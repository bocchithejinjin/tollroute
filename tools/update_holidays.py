"""内閣府「国民の祝日」CSV を取得し、engine/holidays_jp.json に書き出す。

使い方（リポジトリのルートで）:
    python tools/update_holidays.py              # 内閣府から取得
    python tools/update_holidays.py --csv FILE   # 手元の CSV（CP932）から作る

出典: 内閣府「国民の祝日について」 https://www8.cao.go.jp/chosei/shukujitsu/gaiyou.html
利用条件: 公共データ利用規約（第1.0版, PDL1.0）。出典の記載が必要。
このスクリプトは CSV を JSON に形式変換している（日付を ISO 形式にしている）。
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import urllib.request
from datetime import date, datetime
from pathlib import Path

URL = "https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv"
OUT = Path(__file__).resolve().parents[1] / "engine" / "holidays_jp.json"
USER_AGENT = "tollroute/0.1"


def fetch(url: str = URL) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read()


def parse(raw: bytes) -> dict[str, str]:
    """CSV（CP932、`2027/11/23,勤労感謝の日` 形式）を {ISO 日付: 名称} にする。"""
    text = raw.decode("cp932")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or not rows[0] or "月日" not in rows[0][0]:
        raise ValueError(f"想定していないヘッダです: {rows[:1]}")
    out: dict[str, str] = {}
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        d = datetime.strptime(row[0].strip(), "%Y/%m/%d").date()
        out[d.isoformat()] = row[1].strip()
    if not out:
        raise ValueError("祝日が 1 件もありません")
    return dict(sorted(out.items()))


def build(holidays: dict[str, str], fetched: date) -> dict:
    return {
        "source": "内閣府「国民の祝日について」",
        "source_url": URL,
        "source_page": "https://www8.cao.go.jp/chosei/shukujitsu/gaiyou.html",
        "license": "公共データ利用規約（第1.0版）（PDL1.0） https://www.digital.go.jp/resources/open_data/public_data_license_v1.0",
        "attribution": "出典: 内閣府「国民の祝日について」（https://www8.cao.go.jp/chosei/shukujitsu/gaiyou.html）の CSV を加工して作成",
        "modified": "CSV（CP932）を JSON に変換し、日付を ISO 8601 形式にした",
        "fetched": fetched.isoformat(),
        "first": next(iter(holidays)),
        "last": next(reversed(holidays)),
        "holidays": holidays,
    }


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--csv", type=Path, help="手元の CSV ファイル（CP932）")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    raw = args.csv.read_bytes() if args.csv else fetch()
    holidays = parse(raw)
    data = build(holidays, date.today())
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{args.out}: {len(holidays)} 日（{data['first']} 〜 {data['last']}）")


if __name__ == "__main__":
    main()
