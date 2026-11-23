"""探索アルゴリズム比較用の最小モデル。

高速道路網を「ノード（IC・JCT）」と「区間（有向辺）」のグラフで表す。
料金は運営会社の「料金グループ」ごとに、連続して走った区間（ラン）単位で計算する。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Node:
    id: str
    x: float  # km
    y: float  # km
    can_enter: bool = True
    can_exit: bool = True


@dataclass(frozen=True)
class Edge:
    u: str
    v: str
    operator: str  # 料金グループ（例: "nexco", "metro", "aqua"）
    dist_km: float
    time_min: float
    fare_class: str = "normal"  # "normal" | "urban"（大都市近郊）
    flat_yen: int = 0  # 固定料金の区間（橋・アクアラインなど）


@dataclass
class Network:
    nodes: dict[str, Node] = field(default_factory=dict)
    out: dict[str, list[Edge]] = field(default_factory=dict)

    def add_node(self, n: Node) -> None:
        self.nodes[n.id] = n
        self.out.setdefault(n.id, [])

    def add_edge(self, e: Edge, both: bool = True) -> None:
        self.out[e.u].append(e)
        if both:
            self.out[e.v].append(
                Edge(e.v, e.u, e.operator, e.dist_km, e.time_min, e.fare_class, e.flat_yen)
            )

    def edges(self):
        for es in self.out.values():
            yield from es


@dataclass(frozen=True)
class Query:
    ox: float
    oy: float
    dx: float
    dy: float
    depart: datetime
    budget: int | None = None


LOCAL_SPEED_KMH = 30.0
LOCAL_DETOUR = 1.3


def local_minutes(ax: float, ay: float, bx: float, by: float) -> float:
    """一般道の所要時間（分）。本番ではルート検索エンジンに置き換える。"""
    return math.hypot(ax - bx, ay - by) * LOCAL_DETOUR / LOCAL_SPEED_KMH * 60.0


def at(depart: datetime, minutes: float) -> datetime:
    return depart + timedelta(minutes=minutes)
