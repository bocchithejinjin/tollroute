import math
import os
import threading
from datetime import datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from engine.calendar import KNOWN_UNTIL, known
from engine.search import Plan, Searcher, pick

from . import demo, google_routes
from .ratelimit import limited
from .geocode import STATION_LEVEL, GeocoderUnavailable, geocode
from .travel import EstimateProvider, OsrmProvider, TravelTimeError, get_provider

JST = ZoneInfo("Asia/Tokyo")
MAX_IC_KM = 30  # 出発地・目的地から最寄りの IC までの直線距離の上限（デモ道路網の対象範囲）


def parse_departure(value: str):
    """出発日時（日本時間、タイムゾーンなし）。タイムゾーン付きの値は日本時間に直す。"""
    depart = datetime.fromisoformat(value)
    if depart.tzinfo is not None:
        depart = depart.astimezone(JST).replace(tzinfo=None)
    if not 2000 <= depart.year <= 2100:
        raise ValueError("出発日時を確認してください")
    return depart.replace(second=0, microsecond=0)


def check_coverage(net, point, label):
    nearest = min(demo.km_between(point, (x.lat, x.lon)) for x in net.nodes.values())
    if nearest > MAX_IC_KM:
        raise ValueError(f"{label}が対応範囲（横浜〜新宿周辺のデモ道路網）から離れすぎています")

POOL_LABEL = {"nexco": "NEXCO", "shutoko": "首都高", "daisan_keihin": "第三京浜", "yokohama_shindo": "横浜新道",
              "aqualine": "アクアライン"}


@require_GET
def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT PostGIS_Version()")
        (version,) = cursor.fetchone()

    return JsonResponse({"status": "ok", "postgis": version})


@require_GET
def index(request):
    places = [{"id": k, "name": v[0]} for k, v in demo.PLACES.items()]
    return render(request, "routes/index.html", {
        "places": places, "source": demo.SOURCE, "google_routes": bool(settings.GOOGLE_ROUTES_API_KEY),
    })


def _point(value: str):
    """駅の ID・「緯度,経度」・住所のどれかを (名前, 緯度, 経度) にする。"""
    value = value.strip()
    if value in demo.PLACES:
        return demo.PLACES[value]
    parts = value.replace("，", ",").split(",")
    if len(parts) == 2:
        try:
            lat, lon = (float(x) for x in parts)
        except ValueError:
            lat = None
        if lat is not None:
            if not (20 <= lat <= 46 and 122 <= lon <= 154):
                raise ValueError("日本の範囲外の座標です")
            return (f"{lat:.5f}, {lon:.5f}", lat, lon)
    place = geocode(value)
    if place.level == STATION_LEVEL:  # 駅名検索（HeartRails Express）で見つけた駅
        return (f"{place.name}（駅）", place.lat, place.lon)
    return (f"{place.name}（{place.level_label}まで一致）", place.lat, place.lon)


MAX_CANDIDATES = 15  # 乗る IC・降りる IC の候補数（外部 API を使うときの問い合わせ回数を抑える）


def local_times(provider, net, o, d):
    """一般道の所要時間をまとめて求める（出発地 → 近い IC、近い IC → 目的地、一般道だけ）。

    出発時刻をずらして何度も検索するときも、同じ結果を使い回す（問い合わせを 1 回にする）。
    """
    pos = lambda x: (x.lat, x.lon)
    ent = sorted((x for x in net.nodes.values() if x.can_enter), key=lambda x: demo.km_between(o, pos(x)))[:MAX_CANDIDATES]
    ext = sorted((x for x in net.nodes.values() if x.can_exit), key=lambda x: demo.km_between(pos(x), d))[:MAX_CANDIDATES]
    t_in = provider.from_origin(o, [pos(x) for x in ent])
    t_out = provider.to_dest([pos(x) for x in ext], d)
    origin = {x.id: m for x, m in zip(ent, t_in) if m is not None}
    dest = {x.id: m for x, m in zip(ext, t_out) if m is not None}
    local = provider.between(o, d)
    if local is None:
        raise ValueError("一般道で出発地から目的地までのルートが見つかりません")
    lb = {n: demo.km_between(pos(x), d) / 100 * 60 for n, x in net.nodes.items()}
    return origin, dest, local, lb


def _search(searcher, depart, times):
    origin, dest, local, lb = times
    return searcher.search(depart, origin, dest, local, lb)


def _nav_links(points):
    """出発地・経由地・目的地の座標から Google マップの経路リンクを作る。"""
    ll = lambda p: f"{p[0]:.6f},{p[1]:.6f}"
    q = {"api": "1", "origin": ll(points[0]), "destination": ll(points[-1]), "travelmode": "driving"}
    if len(points) > 2:
        q["waypoints"] = "|".join(ll(p) for p in points[1:-1])
    return {"google": "https://www.google.com/maps/dir/?" + urlencode(q)}


def _nav_waypoints(entry, junctions, exit_):
    nodes = [entry]
    if junctions:
        nodes.append(junctions[len(junctions) // 2])
    nodes.append(exit_)
    # 八王子ICの代表座標は上下線を区別せず、Google マップで大きな折り返しを起こす。
    return [(node.lat, node.lon) for node in nodes if node.id != "hachioji"]


def clock(depart, minutes):
    """到着時刻の表示。日をまたぐときは「翌日」を付ける。"""
    arrive = depart + timedelta(minutes=minutes)
    days = (arrive.date() - depart.date()).days
    return arrive.strftime("%H:%M") if days == 0 else f"{'翌日' if days == 1 else f'{days}日後'} {arrive:%H:%M}"


def _plan_json(p, net, depart, o, d, o_name, d_name):
    base = {"minutes": round(p.minutes, 1), "fare": p.fare, "arrive": clock(depart, p.minutes)}
    if p.entry is None:
        return {**base, "entry": None, "exit": None, "runs": [], "roads": [],
                "steps": [{"kind": "local", "text": f"一般道で {o_name} → {d_name}", "minutes": round(p.minutes)}],
                "nav": _nav_links([o, d])}

    entry, exit_ = net.nodes[p.entry], net.nodes[p.exit]
    first, last = p.steps[0], p.steps[-1]
    to_entry = (first.t0 - depart).total_seconds() / 60
    from_exit = p.minutes - (last.t1 - depart).total_seconds() / 60

    # 道路ごとにまとめた道順
    steps = [{"kind": "local", "text": f"一般道で {o_name} → {entry.name}", "minutes": round(to_entry)}]
    roads, junctions = [], []
    for s in p.steps:
        if steps[-1]["kind"] == "highway" and steps[-1]["road"] == s.edge.road:
            steps[-1]["to"] = net.nodes[s.edge.v].name
            steps[-1]["_t1"] = s.t1
        else:
            if steps[-1]["kind"] == "highway":
                junctions.append(net.nodes[s.edge.u])  # 道路が変わる地点（JCT など）
            steps.append({"kind": "highway", "road": s.edge.road, "from": net.nodes[s.edge.u].name,
                          "to": net.nodes[s.edge.v].name, "_t0": s.t0, "_t1": s.t1})
            roads.append(s.edge.road)
    for st in steps:
        if st["kind"] == "highway":
            t0, t1 = st.pop("_t0"), st.pop("_t1")
            st["minutes"] = round((t1 - t0).total_seconds() / 60)
            st["text"] = f"{st['road']}で {st['from']} → {st['to']}（{t0:%H:%M}〜{t1:%H:%M}）"
    steps.append({"kind": "local", "text": f"一般道で {exit_.name} → {d_name}", "minutes": round(from_exit)})

    via = _nav_waypoints(entry, junctions, exit_)
    return {
        **base,
        "entry": entry.name,
        "exit": exit_.name,
        "enter_at": first.t0.strftime("%H:%M"),
        "exit_at": last.t1.strftime("%H:%M"),
        "roads": roads,
        "steps": steps,
        "runs": [{"pool": POOL_LABEL.get(r.pool, r.pool), "entry": net.nodes[r.entry].name,
                  "exit": net.nodes[r.exit].name, "base": r.base, "fare": r.fare, "discount": r.discount}
                 for r in p.runs],
        "nav": _nav_links([o, *via, d]),
    }


MIN_SAVING = 5  # 「お得」と呼ぶのに必要な短縮（分）


def yen_per_minute(p, local_min: float) -> float | None:
    """一般道だけより 1 分早く着くのに何円かかるか（小さいほどお得）。短縮が MIN_SAVING 分未満なら None。"""
    saved = local_min - p.minutes
    if p.entry is None or saved < MIN_SAVING:
        return None
    return p.fare / saved


def choose_options(front, budget: int, n: int = 5):
    """予算内の候補から、[(ラベル, プラン)] を最大 n 個選ぶ。

    - 最速: 予算内でいちばん早い
    - いちばんお得: 1 分短縮あたりの金額がいちばん安い
    - 安さ重視: 最速の短縮効果の半分以上を、いちばん安く得られる
    同じプランが重なったら、お得度の高い順にほかの候補（通る道路が違うものを優先）で埋める。
    """
    local_min = next((p.minutes for p in front if p.entry is None), math.inf)
    within = [p for p in front if p.fare <= budget and p.entry is not None]
    if not within:
        return []
    fastest = min(within, key=lambda p: (p.minutes, p.fare))
    valued = [p for p in within if yen_per_minute(p, local_min) is not None]
    best_value = min(valued, key=lambda p: (yen_per_minute(p, local_min), p.minutes)) if valued else None
    half = (local_min - fastest.minutes) / 2
    cheap_ok = [p for p in within if local_min - p.minutes >= half]
    cheapest = min(cheap_ok, key=lambda p: (p.fare, p.minutes)) if cheap_ok else None

    roads = lambda p: tuple(dict.fromkeys(s.edge.road for s in p.steps))
    chosen: list[tuple[str, object]] = []
    for label, p in (("最速", fastest), ("いちばんお得", best_value), ("安さ重視", cheapest)):
        if p is not None and all(p is not q for _, q in chosen):
            chosen.append((label, p))
    # 足りなければ埋める。点数 = すでに選んだルートとの所要時間の差（分）÷ お得度（円/分）。
    # 所要時間がばらけていて、お得なものほど選ばれる。通る道路が同じで所要時間の差が 5 分未満のものは、
    # ほぼ同じルートなので選ばない
    def near_duplicate(p):
        return any(roads(p) == roads(q) and abs(p.minutes - q.minutes) < 5 for _, q in chosen)

    def score(p):
        gap = min(abs(p.minutes - q.minutes) for _, q in chosen)
        return gap / max(yen_per_minute(p, local_min), 1e-9)

    while len(chosen) < n:
        rest = [p for p in valued if all(p is not q for _, q in chosen) and not near_duplicate(p)]
        if not rest:
            break
        chosen.append(("ほかの候補", max(rest, key=score)))
    return sorted(chosen[:n], key=lambda lp: (lp[1].minutes, lp[1].fare))


# Google で確かめる自作エンジンの案の数。1 回の検索の問い合わせは最大 2 + 3 × この数
GOOGLE_HINTS = int(os.environ.get("GOOGLE_ROUTES_HINTS", "4"))


def _junctions(p, net):
    """道路が変わる地点（JCT など）のノード。"""
    found, previous = [], None
    for s in p.steps:
        if previous is not None and s.edge.road != previous:
            found.append(net.nodes[s.edge.u])
        previous = s.edge.road
    return found


_local_side_cache: dict[str, tuple[float, float] | None] = {}


def local_side(provider, nodes):
    """IC のそばの、有料道路を使わずに行ける一般道の地点（OSRM で求める）。求められなければ None。

    IC の座標は高速の本線上にあるので、そのまま Google に渡すと本線の途中から乗り降りすることになり、
    料金が出ない・指定した IC で降りない経路になる。
    """
    todo = [n for n in nodes if n.id not in _local_side_cache]
    if todo and isinstance(provider, OsrmProvider):
        try:
            access = provider.access_points([(n.lat, n.lon) for n in todo])
            for node, (lat, lon) in zip(todo, access):
                found = provider._get(f"/nearest/v1/driving/{lon:.6f},{lat:.6f}?number=1&exclude=toll")
                lon2, lat2 = found["waypoints"][0]["location"]
                _local_side_cache[node.id] = (lat2, lon2)
        except (TravelTimeError, KeyError, IndexError):
            return {}
    return {n.id: _local_side_cache[n.id] for n in nodes if _local_side_cache.get(n.id)}


def google_hints(front, net, budget, depart, provider, n=GOOGLE_HINTS):
    """自作エンジンの候補から、Google で確かめる「乗る IC・降りる IC」の案（google_routes.Hint）を最大 n 個選ぶ。

    Google 自身の候補は「全部高速」か「高速なし」に偏るので、中間の料金の案を幅広く選ぶ。
    エンジンの料金は概算なので、予算を少し超える案も確かめる。
    """
    limit = budget * 1.5 + 500
    plans = [p for p in front if p.entry is not None and p.fare <= limit]
    plans.sort(key=lambda p: (p.fare, p.minutes))
    picked = [p for _, p in choose_options(front, budget)]
    spread = [plans[round(i * (len(plans) - 1) / (n - 1))] for i in range(n)] if len(plans) > n else plans
    chosen, seen = [], set()
    for p in [*picked, *spread]:
        junctions = _junctions(p, net)
        key = (p.entry, p.exit, tuple(j.id for j in junctions))
        if key not in seen:
            seen.add(key)
            chosen.append((p, junctions))
    chosen = chosen[:n]
    sides = local_side(provider, [net.nodes[x] for p, _ in chosen for x in (p.entry, p.exit)])
    hints = []
    for p, junctions in chosen:
        if p.entry not in sides or p.exit not in sides:
            continue
        entry, exit_ = net.nodes[p.entry], net.nodes[p.exit]
        hints.append(google_routes.Hint(
            sides[p.entry], sides[p.exit], tuple((j.lat, j.lon) for j in junctions),
            to_exit_min=round((p.steps[-1].t1 - depart).total_seconds() / 60),
            info={"entry": entry.name, "exit": exit_.name,
                  "roads": list(dict.fromkeys(s.edge.road for s in p.steps)), "engine_fare": p.fare},
        ))
    return hints


def _google_labels(candidates, budget):
    """(予算内で最速, いちばん安い, お得) の添字。お得 = 最安の候補より 1 分早く着くのにかかる金額が最小。"""
    known = [i for i, c in enumerate(candidates) if c.fare is not None]
    best = next((i for i in known if candidates[i].fare <= budget), None)
    cheapest = min(known, key=lambda i: (candidates[i].fare, candidates[i].seconds), default=None)
    balance = None
    if best is not None and cheapest is not None and best != cheapest:
        base = candidates[cheapest]

        def cost_per_minute(i):
            saved = float(base.seconds - candidates[i].seconds) / 60
            return float(candidates[i].fare - base.fare) / saved if saved >= MIN_SAVING else None

        middle = [i for i in known if i not in (best, cheapest) and candidates[i].fare <= budget
                  and cost_per_minute(i) is not None]
        balance = min(middle, key=cost_per_minute, default=None)
    return best, cheapest, balance


_google_quota = {"day": None, "used": 0}
_google_quota_lock = threading.Lock()


def google_quota_available() -> bool:
    """Google を使う検索の回数を数え、今日の上限内なら True（API の利用料金の使いすぎを防ぐ）。"""
    limit = settings.GOOGLE_ROUTES_DAILY_SEARCHES
    if limit <= 0:
        return True
    today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    with _google_quota_lock:
        if _google_quota["day"] != today:
            _google_quota.update(day=today, used=0)
        if _google_quota["used"] >= limit:
            return False
        _google_quota["used"] += 1
        return True


def _google_search(search_input, o, d, depart, hints_for):
    jst = ZoneInfo("Asia/Tokyo")
    now = datetime.now(jst)
    departure_time = None
    if depart is not None:
        depart = depart.astimezone(jst) if depart.tzinfo else depart.replace(tzinfo=jst)
        if depart <= now - timedelta(minutes=10):
            return JsonResponse({"error": "今すぐ、または未来の出発日時を指定してください。"}, status=400)
        # 少し前の時刻（フォームを開いたままだった場合など）は「今すぐ」として扱う。
        departure_time = depart.isoformat() if depart > now else None
        depart = max(depart, now.replace(second=0, microsecond=0))
    else:
        depart = now.replace(second=0, microsecond=0)
    budget = search_input["budget"]
    try:
        hints = hints_for(depart.replace(tzinfo=None))
    except (ValueError, TravelTimeError):
        hints = []  # エンジンの案が作れなくても、Google 自身の候補は出す。
    try:
        candidates, low_cost_search_failed = google_routes.search_candidates(
            settings.GOOGLE_ROUTES_API_KEY, o, d, depart if departure_time else None, hints=hints, now=now,
        )
    except google_routes.GoogleRoutesError:
        return None  # 呼び出し元が自作エンジンの結果で答える

    def describe(candidate):
        hint = candidate.hint
        if not hint:
            return candidate.description
        # 道路名は Google が実際に返した経路のもの（指定した IC の手前で降りる経路になることもある）
        return f"{hint['entry']} から乗る案 · {candidate.description}"

    routes = [{
        "description": describe(candidate),
        "source": "ic" if candidate.via else "google",
        "minutes": round(float(candidate.seconds / 60), 1),
        "arrive": clock(depart, float(candidate.seconds) / 60),
        "distance_km": round(candidate.distance / 1000, 1),
        "fare": float(candidate.fare) if candidate.fare is not None else None,
        "within_budget": candidate.fare is not None and candidate.fare <= budget,
        "nav": _nav_links([o, *candidate.via, d]) if candidate.via else None,
    } for candidate in candidates]
    best_index, cheapest_index, balance_index = _google_labels(candidates, budget)
    response = JsonResponse({
        **search_input, "depart": depart.strftime("%Y-%m-%d %H:%M"), "provider": "google_routes",
        "routes": routes, "best": routes[best_index] if best_index is not None else None,
        "cheapest_index": cheapest_index, "balance_index": balance_index,
        "low_cost_search_failed": low_cost_search_failed,
        "nav": _nav_links([o, d]),
    })
    response["Cache-Control"] = "no-store"
    return response


def _local_times_with_fallback(net, o, d):
    provider = get_provider()
    try:
        return provider, None, local_times(provider, net, o, d)
    except TravelTimeError as exc:
        # ルート検索エンジンに接続できないときは概算で答える（画面に理由を出す）
        provider = EstimateProvider()
        return provider, f"{exc}。一般道の所要時間は概算に切り替えました。", local_times(provider, net, o, d)


@require_GET
@limited
def api_search(request):
    try:
        origin = request.GET.get("origin", "yokohama").strip()
        dest = request.GET.get("dest", "shinjuku").strip()
        o_name, *o = _point(origin)
        d_name, *d = _point(dest)
        scheduled = request.GET.get("depart")
        depart = parse_departure(scheduled) if scheduled else None
        # 「今すぐ」の検索では、出発を早める提案をしない
        now_mode = request.GET.get("now") in {"1", "true"} or depart is None
        try:
            budget = int(request.GET.get("budget", "1000"))
        except ValueError:
            raise ValueError("予算は整数（円）で指定してください") from None
        if not 0 <= budget <= 1_000_000:
            raise ValueError("予算は 0〜1,000,000 円で指定してください")
    except GeocoderUnavailable as exc:
        return JsonResponse({"error": str(exc)}, status=503)
    except (ValueError, TypeError) as exc:
        return JsonResponse({"error": str(exc) or "入力が正しくありません"}, status=400)

    search_input = {
        "origin": {"name": o_name, "lat": o[0], "lon": o[1]},
        "dest": {"name": d_name, "lat": d[0], "lon": d[1]},
        "budget": budget,
    }
    net, tariffs, _ = demo.build()
    searcher = Searcher(net, tariffs)
    google_note = None
    if settings.GOOGLE_ROUTES_API_KEY and not google_quota_available():
        google_note = "今日の Google での確認回数の上限に達したため、自作エンジンの概算で表示しています。"
    elif settings.GOOGLE_ROUTES_API_KEY:
        def hints_for(when):
            # 範囲外なら ValueError になり、Google 自身の候補だけで答える
            check_coverage(net, o, "出発地")
            check_coverage(net, d, "目的地")
            provider, _, times = _local_times_with_fallback(net, o, d)
            return google_hints(_search(searcher, when, times), net, budget, when, provider)

        response = _google_search(search_input, o, d, depart, hints_for)
        if response is not None:
            return response
        google_note = "Google の経路を取得できなかったため（利用上限・通信エラーなど）、自作エンジンの概算で表示しています。"

    if depart is None:
        depart = datetime.now(JST).replace(tzinfo=None, second=0, microsecond=0)
    try:
        check_coverage(net, o, "出発地")
        check_coverage(net, d, "目的地")
        provider, provider_note, times = _local_times_with_fallback(net, o, d)
        front = _search(searcher, depart, times)
    except OverflowError:
        return JsonResponse({"error": "出発日時を確認してください"}, status=400)
    except ValueError as exc:  # 一般道でつながらない地点、料金データのない日時
        return JsonResponse({"error": str(exc)}, status=400)
    approximate = searcher.stats.get("approximate", False)
    local_plan = next((p for p in front if p.entry is None), None) or Plan(times[2], 0, None, None)
    calendar_note = None
    if not known(depart.date()):
        calendar_note = (f"{KNOWN_UNTIL:%Y年%m月%d日}より後の祝日・休日割引の適用除外日はまだ登録していません。"
                         "休日割引の有無が実際と違う可能性があります。")
        approximate = True
    best = pick(front, budget)

    # 出発時刻を前後 2 時間の範囲でずらすと、同じくらいの時間でもっと安くならないか
    shifts = []
    for off in range(-120, 121, 15):
        if off == 0 or (now_mode and off < 0):
            continue
        try:
            f2 = _search(searcher, depart + timedelta(minutes=off), times)
        except (ValueError, OverflowError):
            continue
        p2 = pick(f2, budget)
        if p2.fare < best.fare and p2.minutes <= best.minutes + 10:
            shifts.append({"offset": off, "depart": (depart + timedelta(minutes=off)).strftime("%H:%M"),
                           "fare": p2.fare, "minutes": round(p2.minutes, 1), "saving": best.fare - p2.fare})
    shift = max(shifts, key=lambda s: (s["saving"], -abs(s["offset"]))) if shifts else None

    local_min = local_plan.minutes

    def plan(p, label=None):
        j = _plan_json(p, net, depart, o, d, o_name, d_name)
        ypm = yen_per_minute(p, local_min)
        j.update(label=label, saved=round(local_min - p.minutes), yen_per_min=round(ypm, 1) if ypm is not None else None)
        return j

    return JsonResponse({
        **search_input,
        "depart": depart.strftime("%Y-%m-%d %H:%M"),
        "best": plan(best),
        "options": [plan(p, label) for label, p in choose_options(front, budget)],
        "local_only": plan(local_plan, "一般道だけ"),
        "front": [plan(p) for p in front],
        "shift": shift,
        "approximate": approximate,
        "notes": [
            *([calendar_note] if calendar_note else []),
            *([google_note] if google_note else []),
            *([provider_note] if provider_note else []),
            provider.description,
            "高速道路の区間の距離は IC 間の直線距離から推定した概算です（公式の距離に置き換え予定）。料金も概算です。",
            "経由地を参考に Google マップが経路を再検索します。表示された経路と料金を出発前に確認してください。",
            "首都圏の「起終点を基本とした料金」、中央道の 630 円上限は未対応です。出入口の方向制限は首都高の一部に反映しています。",
        ],
    })
