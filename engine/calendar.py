"""休日・割引の適用除外日のカレンダー。

祝日: 内閣府「国民の祝日」CSV（振替休日・国民の休日を含む）を engine/holidays_jp.json に変換したもの。
      出典: 内閣府「国民の祝日について」 https://www8.cao.go.jp/chosei/shukujitsu/gaiyou.html
      （公共データ利用規約 第1.0版 / PDL1.0。CSV を JSON に加工して利用）
      更新は `python tools/update_holidays.py`。
適用除外日: NEXCO 3 社の 2026 年度の発表（docs/research-fares.md 0-3）。2027 年度分は未発表。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

HOLIDAYS_FILE = Path(__file__).with_name("holidays_jp.json")


def _load_holidays(path: Path = HOLIDAYS_FILE) -> tuple[dict[date, str], date]:
    """{日付: 祝日名} と、祝日が分かっている最後の日（データの最終年の 12/31）を返す。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    names = {date.fromisoformat(k): v for k, v in data["holidays"].items()}
    last = max(names)
    return names, date(last.year, 12, 31)


HOLIDAY_NAMES, HOLIDAYS_KNOWN_UNTIL = _load_holidays()
HOLIDAYS = frozenset(HOLIDAY_NAMES)

# NEXCO の休日割引の適用除外日が分かっている最後の日（2026 年度末）
EXCLUDED_KNOWN_UNTIL = date(2027, 3, 31)
# これより後の日は祝日か適用除外日が未登録（両方そろっている日まで）
KNOWN_UNTIL = min(HOLIDAYS_KNOWN_UNTIL, EXCLUDED_KNOWN_UNTIL)

NEXCO_HOLIDAY_EXCLUDED = {
    date(2026, 4, 25), date(2026, 4, 26), date(2026, 4, 29), date(2026, 5, 2), date(2026, 5, 3),
    date(2026, 5, 4), date(2026, 5, 5), date(2026, 5, 6),
    date(2026, 7, 18), date(2026, 7, 19), date(2026, 7, 20),
    date(2026, 8, 8), date(2026, 8, 9), date(2026, 8, 11), date(2026, 8, 15), date(2026, 8, 16),
    date(2026, 9, 19), date(2026, 9, 20), date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23),
    date(2026, 10, 10), date(2026, 10, 11), date(2026, 10, 12),
    date(2026, 11, 21), date(2026, 11, 22), date(2026, 11, 23),
    date(2026, 12, 26), date(2026, 12, 27), date(2027, 1, 1), date(2027, 1, 2), date(2027, 1, 3),
    date(2027, 1, 9), date(2027, 1, 10), date(2027, 1, 11),
    date(2027, 3, 20), date(2027, 3, 21), date(2027, 3, 22),
}


def is_weekend_or_holiday(d: date) -> bool:
    return d.weekday() >= 5 or d in HOLIDAYS


def is_nexco_holiday_discount_day(d: date) -> bool:
    return is_weekend_or_holiday(d) and d not in NEXCO_HOLIDAY_EXCLUDED


def is_aqua_holiday(d: date) -> bool:
    """アクアラインの時間帯別料金の「土日祝」。1/2・1/3 を含む。休日割引の除外日も含む。"""
    return is_weekend_or_holiday(d) or (d.month == 1 and d.day in (2, 3))


def known(d: date) -> bool:
    return d <= KNOWN_UNTIL
