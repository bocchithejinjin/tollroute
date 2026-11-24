"""横浜駅→新宿駅で Google Routes API を 1 回試す（キーと料金の取得の確認用）。

キーは環境変数 GOOGLE_ROUTES_API_KEY、なければ GOOGLE_ROUTES_API_KEY_FILE のファイルから読む。
    python tools/probe_google_routes.py --budget 1000
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from routes import google_routes  # noqa: E402  （Django の設定は不要）

YOKOHAMA, SHINJUKU = (35.4657, 139.6223), (35.6896, 139.7006)


def api_key():
    key = os.environ.get("GOOGLE_ROUTES_API_KEY", "").strip()
    path = os.environ.get("GOOGLE_ROUTES_API_KEY_FILE", "").strip()
    if not key and path and Path(path).is_file():
        key = Path(path).read_text(encoding="utf-8").strip()
    return key


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--budget", type=int, default=1000)
    parser.add_argument("--departure", help="未来の出発時刻（RFC 3339）。省略時は現在時刻")
    parser.add_argument("--show-request", action="store_true", help="リクエスト本文だけ表示する（API は呼ばない）")
    args = parser.parse_args()
    if args.show_request:
        print(json.dumps(google_routes.make_request(YOKOHAMA, SHINJUKU, args.departure), indent=2, ensure_ascii=False))
        return
    key = api_key()
    if not key:
        parser.error("GOOGLE_ROUTES_API_KEY か GOOGLE_ROUTES_API_KEY_FILE を設定してください")
    try:
        candidates, free_failed = google_routes.search_candidates(key, YOKOHAMA, SHINJUKU, args.departure)
    except google_routes.GoogleRoutesError as exc:
        raise SystemExit(f"Compute Routes を呼び出せませんでした: {exc}") from None
    for c in candidates:
        fare = f"{c.fare:g} 円" if c.fare is not None else "料金不明"
        print(f"{c.description} | {c.distance / 1000:.1f} km | {float(c.seconds) / 60:.1f} 分 | {fare}")
    if free_failed:
        print("（有料道路を避ける検索は失敗しました）")
    within = [c for c in candidates if c.fare is not None and c.fare <= args.budget]
    if within:
        best = within[0]
        print(f"予算内の最速は {best.description}（{float(best.seconds) / 60:.1f} 分、{best.fare:g} 円）")
    else:
        print("料金を確認できた予算内の候補はありません")


if __name__ == "__main__":
    main()
