# 引き継ぎメモ（2026-11-23 23:2x 時点、作業を一時中断）

要件定義書はリポジトリ外で管理（必要なら docs/ に Markdown で追加）

## 中断時点で裏で動いていたもの（再開したら結果を確認する）
| 作業 | 担当 | 結果の場所 | 確認すること |
|---|---|---|---|
| 見た目の作り直し（配色 3 案） | Codex | `docs/codex-tasks/06-visual-style.result.md`、`routes/static/routes/*`、`routes/templates/routes/index.html`、`docs/ux-redesign.md` | 差分・テスト・画面で 3 案を確認 → コミット → 利用者に選んでもらう |
| 探索の高速化 | Codex | `docs/codex-tasks/05-search-speedup.result.md`、`engine/search.py` ほか（未コミットの変更あり）、`docs/exact-search-design.md` 末尾の計測 | 差分レビュー、`pytest engine`、総当たり照合、計測値 → コミット |
| 外部 API の調査（所要時間・住所/駅名・祝日 CSV） | サブエージェント | `docs/research-routing-apis.md` | 手間が小さければ外部 API に切り替える（利用者の希望）。API キーは利用者に取得してもらう |
| ルート検索エンジンの比較（関東） | `routing/evaluate.sh` | `data-routing-run.log`、`data/routing/kanto-*/` | OSRM/Valhalla のメモリ・時間・問い合わせ結果を `docs/routing-eval.md` に反映 |

## 残作業（段階 ①）
1. 上の 4 つの取り込み
2. 一般道の所要時間を実際の値に（`routes/travel.py` に実装を追加し、`TRAVEL_TIME_PROVIDER` で切り替え）
3. 区間の距離を実際の値に、横浜〜新宿周辺の区間の料金を公式と照合
4. 祝日を内閣府 CSV から（`engine/calendar.py`）
5. 常用サーバー（compose の `web`）向けの Django 設定: `EXTRA_ALLOWED_HOSTS`、`SECRET_KEY_FILE`、WhiteNoise、`CSRF_TRUSTED_ORIGINS`
6. 要件定義書の更新
7. Tailscale の設定（利用者が PC とスマホに入れてから。手順は `docs/remote-access.md`）

## メモ
- 開発用サーバーはコンテナ内で `python manage.py runserver 0.0.0.0:8000`（再起動したら起動し直す）
- 住所の辞書は `data/jageocoder/db` に導入済み
- Codex への依頼は `docs/codex-tasks/NN-*.md` → `codex exec -s workspace-write -C . -o ...result.md -`
