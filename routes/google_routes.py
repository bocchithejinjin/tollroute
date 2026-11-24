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


def search_candidates(api_key, origin, destination, departure_time, *, hints=()):
    """Google の候補と、経由地を指定した候補をまとめて返す。

    hints: [(経由地の座標の列, 説明用の dict), ...]（自作エンジンが選んだ乗り降りの IC）。
    戻り値: (候補（所要時間順。料金の分かる候補は互いに優劣のないものだけ）, 有料回避の検索に失敗したか)
    """
    jobs = [("normal", make_request(origin, destination, departure_time), (), None),
            ("free", make_request(origin, destination, departure_time, avoid_tolls=True), (), None)]
    jobs += [("via", make_request(origin, destination, departure_time, via=via), via, hint)
             for via, hint in hints]

    def run(job):
        kind, payload, via, hint = job
        try:
            return kind, compute_routes(api_key, payload, via=via, hint=hint)
        except GoogleRoutesError as exc:
            return kind, exc

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        results = list(pool.map(run, jobs))

    normal = results[0][1]
    if isinstance(normal, GoogleRoutesError):
        raise normal
    low_cost_search_failed = isinstance(results[1][1], GoogleRoutesError)
    candidates = list(normal)
    for kind, found in results[1:]:
        if isinstance(found, GoogleRoutesError):
            continue  # 補助の候補が取れなくても、通常の候補は返す。
        if kind == "via":
            # 経由地の IC を一般道で素通りした（高速に乗らなかった）結果は、指定した案になっていない。
            found = [c for c in found if c.fare != 0]
        candidates += found

    unique = {}
    for candidate in candidates:
        # 同じ経路が複数の問い合わせで返る場合は、料金が分かる・経由地のない（Google 自身の）結果を優先する。
        key = candidate.polyline or candidate
        current = unique.get(key)
        if current is None or (current.fare is None and candidate.fare is not None) or (
                current.via and not candidate.via and candidate.fare is not None):
            unique[key] = candidate
    front = pareto(unique.values())
    # 料金が不明な候補は、料金の分かる最速の候補より速いときだけ残す（参考として表示する）。
    fastest_known = front[0].seconds if front else Decimal("Infinity")
    unknown = [c for c in unique.values() if c.fare is None and c.seconds < fastest_known]
    ordered = sorted(front + unknown, key=lambda c: (
        c.seconds, c.fare if c.fare is not None else Decimal("Infinity"),
    ))
    return ordered, low_cost_search_failed
