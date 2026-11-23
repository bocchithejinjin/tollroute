"""高速道路網のモデル。Django に依存しない。

- Node: IC・JCT・本線料金所など。乗り降りできるかを持つ。
- Edge: 有向の区間。どの料金プール（pool）に属するか、料金の距離、所要時間、区分、割引の対象かを持つ。
  料金プール = 1 回の利用としてまとめて料金を計算する道路の集まり（例: NEXCO の高速自動車国道、首都高）。
- 料金所（本線料金所）を通るたびに料金が決まる道路は、その区間の Edge に tollgate を付ける。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Node:
    id: str
    name: str
    lat: float
    lon: float
    can_enter: bool = True
    can_exit: bool = True
    # None は方向制限なし。空の組は、対応するランプにデモ網内から接続できない場合。
    entry_towards: tuple[str, ...] | None = None
    exit_from: tuple[str, ...] | None = None

    def permits_entry_towards(self, neighbor: str) -> bool:
        return self.entry_towards is None or neighbor in self.entry_towards

    def permits_exit_from(self, neighbor: str) -> bool:
        return self.exit_from is None or neighbor in self.exit_from


@dataclass(frozen=True)
class Edge:
    u: str
    v: str
    pool: str  # 料金プールの ID（tariffs の Pool.id）
    road: str  # 路線名（表示・割引の対象判定に使う）
    dist_km: float  # 料金の距離
    time_min: float  # 所要時間（渋滞なし）
    fare_class: str = "normal"  # "normal" | "urban" | "strait" など、単価の区分
    holiday_ok: bool = True  # 休日割引の対象区間か
    night_ok: bool = True  # 深夜割引の対象区間か
    tollgate: str | None = None  # この区間に本線料金所があればその ID
    direction: str | None = None  # "up" | "down"（料金所の料金が向きで変わるとき）


@dataclass
class Network:
    nodes: dict[str, Node] = field(default_factory=dict)
    out: dict[str, list[Edge]] = field(default_factory=dict)

    def add_node(self, n: Node) -> None:
        self.nodes[n.id] = n
        self.out.setdefault(n.id, [])

    def add_edge(self, e: Edge) -> None:
        if e.u not in self.nodes or e.v not in self.nodes:
            raise KeyError(f"unknown node in edge {e.u}->{e.v}")
        self.out[e.u].append(e)

    def edges(self):
        for es in self.out.values():
            yield from es
