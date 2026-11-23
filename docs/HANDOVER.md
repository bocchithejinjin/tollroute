# 引き継ぎ資料（2026-11-23 23:4x、Claude → Codex）

## 1. いまの状態（ひとことで）
横浜〜新宿周辺のデモ道路網で、**高速代の予算内で最速・お得なルートを最大 5 件出す操作確認版が動いており、GitHub に公開済み、自宅 PC から Cloudflare のクイックトンネルで外部公開中**。

| もの | 場所 |
|---|---|
| リポジトリ（公開） | https://github.com/bocchithejinjin/tollroute （既定ブランチ `develop`） |
| 手元の作業フォルダ・今の公開 URL | 所有者の PC の `data/LOCAL_NOTES.md`（git 管理外。公開リポジトリには書かない） |
| 要件定義書 | `docs/requirements.md`（リポジトリ版）と、所有者の Claude Docs 版（非公開） |
| 開いている PR | #1 公開向けの設定 / #2 探索の高速化 / #3 ホスティング調査の追記 / （この資料の PR）。CI を確認して Squash merge する |

## 2. ブランチと PR のルール（CONTRIBUTING.md）
- `main` = リリース（本番デプロイはここから）、`develop` = 開発の本流、`feature/*`・`fix/*` は develop から、`hotfix/*` は main から。
- main / develop は保護済み（直接 push 不可、PR と CI「engine (pure Python)」「django (routes)」の成功が必須、レビュー承認数 0）。
- マージは **Squash and merge** のみ。マージ後ブランチは自動削除。
- コミットの作成者: `じんじん <197459521+bocchithejinjin@users.noreply.github.com>`、末尾に `Co-Authored-By:` を付ける運用。
- `gh` はログイン済み（workflow 権限あり）。パスは `data/LOCAL_NOTES.md`。
- 手元の `archive/pre-publish` ブランチは公開前の履歴（ユーザー名などを含むので**絶対に push しない**）。

## 3. 構成
- `engine/`: 料金エンジン（`tariffs.py`）と多目的ラベル法の探索（`search.py`）。Django 不要。`.\.venv\Scripts\python -m pytest -q engine`。
  - 探索の正しさは総当たり（`engine/brute.py`）との照合テストで守る。テストを弱めない。
- `routes/`: Django アプリ。`demo.py`（デモ道路網。距離は `demo_distances.json`、IC 位置は `demo_ics.json`）、`views.py`（API `/api/search/`）、`travel.py`（一般道の所要時間: OSRM / 概算）、`geocode.py`（jageocoder＋HeartRails 駅名）、`ratelimit.py`（PR #1）。
- 画面: `routes/templates/routes/index.html` ＋ `routes/static/routes/search.{js,css}`（配色は「案内標識の緑」1 案に確定）。
- `.devcontainer/compose.yaml`: `app`（開発。runserver は手で起動: `python manage.py runserver 0.0.0.0:8000`）、`web`（gunicorn、127.0.0.1:8080、常用・公開用）、`db`（PostGIS）、`osrm`（127.0.0.1:5000、関東グラフ `data/osrm/kanto`）。
- `data/`（git 管理外）: `osm/kanto-latest.osm.pbf`、`osrm/kanto/`（3.1GB）、`jageocoder/db`（住所辞書）、`routing/kanto-*/`（OSRM/Valhalla の評価結果）。
- テスト: `docker compose -f .devcontainer/compose.yaml exec -T app pytest -q`（routes 34 件）、engine 244 件（PR #2 後）。

## 4. 決まったこと（要点）
- 一般道の所要時間は手元の OSRM（関東）。混雑補正 ×1.8（`LOCAL_CONGESTION_FACTOR`）。外部 API は使わない（`docs/research-routing-apis.md`）。全国の OSRM はメモリ約 30GB で PC では不可。
- 祝日は内閣府 CSV（`tools/update_holidays.py`）、駅名検索は HeartRails Express（クレジット表示必須）。
- ホスティング: 当面は自宅 PC＋クイックトンネル。次は **Oracle Cloud Always Free（ARM、12GB）＋ docker compose**（所有者が申し込み予定、ホームリージョンは東京か大阪）。手順の概要は `docs/research-hosting.md` 5 章。PaaS なら Fly.io（同 6 章、PR #3）。
- 商用利用は当面想定しない（仲間内で使う・改良する）。デモの区間は横浜駅〜新宿駅（所有者の生活圏を出さないため）。

## 5. 残作業（優先順）
1. **PR の CI を確認して Squash merge**（`gh pr checks N -R bocchithejinjin/tollroute`、`gh pr merge N --squash`）。
2. **要件定義書の更新**（所有者の依頼）: `docs/requirements.md` の 9 章に「やったこと」と「まだやっていないこと（今後の機能拡張）」を書く（6 章を材料に）。所有者の Claude Docs 版にも反映（Claude で可能なら）。
3. **エンジニア仲間への案内文**: Claude がチャットで下書き済み。公開 URL が変わったら差し替える。
4. CI の警告解消: `actions/checkout@v4`・`actions/setup-python@v5` を Node 24 対応版へ。
5. `docs/routing-eval.md` に OSRM/Valhalla の実測値を反映（`data/routing/kanto-*/osrm/build.json`・`valhalla/`）。OSRM 関東: 前処理 14 分・ピーク 6.1GB・グラフ 3.3GB・Docker のメモリ上限 7.6GB。
6. Oracle Cloud へのデプロイ（所有者の申し込み後）: `compose.prod.yaml`（PostGIS を `imresamu/postgis:17-3.5` に、OSRM グラフは VM 上で再前処理も検討）、Docker・cloudflared/Tailscale の導入、データ転送、`main` からデプロイ。
7. 探索: NEXCO の境目判定の局所化（2,000 ノードで 5/9 件が近似モード。`docs/exact-search-design.md` 末尾）。

## 6. 今後の機能拡張の候補（要件定義書の「まだやっていないこと」）
- 料金: 首都圏の起終点を基本とした料金、中央道（高井戸〜八王子）630 円上限、圏央道の短区間（公式と 70〜110 円差 → IC 間料金表で持つ）、首都高の乗り降り方向の制限（用賀→中野長者橋が公式と不一致）、首都高区間の距離は概算（`docs/research-demo-distances.md`）、八王子〜高尾山の ETC 特別料金。
- 割引: 見直し後の深夜割引の施行日（未定、`NightV2.effective_from`）、2027 年度の休日割引除外日（未発表）、平日朝夕割引など未対応の割引。
- 範囲: 全国の道路網と料金データ、車種の切り替え。
- 一般道: 混雑の補正が一律（時間帯・地域別にしたい）、IC の一般道側の出入口の精度。
- 画面: 実機スマホでの確認、検索履歴（F12）、お気に入り地点。
- 運用: 固定 URL（Oracle＋名前付きトンネル or Tailscale）、アクセス制限（Cloudflare Access）、バックアップ。
- 教材化（段階 ③）。

## 7. 公開（クイックトンネル）の動かし方
```powershell
cd <作業フォルダ>
$env:TOLLROUTE_HOST = ".trycloudflare.com"
docker compose -f .devcontainer/compose.yaml up -d web osrm db
& "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --no-autoupdate --url http://127.0.0.1:8080
# 出力の https://xxxx.trycloudflare.com が新しい URL
```
- **注意: 今の cloudflared は Claude のセッションの裏で起動している。Claude のセッションが終わると止まる可能性がある**。止まったら上のコマンドで起動し直し、新しい URL を共有する。
- `web` は PR #1 のコードで起動済み（作業フォルダの内容を使うため、ブランチを切り替えたら `docker compose ... restart web`）。

## 8. 参考資料
`docs/requirements.md`、`docs/algorithm-selection.md`、`docs/exact-search-design.md`、`docs/research-fares.md`、`docs/research-demo-distances.md`、`docs/research-routing-apis.md`、`docs/research-hosting.md`、`docs/routing-eval.md`、`docs/ux-redesign.md`、`docs/remote-access.md`。
