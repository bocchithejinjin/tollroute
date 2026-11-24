"""Google Routes API（Compute Routes）で、経路の所要時間と日本の ETC 料金を取得する。

Google が自分で返す候補（通常・有料道路を避ける）は「全部高速」か「高速なし」に偏りやすい。
そこで、自作エンジンが選んだ「乗る IC・降りる IC」を経由地（via）にした問い合わせも併せて行い、
中間の候補（一部だけ高速に乗る）も Google の所要時間・料金で確かめる。
"""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = (
    "routes.description,routes.distanceMeters,routes.duration,"
    "routes.travelAdvisory.tollInfo,routes.polyline.encodedPolyline"
)
MAX_PARALLEL = 4


class GoogleRoutesError(Exception):
    pass


@dataclass(frozen=True)
class Candidate:
    seconds: Decimal
    fare: Decimal | None
    distance: int
    description: str
    polyline: str
    via: tuple[tuple[float, float], ...] = ()
    # 経由地を指定した問い合わせのときの、自作エンジン側の案（画面の説明用）。
    hint: dict = field(default_factory=dict, compare=False, hash=False)


def make_request(origin, destination, departure_time=None, *, avoid_tolls=False, via=()):
    def waypoint(point):
        return {"location": {"latLng": {"latitude": point[0], "longitude": point[1]}}}

    payload = {
        "origin": waypoint(origin),
        "destination": waypoint(destination),
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
        "computeAlternativeRoutes": not via,
        "extraComputations": ["TOLLS"],
        "routeModifiers": {"tollPasses": ["JP_ETC"]},
        "languageCode": "ja",
    }
    if avoid_tolls:
        payload["routeModifiers"]["avoidTolls"] = True
    if via:
        payload["intermediates"] = [{**waypoint(point), "via": True} for point in via]
    if departure_time:
        payload["departureTime"] = departure_time
    return payload


def toll_yen(route):
    """ETC の推定料金（円）。有料区間がなければ 0、料金が読み取れなければ None。"""
    advisory = route.get("travelAdvisory") or {}
    if "tollInfo" not in advisory:
        return Decimal(0)
    prices = (advisory["tollInfo"] or {}).get("estimatedPrice") or []
    if len(prices) != 1 or prices[0].get("currencyCode") != "JPY":
        return None
    price = prices[0]
    if "units" not in price and "nanos" not in price:
        return None
    try:
        fare = Decimal(price.get("units", 0)) + Decimal(price.get("nanos", 0)) / 10**9
    except (InvalidOperation, TypeError):
        return None
    return fare if fare.is_finite() and fare >= 0 else None


def compute_routes(api_key, payload, *, via=(), hint=None):
    request = Request(ENDPOINT, data=json.dumps(payload).encode(), headers={
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    })
    try:
        with urlopen(request, timeout=8) as response:
            routes = json.load(response).get("routes", [])
        candidates = []
        for route in routes:
            duration = route["duration"]
            if not duration.endswith("s"):
                raise ValueError("Invalid duration")
            seconds = Decimal(duration.removesuffix("s"))
            distance = route.get("distanceMeters", 0)
            if not seconds.is_finite() or seconds < 0 or distance < 0:
                raise ValueError("Invalid route metrics")
            candidates.append(Candidate(
                seconds, toll_yen(route), distance,
                route.get("description") or "経路名なし",
                (route.get("polyline") or {}).get("encodedPolyline", ""),
                tuple(via), hint or {},
            ))
        return candidates
    except HTTPError as exc:
        raise GoogleRoutesError(f"HTTP {exc.code}") from None
    except (OSError, ValueError, TypeError, KeyError, AttributeError, InvalidOperation):
        raise GoogleRoutesError("Route response unavailable") from None


def pareto(candidates):
    """料金が分かる候補のうち「これより速くて安い候補がない」ものを、所要時間順に返す。"""
    known = sorted((c for c in candidates if c.fare is not None), key=lambda c: (c.seconds, c.fare))
    front = []
    for candidate in known:
        if not front or candidate.fare < front[-1].fare:
            front.append(candidate)
    return front


@dataclass(frozen=True)
class Hint:
    """自作エンジンの案: 乗る IC・降りる IC のそばの一般道の地点と、高速区間で通る JCT。"""
    entry: tuple[float, float]
    exit: tuple[float, float]
    junctions: tuple[tuple[float, float], ...] = ()
    to_exit_min: float = 0.0  # エンジンが見積もった、出発から降りる IC までの時間（3 区間目の出発時刻に使う）
    info: dict = field(default_factory=dict, compare=False, hash=False)


def _rfc3339(when):
    return when.isoformat(timespec="seconds") if when is not None else None


def _first(found):
    return found[0] if isinstance(found, list) and found else None


def _join(hint, legs):
    """3 区間の結果を 1 つの候補にする。一般道の区間で有料道路を使った結果は、その案になっていないので捨てる。"""
    first, middle, last = legs
    if first is None or middle is None or last is None:
        return None
    if first.fare != 0 or last.fare != 0 or middle.fare == 0:
        return None
    return Candidate(
        first.seconds + middle.seconds + last.seconds, middle.fare,
        first.distance + middle.distance + last.distance, middle.description,
        "|".join((first.polyline, middle.polyline, last.polyline)),
        (hint.entry, *hint.junctions, hint.exit), hint.info,
    )


def search_candidates(api_key, origin, destination, departure, *, hints=(), now=None):
    """Google の候補と、自作エンジンの案（乗り降りの IC を指定）を Google で確かめた候補をまとめて返す。

    departure: 出発日時（タイムゾーン付き）。None は「今すぐ」（now を基準に区間の出発時刻を決める）。
    案ごとに「出発地 → 乗る IC のそばの一般道」「乗る IC → 降りる IC」「降りる IC のそば → 目的地」の 3 区間に分け、
    一般道の区間は有料道路を避けて問い合わせる。1 回の経路にまとめると、降りる IC を通ったあとも
    Google が高速を乗り継いでしまい、指定した案にならないため。
    戻り値: (候補（所要時間順。料金の分かる候補は互いに優劣のないものだけ）, 有料回避の検索に失敗したか)
    """
    from datetime import timedelta

    base = departure or now
    start = _rfc3339(departure)

    def call(payload, **kwargs):
        try:
            return compute_routes(api_key, payload, **kwargs)
        except GoogleRoutesError as exc:
            return exc

    def single(a, b, when, *, avoid_tolls=False, via=()):
        payload = make_request(a, b, _rfc3339(when), avoid_tolls=avoid_tolls, via=via)
        payload["computeAlternativeRoutes"] = False
        return call(payload)

    entries = sorted({h.entry for h in hints})
    exits = sorted({(h.exit, h.to_exit_min) for h in hints})
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        # 1 回目: Google 自身の候補と、一般道の区間（乗る IC まで・降りる IC から）
        normal = pool.submit(call, make_request(origin, destination, start))
        free = pool.submit(call, make_request(origin, destination, start, avoid_tolls=True))
        to_entry = {e: pool.submit(single, origin, e, departure, avoid_tolls=True) for e in entries}
        from_exit = {(x, m): pool.submit(single, x, destination,
                                         base + timedelta(minutes=m) if base else None, avoid_tolls=True)
                     for x, m in exits}
        to_entry = {k: _first(f.result()) for k, f in to_entry.items()}
        from_exit = {k: _first(f.result()) for k, f in from_exit.items()}
        # 2 回目: 高速の区間。乗る時刻で料金（深夜・休日割引など）が変わるので、実際に乗る時刻で問い合わせる
        middle = {}
        for hint in hints:
            first = to_entry.get(hint.entry)
            if first is None or from_exit.get((hint.exit, hint.to_exit_min)) is None:
                continue
            when = base + timedelta(seconds=float(first.seconds)) if base else None
            middle[hint] = pool.submit(single, hint.entry, hint.exit, when, via=hint.junctions)
        middle = {k: _first(f.result()) for k, f in middle.items()}
        normal, free = normal.result(), free.result()

    if isinstance(normal, GoogleRoutesError):
        raise normal
    low_cost_search_failed = isinstance(free, GoogleRoutesError)
    candidates = list(normal) + ([] if low_cost_search_failed else list(free))
    for hint, mid in middle.items():
        joined = _join(hint, (to_entry[hint.entry], mid, from_exit[(hint.exit, hint.to_exit_min)]))
        if joined is not None:
            candidates.append(joined)

    unique = {}
    for candidate in candidates:
        # 同じ経路が複数の問い合わせで返る場合は、料金が分かる結果を優先する。
        key = candidate.polyline or candidate
        current = unique.get(key)
        if current is None or (current.fare is None and candidate.fare is not None):
            unique[key] = candidate
    front = pareto(unique.values())
    # 料金が不明な候補は、料金の分かる最速の候補より速いときだけ残す（参考として表示する）。
    fastest_known = front[0].seconds if front else Decimal("Infinity")
    unknown = [c for c in unique.values() if c.fare is None and c.seconds < fastest_known]
    ordered = sorted(front + unknown, key=lambda c: (
        c.seconds, c.fare if c.fare is not None else Decimal("Infinity"),
    ))
    return ordered, low_cost_search_failed
