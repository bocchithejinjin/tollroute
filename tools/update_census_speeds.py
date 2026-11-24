"""道路交通センサスの旅行速度から、一般道の地域別の平均速度の表（routes/census_speeds.json）を作る。

出典: 国土交通省「令和3年度 全国道路・街路交通情勢調査 一般交通量調査 集計表」
      5. 旅行速度整理表（都道府県別道路種別別） https://www.mlit.go.jp/road/census/r3/
使い方:
    curl -o syuukei05.csv https://www.mlit.go.jp/road/census/r3/data/csv/syuukei05.csv
    python tools/update_census_speeds.py syuukei05.csv
「一般道路計」の行の、混雑時（朝夕）と非混雑時（昼間）の旅行速度の「合計」の列を使う。
"""
import csv
import io
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "routes" / "census_speeds.json"
SOURCE = ("「令和3年度 全国道路・街路交通情勢調査 一般交通量調査 集計表」5. 旅行速度整理表（都道府県別道路種別別）"
          "（国土交通省） https://www.mlit.go.jp/road/census/r3/ の一般道路計の旅行速度を加工して作成（PDL1.0）")


def number(text):
    try:
        return float(text)
    except ValueError:
        return None


def main(path):
    rows = list(csv.reader(io.StringIO(Path(path).read_bytes().decode("cp932"))))
    header = rows[0]
    peak = header.index(next(h for h in header if h.startswith("朝夕旅行速度") and h.endswith("合計")))
    offpeak = header.index(next(h for h in header if h.startswith("昼間旅行速度") and h.endswith("合計")))
    areas, area = {}, None
    for row in rows[1:]:
        if row[0]:
            area = row[0]
        if area and row[1] == "一般道路計":
            p, o = number(row[peak]), number(row[offpeak])
            if p and o:
                areas[area] = {"peak": p, "offpeak": o}
    OUT.write_text(json.dumps({"_source": SOURCE, "areas": areas}, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    print(f"{len(areas)} 地域 → {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
