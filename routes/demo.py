"""操作確認用（デモ）の道路網: 横浜駅〜新宿駅の周辺（東名・首都高・中央道・圏央道・第三京浜）だけ。

【デモ用の概算であること】
- IC の位置は OpenStreetMap（demo_ics.json）。区間の距離は demo_distances.json（NEXCO・第三京浜は公式、首都高は概算）。
- 一般道の所要時間は直線距離 × 1.3 ÷ 時速 20km の概算（ルート検索エンジンの準備ができたら差し替える）。
- 首都圏の「起終点を基本とした料金」、中央道（高井戸〜八王子）の 630 円上限は未対応。出入口の方向制限は首都高の一部に反映。
- 第三京浜の料金は、公式の料金表で確認できた組み合わせ以外は概算。
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from engine.model import Edge, Network, Node
from engine.tariffs import OdTablePool, Tariffs, default_tariffs, round10

ICS = json.loads((Path(__file__).with_name("demo_ics.json")).read_text(encoding="utf-8"))
SOURCE = ICS["_source"]

JCTS = {"ebina_jct", "ohashi_jct", "nishishinjuku_jct", "hachioji_jct"}

# 首都高公式の出入口案内に基づく、乗る方向の隣接ノードと降りる方向の直前ノード。
# https://www.shutoko.jp/driving/route/
RAMP_DIRECTIONS = {
    "youga": (("sangenjaya",), ("sangenjaya",)),
    "sangenjaya": (("ikejiri",), ("ikejiri",)),
    "ikejiri": (("sangenjaya",), ("sangenjaya",)),
    "tomigaya": (("hatsudai_minami",), ("hatsudai_minami",)),
    "hatsudai_minami": (("tomigaya",), ("tomigaya",)),
    "nakano_chojabashi": ((), ()),  # 外回りの入口・内回りの出口に続く北側はデモ網の範囲外。
    "takaido_s": (("eifuku",), ("eifuku",)),
    "hatagaya": (("nishishinjuku_jct",), ("nishishinjuku_jct",)),
    "shinjuku": ((), None),  # 上り入口から先の東側はデモ網の範囲外。西側から上り出口には進める。
}

# (路線名, 料金プール, 区分, 休日割引の対象, 時速, IC の並び)
ROADS = [
    ("東名高速", "nexco", "urban", False, 80,
     ["tokyo", "tomei_kawasaki", "yokohama_aoba", "yokohama_machida", "ebina_jct", "atsugi"]),
    ("中央道", "nexco", "urban", False, 80,
     ["takaido", "chofu", "inagi", "kunitachi_fuchu", "hachioji", "hachioji_jct"]),
    ("圏央道", "nexco", "urban", False, 80,
     ["ebina_jct", "ken_atsugi", "sagamihara_aikawa", "sagamihara", "takaosan", "hachioji_jct"]),
    ("首都高 3 号渋谷線", "shutoko", "normal", False, 50, ["tokyo", "youga", "sangenjaya", "ikejiri", "ohashi_jct"]),
    ("首都高 中央環状線", "shutoko", "normal", False, 50,
     ["ohashi_jct", "tomigaya", "hatsudai_minami", "nishishinjuku_jct", "nakano_chojabashi"]),
    ("首都高 4 号新宿線", "shutoko", "normal", False, 50,
     ["takaido", "takaido_s", "eifuku", "hatagaya", "nishishinjuku_jct", "shinjuku"]),
    ("第三京浜", "daisan_keihin", "normal", False, 70,
     ["hodogaya", "hazawa", "kohoku", "tsuzuki", "keihin_kawasaki", "tamagawa"]),
]

# 第三京浜の公式料金表（普通車、docs/research-fares.md 1-5）。ほかの組み合わせは概算。
DAISAN_OFFICIAL = {
    ("tamagawa", "keihin_kawasaki"): 50, ("tamagawa", "tsuzuki"): 200, ("tamagawa", "kohoku"): 260,
    ("tamagawa", "hazawa"): 390, ("tamagawa", "hodogaya"): 390, ("keihin_kawasaki", "kohoku"): 210,
    ("tsuzuki", "kohoku"): 70,
}

PLACES = {
    "shinjuku": ("新宿駅", 35.6896, 139.7006),
    "yokohama": ("横浜駅", 35.4657, 139.6223),
    "hachioji": ("八王子駅", 35.6557, 139.3389),
    "machida": ("町田駅", 35.5422, 139.4455),
}

LOCAL_DETOUR, LOCAL_KMH = 1.3, 20.0


def km_between(a, b) -> float:
    (la1, lo1), (la2, lo2) = a, b
    x = math.radians(lo2 - lo1) * math.cos(math.radians((la1 + la2) / 2))
    y = math.radians(la2 - la1)
    return 6371.0 * math.hypot(x, y)


def local_minutes(a, b) -> float:
    return km_between(a, b) * LOCAL_DETOUR / LOCAL_KMH * 60


def ic_pos(nid: str):
    ic = ICS["ics"][nid]
    return ic["lat"], ic["lon"]


# 区間の距離: routes/demo_distances.json（NEXCO の区間は公式の距離、首都高は概算。docs/research-demo-distances.md）
DISTANCES = json.loads((Path(__file__).with_name("demo_distances.json")).read_text(encoding="utf-8"))["edges"]
# 0km の区間（東名 東京IC と首都高 用賀、中央道 高井戸IC と首都高 高井戸）は、所要時間が 0 にならないよう最小値にする
MIN_KM = 0.1
# 大都市近郊区間の外（休日割引の対象）。中央道 八王子IC〜八王子JCT（ドラぷらで休日料金が出る）
OUTSIDE_URBAN = {frozenset(("hachioji", "hachioji_jct"))}


def edge_km(a: str, b: str) -> float:
    """区間の距離（km）。調べた値がなければ、IC 間の直線距離 × 1.15 の推定。"""
    e = DISTANCES.get(f"{a}|{b}") or DISTANCES.get(f"{b}|{a}")
    if e is None:
        return round(km_between(ic_pos(a), ic_pos(b)) * 1.15, 2)
    return max(float(e["km"]), MIN_KM)


@lru_cache(maxsize=1)
def build() -> tuple[Network, Tariffs, dict]:
    net = Network()
    for nid, ic in ICS["ics"].items():
        jct = nid in JCTS
        entry_towards, exit_from = RAMP_DIRECTIONS.get(nid, (None, None))
        net.add_node(Node(nid, ic["name"], ic["lat"], ic["lon"],
                          can_enter=not jct and entry_towards != (), can_exit=not jct and exit_from != (),
                          entry_towards=entry_towards, exit_from=exit_from))
    seen = set()
    for road, pool, cls, holiday_ok, kmh, seq in ROADS:
        for a, b in zip(seq, seq[1:]):
            if (a, b) in seen:
                continue
            seen |= {(a, b), (b, a)}
            km = edge_km(a, b)
            c, h = (("normal", True) if frozenset((a, b)) in OUTSIDE_URBAN else (cls, holiday_ok))
            for u, v in ((a, b), (b, a)):
                net.add_edge(Edge(u, v, pool, road, km, km / kmh * 60, c, holiday_ok=h))
    # 第三京浜の料金表（確認できた組み合わせ + 概算）
    seq = ROADS[-1][-1]
    table, estimated = {}, set()
    for i, a in enumerate(seq):
        for b in seq[i + 1:]:
            fare = DAISAN_OFFICIAL.get((a, b)) or DAISAN_OFFICIAL.get((b, a))
            if fare is None:
                km = sum(edge_km(x, y) for x, y in zip(seq[seq.index(a):], seq[seq.index(a) + 1:seq.index(b) + 1]))
                fare = max(50, round10(km * 24.6 * 1.1 * 0.8))
                estimated.add(frozenset((a, b)))
            table[(a, b)] = table[(b, a)] = fare
    tariffs = default_tariffs({"daisan_keihin": table})
    return net, tariffs, {"daisan_estimated": estimated}
