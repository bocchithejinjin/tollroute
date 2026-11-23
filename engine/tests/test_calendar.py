"""祝日（内閣府 CSV 由来）と NEXCO の適用除外日の判定。"""
import json
from datetime import date, timedelta

from engine import calendar as cal

# 以前 calendar.py に手書きしていた祝日。CSV 由来のデータにすべて含まれているはず。
HAND_WRITTEN = {
    date(2026, 1, 1), date(2026, 1, 12), date(2026, 2, 11), date(2026, 2, 23), date(2026, 3, 20),
    date(2026, 4, 29), date(2026, 5, 3), date(2026, 5, 4), date(2026, 5, 5), date(2026, 5, 6),
    date(2026, 7, 20), date(2026, 8, 11), date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23),
    date(2026, 10, 12), date(2026, 11, 3), date(2026, 11, 23),
    date(2027, 1, 1), date(2027, 1, 11), date(2027, 2, 11), date(2027, 2, 23), date(2027, 3, 21),
    date(2027, 3, 22),
}


def test_data_file_has_source_and_license():
    data = json.loads(cal.HOLIDAYS_FILE.read_text(encoding="utf-8"))
    assert data["source_url"] == "https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv"
    assert "PDL1.0" in data["license"]
    assert data["fetched"]


def test_hand_written_holidays_are_in_csv():
    assert HAND_WRITTEN <= cal.HOLIDAYS
    # 2026-01 〜 2027-03 の祝日は手書きのものと完全に一致する
    window = {d for d in cal.HOLIDAYS if date(2026, 1, 1) <= d <= date(2027, 3, 31)}
    assert window == HAND_WRITTEN


def test_special_holidays():
    assert cal.HOLIDAY_NAMES[date(2026, 9, 22)] == "休日"  # 国民の休日（敬老の日と秋分の日の間）
    assert cal.HOLIDAY_NAMES[date(2027, 3, 22)] == "休日"  # 振替休日（春分の日が日曜）
    assert cal.HOLIDAY_NAMES[date(2026, 5, 6)] == "休日"  # 振替休日（憲法記念日が日曜）
    assert cal.HOLIDAY_NAMES[date(2026, 11, 23)] == "勤労感謝の日"
    assert cal.is_weekend_or_holiday(date(2026, 9, 22))
    assert cal.is_weekend_or_holiday(date(2027, 3, 22))


def test_weekend_and_weekday():
    assert cal.is_weekend_or_holiday(date(2026, 11, 28))  # 土曜
    assert cal.is_weekend_or_holiday(date(2026, 11, 29))  # 日曜
    assert not cal.is_weekend_or_holiday(date(2026, 11, 25))  # 水曜
    assert not cal.is_weekend_or_holiday(date(2026, 11, 24))  # 祝日の翌日（火曜）


def test_nexco_excluded_days():
    # 祝日だが休日割引の適用除外日
    assert not cal.is_nexco_holiday_discount_day(date(2026, 11, 23))
    assert not cal.is_nexco_holiday_discount_day(date(2027, 3, 22))
    # 土日だが適用除外日
    assert not cal.is_nexco_holiday_discount_day(date(2026, 11, 21))
    # 除外されていない土日・祝日
    assert cal.is_nexco_holiday_discount_day(date(2026, 11, 28))
    assert cal.is_nexco_holiday_discount_day(date(2026, 11, 3))
    # 平日
    assert not cal.is_nexco_holiday_discount_day(date(2026, 11, 25))


def test_aqua_holiday_includes_jan_2_3():
    assert cal.is_aqua_holiday(date(2026, 11, 23))
    assert cal.is_aqua_holiday(date(2027, 1, 4)) is False  # 月曜・平日
    assert cal.is_aqua_holiday(date(2026, 1, 2))


def test_known_until():
    assert cal.HOLIDAYS_KNOWN_UNTIL == date(max(cal.HOLIDAYS).year, 12, 31)
    assert cal.KNOWN_UNTIL == min(cal.HOLIDAYS_KNOWN_UNTIL, cal.EXCLUDED_KNOWN_UNTIL)
    assert cal.known(date(2027, 3, 31))
    assert not cal.known(cal.KNOWN_UNTIL + timedelta(days=1))


def test_load_holidays_from_other_file(tmp_path):
    p = tmp_path / "h.json"
    p.write_text(json.dumps({"holidays": {"2030-01-01": "元日", "2030-05-03": "憲法記念日"}}), encoding="utf-8")
    names, until = cal._load_holidays(p)
    assert names == {date(2030, 1, 1): "元日", date(2030, 5, 3): "憲法記念日"}
    assert until == date(2030, 12, 31)
