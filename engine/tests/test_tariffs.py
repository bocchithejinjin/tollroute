"""料金と割引の規則のテスト。数値の根拠は docs/research-fares.md。"""
from datetime import datetime

import pytest

from engine.model import Edge, Network, Node
from engine.tariffs import NightV2, Step, aqua_gate, default_tariffs, round10
from engine.brute import evaluate


def test_round10():
    assert round10(814.4) == 810
    assert round10(815.0) == 820
    assert round10(879.4) == 880
    assert round10(10_456.7) == 10_400  # 1 万円超は 100 円未満切り捨て
    assert round10(10_000.0) == 10_000
    assert round10(10_000.4) == 10_000
    assert round10(9_995.0) == 10_000


def chain(pool, kms, cls="normal", **kw):
    """一直線の道路網 n0 - n1 - ... を作る（1 区間 = kms の各要素 km、時速 80km）。"""
    net = Network()
    for i in range(len(kms) + 1):
        net.add_node(Node(f"n{i}", f"n{i}", 0, 0))
    for i, km in enumerate(kms):
        net.add_edge(Edge(f"n{i}", f"n{i+1}", pool, f"{pool}-road", km, km / 80 * 60, cls, **kw))
    return net


def fare(net, depart, tariffs=None):
    tariffs = tariffs or default_tariffs()
    edges = [net.out[f"n{i}"][0] for i in range(len(net.nodes) - 1)]
    last = edges[-1].v
    plan = evaluate(net, tariffs, depart, "n0", edges, {"n0": 0.0}, {last: 0.0})
    return plan.runs


WED_NOON = datetime(2026, 11, 25, 12, 0)
SAT_NOON = datetime(2026, 11, 28, 12, 0)


class TestShutoko:
    def test_after_revision_20km(self):
        assert fare(chain("shutoko", [20]), WED_NOON)[0].fare == 880

    def test_before_revision_20km(self):
        assert fare(chain("shutoko", [20]), datetime(2026, 9, 30, 12))[0].fare == 810

    def test_cap_and_floor(self):
        assert fare(chain("shutoko", [70]), WED_NOON)[0].fare == 2130
        assert fare(chain("shutoko", [1]), WED_NOON)[0].fare == 300

    def test_night_by_entry_time_only(self):
        assert fare(chain("shutoko", [20]), datetime(2026, 11, 25, 3, 50))[0].fare == round10(880 * 0.8)
        # 0 時前に入れば、0 時以降に出ても対象外
        assert fare(chain("shutoko", [20, 20]), datetime(2026, 11, 25, 23, 50))[0].discount is None

    def test_uses_shortest_distance_not_driven(self):
        net = Network()
        for n in "abc":
            net.add_node(Node(n, n, 0, 0))
        net.add_edge(Edge("a", "b", "shutoko", "x", 10, 10))
        net.add_edge(Edge("a", "c", "shutoko", "x", 8, 6))
        net.add_edge(Edge("c", "b", "shutoko", "x", 8, 6))
        t = default_tariffs()
        detour = [net.out["a"][1], net.out["c"][0]]
        p = evaluate(net, t, WED_NOON, "a", detour, {"a": 0}, {"b": 0})
        assert p.fare == round10((32.472 * 10 + 150) * 1.1)


class TestNexco:
    def test_basic_formula(self):
        # (24.6 × 50 + 150) × 1.1 = 1518 → 1520
        assert fare(chain("nexco", [50]), WED_NOON)[0].fare == 1520

    def test_long_distance_taper(self):
        # 250km: 100 + 100×0.75 + 50×0.7 = 210 換算km → (24.6×210+150)×1.1 = 5847.6 → 5850
        assert fare(chain("nexco", [250]), WED_NOON)[0].fare == 5850

    def test_holiday_discount_rural_only(self):
        assert fare(chain("nexco", [50]), SAT_NOON)[0].fare == round10(1518 - 24.6 * 50 * 1.1 * 0.3)
        assert fare(chain("nexco", [50], "urban", holiday_ok=False), SAT_NOON)[0].discount is None

    def test_holiday_excluded_day(self):
        assert fare(chain("nexco", [50]), datetime(2026, 11, 23, 12))[0].discount is None  # 3 連休は除外

    def test_holiday_by_exit_date(self):
        # 金曜 23:30 に入り、土曜 0 時以降に出る → 休日割引の対象（深夜割引とも重なるが大きいほう 1 つ）
        runs = fare(chain("nexco", [60]), datetime(2026, 11, 27, 23, 30))
        # (24.6×60+150)×1.1 = 1788.6。深夜割引はターミナルチャージ込みの 3 割引で、休日割引より大きい
        assert runs[0].discount == "深夜割引"
        assert runs[0].fare == round10(1788.6 * 0.7)

    @pytest.mark.parametrize("depart,km,expected", [
        (datetime(2026, 11, 25, 23, 0), 40, None),        # 0 時前に入って 0 時前に出る
        (datetime(2026, 11, 25, 23, 40), 40, "深夜割引"),  # 0 時をまたぐ
        (datetime(2026, 11, 26, 3, 50), 40, "深夜割引"),   # 4 時前に入って 4 時以降に出る
        (datetime(2026, 11, 26, 4, 0), 40, None),          # 4 時以降に入る
    ])
    def test_night_v1(self, depart, km, expected):
        assert fare(chain("nexco", [km]), depart)[0].discount == expected

    def test_urban_night_bigger_than_holiday(self):
        # 大都市近郊区間だけなら、休日割引はないが深夜割引はある
        runs = fare(chain("nexco", [40], "urban", holiday_ok=False), datetime(2026, 11, 28, 1, 0))
        assert runs[0].discount == "深夜割引"

    def test_night_v2_only_night_part(self):
        t = default_tariffs()
        t.pools["nexco"].night_v2 = NightV2(effective_from=datetime(2026, 4, 1))
        # 21:00 に入り 160km（2 時間）。22 時以降の 1 時間分（80km）だけが 3 割引
        runs = fare(chain("nexco", [80, 80]), datetime(2026, 11, 25, 21, 0), t)
        tapered = 100 + 60 * 0.75
        base_raw = (24.6 * tapered + 150) * 1.1
        assert runs[0].fare == round10(base_raw - base_raw * 80 / 160 * 0.3)


class TestTollgates:
    def test_yokohama_shindo_flat(self):
        assert fare(chain("yokohama_shindo", [5], tollgate="g"), WED_NOON)[0].fare == 320

    @pytest.mark.parametrize("t,direction,expected", [
        (datetime(2026, 11, 25, 14), "up", 800),    # 平日
        (datetime(2026, 11, 28, 14), "up", 1600),   # 土曜 13〜19 時 上り
        (datetime(2026, 11, 28, 14), "down", 800),
        (datetime(2026, 11, 28, 6), "down", 1000),  # 土曜 5〜7 時 下り
        (datetime(2026, 11, 28, 0, 30), "up", 400), # 土曜の深夜は時間帯別料金
        (datetime(2026, 11, 25, 2), "up", 800),     # 平日は深夜も 800 円（Codex r01 の指摘）
        (datetime(2026, 11, 28, 12, 59), "up", 800),  # 境目の直前
        (datetime(2026, 11, 28, 13, 0), "up", 1600),  # 境目ちょうど
        (datetime(2026, 11, 28, 19, 0), "up", 800),
        (datetime(2027, 1, 2, 14), "up", 1600),     # 1/2 は土日祝扱い
        (datetime(2027, 4, 3, 14), "up", 800),      # 実施期間の後
        (datetime(2025, 3, 29, 14), "up", 800),     # 実施期間の前
    ])
    def test_aqua(self, t, direction, expected):
        assert aqua_gate("kisarazu", direction, t)[1] == expected


class TestReviewFixes:
    """Codex レビュー r01 の指摘を固定したケース。"""

    def test_night_not_applied_to_ineligible_only(self):
        assert fare(chain("nexco", [10], night_ok=False), datetime(2026, 11, 25, 1, 0))[0].discount is None

    def test_shutoko_uses_shorter_of_both_directions(self):
        net = Network()
        for n in "ab":
            net.add_node(Node(n, n, 0, 0))
        net.add_edge(Edge("a", "b", "shutoko", "x", 20, 20))
        net.add_edge(Edge("b", "a", "shutoko", "x", 10, 10))
        p = evaluate(net, default_tariffs(), WED_NOON, "a", [net.out["a"][0]], {"a": 0}, {"b": 0})
        assert p.fare == round10((32.472 * 10 + 150) * 1.1)

    @pytest.mark.parametrize("depart,expected", [
        (datetime(2026, 11, 27, 22, 0), "休日割引"),  # 金曜に入って土曜に出る（深夜をまたがない）
        (datetime(2026, 11, 29, 22, 0), "休日割引"),  # 日曜に入って月曜に出る
        (datetime(2026, 11, 20, 22, 0), None),        # 金曜に入って 3 連休の初日（除外日）に出る
    ])
    def test_holiday_by_entry_or_exit_without_night(self, depart, expected):
        # 22:00 に入って 100km（75 分）→ 23:15 に出る、は同じ日。日付をまたがせるため 23:30 発に調整する
        d = depart.replace(hour=23, minute=30)
        # 0 時をまたいで 0:00〜4:00 にかかると深夜割引も付くので、深夜割引の対象外の区間で確かめる
        runs = fare(chain("nexco", [60], night_ok=False), d)
        assert runs[0].discount == expected

    def test_night_exact_boundaries(self):
        # 0:00 ちょうどに出る → 0 時をまたいだので対象。4:00 ちょうどに入る → 対象外
        assert fare(chain("nexco", [40]), datetime(2026, 11, 25, 23, 30))[0].discount == "深夜割引"
        assert fare(chain("nexco", [40]), datetime(2026, 11, 26, 4, 0))[0].discount is None

    def test_monotone_validation_rejects_strait_in_same_pool(self):
        from engine.tariffs import NexcoPool
        NexcoPool().validate()
        with pytest.raises(ValueError):
            NexcoPool(rates={"normal": 24.6, "strait": 108.1}).validate()
