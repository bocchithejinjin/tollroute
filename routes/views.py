from datetime import datetime, timedelta
from urllib.parse import urlencode

from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from engine.search import Searcher, pick

from . import demo
from .ratelimit import limited
from .geocode import STATION_LEVEL, GeocoderUnavailable, geocode
from .travel import EstimateProvider, TravelTimeError, get_provider

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
    return render(request, "routes/index.html", {"places": places, "source": demo.SOURCE})


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


def _plan_json(p, net, depart, o, d, o_name, d_name):
    arrive = depart + timedelta(minutes=p.minutes)
    base = {"minutes": round(p.minutes, 1), "fare": p.fare, "arrive": arrive.strftime("%H:%M")}
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
    local_min = next(p.minutes for p in front if p.entry is None)
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


@require_GET
@limited
def api_search(request):
    try:
        o_name, *o = _point(request.GET.get("origin", "yokohama"))
        d_name, *d = _point(request.GET.get("dest", "shinjuku"))
        depart = datetime.fromisoformat(request.GET.get("depart") or datetime.now().strftime("%Y-%m-%dT%H:%M"))
        budget = int(request.GET.get("budget", "1000"))
        if budget < 0:
            raise ValueError("予算は 0 円以上にしてください")
    except GeocoderUnavailable as exc:
        return JsonResponse({"error": str(exc)}, status=503)
    except (ValueError, TypeError) as exc:
        return JsonResponse({"error": str(exc) or "入力が正しくありません"}, status=400)

    net, tariffs, _ = demo.build()
    searcher = Searcher(net, tariffs)
    provider = get_provider()
    provider_note = None
    try:
        times = local_times(provider, net, o, d)
    except TravelTimeError as exc:
        # ルート検索エンジンに接続できないときは概算で答える（画面に理由を出す）
        provider = EstimateProvider()
        provider_note = f"{exc}。一般道の所要時間は概算に切り替えました。"
        times = local_times(provider, net, o, d)
    front = _search(searcher, depart, times)
    approximate = searcher.stats.get("approximate", False)
    best = pick(front, budget)

    # 出発時刻を前後 2 時間の範囲でずらすと、同じくらいの時間でもっと安くならないか
    shifts = []
    for off in range(-120, 121, 15):
        if off == 0:
            continue
        f2 = _search(searcher, depart + timedelta(minutes=off), times)
        p2 = pick(f2, budget)
        if p2.fare < best.fare and p2.minutes <= best.minutes + 10:
            shifts.append({"offset": off, "depart": (depart + timedelta(minutes=off)).strftime("%H:%M"),
                           "fare": p2.fare, "minutes": round(p2.minutes, 1), "saving": best.fare - p2.fare})
    shift = max(shifts, key=lambda s: (s["saving"], -abs(s["offset"]))) if shifts else None

    local_min = next(p.minutes for p in front if p.entry is None)

    def plan(p, label=None):
        j = _plan_json(p, net, depart, o, d, o_name, d_name)
        ypm = yen_per_minute(p, local_min)
        j.update(label=label, saved=round(local_min - p.minutes), yen_per_min=round(ypm, 1) if ypm is not None else None)
        return j

    return JsonResponse({
        "origin": {"name": o_name, "lat": o[0], "lon": o[1]},
        "dest": {"name": d_name, "lat": d[0], "lon": d[1]},
        "depart": depart.strftime("%Y-%m-%d %H:%M"),
        "budget": budget,
        "best": plan(best),
        "options": [plan(p, label) for label, p in choose_options(front, budget)],
        "local_only": plan(next(p for p in front if p.entry is None), "一般道だけ"),
        "front": [plan(p) for p in front],
        "shift": shift,
        "approximate": approximate,
        "notes": [
            *([provider_note] if provider_note else []),
            provider.description,
            "高速道路の区間の距離は IC 間の直線距離から推定した概算です（公式の距離に置き換え予定）。料金も概算です。",
            "経由地を参考に Google マップが経路を再検索します。表示された経路と料金を出発前に確認してください。",
            "首都圏の「起終点を基本とした料金」、中央道の 630 円上限は未対応です。出入口の方向制限は首都高の一部に反映しています。",
        ],
    })
