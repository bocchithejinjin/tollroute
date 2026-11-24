"""jageocoder の逆引き用の索引（rtree.dat・rtree.idx）を作る。一般道の所要時間の見積もり（routes/speed.py）に使う。

    python tools/build_reverse_index.py   # 辞書は JAGEOCODER_DB2_DIR、なければ data/jageocoder/db
数分かかる（一度作れば残る）。
"""
import os
import sys
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "jageocoder" / "db"


def main():
    import jageocoder

    db = Path(os.environ.get("JAGEOCODER_DB2_DIR", DEFAULT_DB))
    if not db.exists():
        sys.exit(f"住所の辞書が見つかりません（{db}）")
    jageocoder.init(db_dir=str(db))
    found = jageocoder.reverse(139.7006, 35.6896, level=3)  # 初回の逆引きで索引が作られる
    print("索引あり:", (db / "rtree.dat").exists(), "/ 試しに逆引き:", found[0]["candidate"]["fullname"] if found else None)


if __name__ == "__main__":
    main()
