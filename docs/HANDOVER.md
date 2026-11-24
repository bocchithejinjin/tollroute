# 引き継ぎ資料（2026-11-24、Codex → Claude）

Codex に任せていた作業を、2026-11-24 から Claude が引き継いだ。Codex はもう使わない。作業は Claude と、Claude が呼び出すサブエージェントで行う。

## 1. いまの状態（ひとことで）
横浜〜新宿周辺のデモ道路網で、**高速代の予算内で最速・お得なルートを最大 5 件出す操作確認版**が動いている。API キーがあれば、**所要時間と ETC 料金を Google Routes API で確かめるモード**になる（PR #10）。GitHub に公開済み。外部への公開（クイックトンネル）は、11-24 の時点で止めている。

| もの | 場所 |
|---|---|
| リポジトリ（公開） | https://github.com/bocchithejinjin/tollroute （既定ブランチ `develop`） |
| 手元の作業フォルダ・公開 URL | 所有者の PC の `data/LOCAL_NOTES.md`（git 管理外。公開リポジトリには書かない） |
| 要件定義書 | `docs/requirements.md`（リポジトリ版）と、所有者の Claude Docs 版（非公開） |
| Google モードの仕組み | `docs/google-routes.md` |

## 2. PR の状況（2026-11-24）
- マージ済み: #1〜#8（#7 の NEXCO 境界判定は、総当たりとの照合を乱数で約 1 万件行い、不一致 0 件を確認）
- 開いている（順に積み重ね。下から順にマージする）:
  1. **#9** 首都高の出入口方向の制限（base: develop）
  2. **#10** Google Routes API のモード（base: #9 のブランチ）
  3. **#11** 入力チェックと日時まわりの不具合修正（base: #10 のブランチ）
  - 積み重ねた PR は、下の PR を Squash merge すると、上の PR の base が自動で develop に変わる。差分が二重に見えたら、上のブランチを develop に rebase する。
- 作業中: 中央道（高井戸〜八王子）の 630 円上限（`fix/chuo-630-cap`、worktree `../tollroute-chuo`）。エンジンは 八王子IC→高井戸IC を 1,000 円と計算しているが、公式と Google は 630 円。

## 3. ブランチと PR のルール（CONTRIBUTING.md）
- `main` = リリース、`develop` = 開発の本流、`feature/*`・`fix/*`・`docs/*` は develop から、`hotfix/*` は main から。
- main / develop は保護済み（PR と CI「engine (pure Python)」「django (routes)」の成功が必須）。マージは **Squash and merge** のみで、**所有者が行う**（Claude の `gh pr merge` は権限で止められる）。
- コミットの作成者: `じんじん <197459521+bocchithejinjin@users.noreply.github.com>`、末尾に `Co-Authored-By:`。
- 手元の `archive/pre-publish` ブランチは公開前の履歴（**絶対に push しない**）。
- worktree `tollroute-handover`・`tollroute-nexco` は Codex のユーザー（CodexSandboxOffline）が作ったもので、git の操作に `-c safe.directory=*` が要る。不要になったら `git worktree remove` で片付ける。

## 4. 構成
- `engine/`: 料金エンジン（`tariffs.py`）と多目的ラベル法の探索（`search.py`）。Django 不要。`.\.venv\Scripts\python -m pytest -q engine`（247 件）。
  - 探索の正しさは総当たり（`engine/brute.py`）との照合テストで守る。**テストを弱めない**。
- `routes/`: Django アプリ。`demo.py`（デモ道路網）、`views.py`（API `/api/search/`）、`google_routes.py`（Google Routes API）、`travel.py`（一般道の所要時間: OSRM / 概算）、`geocode.py`、`ratelimit.py`。
- 画面: `routes/templates/routes/index.html` ＋ `routes/static/routes/search.{js,css}`。
- `.devcontainer/compose.yaml`: `app`（開発）、`web`（gunicorn、127.0.0.1:8080、常用・公開用）、`db`（PostGIS）、`osrm`（127.0.0.1:5000）。
- テスト（routes は PostGIS が要る）: `docker compose -f .devcontainer/compose.yaml run --rm -T app sh -c "pip install -q -r requirements.txt; python -m pytest -q"`。**`app` のイメージが古く whitenoise が入っていない**ので、`pip install` を先に行う（またはイメージを作り直す）。

## 5. Google Routes API のキー
- `data/google_routes_demo_key` に、**Windows の DPAPI で暗号化して**保存されている（PowerShell の `ConvertFrom-SecureString` の形式。所有者のユーザーで復号できる）。コンテナからは読めないので、起動時に復号して環境変数で渡す:
  ```powershell
  $raw = (Get-Content data\google_routes_demo_key -Raw).Trim()
  $env:GOOGLE_ROUTES_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR((ConvertTo-SecureString $raw)))
  docker compose -f .devcontainer/compose.yaml up -d web
  Remove-Item Env:GOOGLE_ROUTES_API_KEY
  ```
  （PR #10 の `compose.yaml` が、環境変数 `GOOGLE_ROUTES_API_KEY` を `web` に渡す）
- Google Cloud 側に 1 日のリクエスト上限がある（11-24 の確認中に到達）。1 検索で最大 14 リクエスト。アプリ側でも 1 日 30 検索に制限している。

## 6. 残作業（優先順）
1. PR #9 → #10 → #11 の順にマージ（所有者）。
2. 中央道の 630 円上限（作業中）を PR にする。
3. Google の 1 日の上限が戻ったら、町田→新宿など、まだ実際の API で確かめていない区間を確認する。
4. 公開デモの再開（`web` を新しいコードで再起動し、cloudflared を起動。URL が変わる）。Google モードで公開すると、ほかの人の検索も API の利用料金と上限に数えられる点に注意。
5. Claude Docs 版の要件定義書に、9 章の更新を反映する。
6. Oracle Cloud へのデプロイ（所有者の申し込み後）。
7. 今後の機能拡張は `docs/requirements.md` 9 章「まだやっていないこと」。

## 7. 公開（クイックトンネル）の動かし方
```powershell
cd <作業フォルダ>
$env:TOLLROUTE_HOST = ".trycloudflare.com"
docker compose -f .devcontainer/compose.yaml up -d web osrm db
& "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --no-autoupdate --url http://127.0.0.1:8080
# 出力の https://xxxx.trycloudflare.com が新しい URL
```
- cloudflared は、起動したセッション（Claude など）が終わると止まることがある。止まったら起動し直し、新しい URL を共有する。
- `web` は作業フォルダの内容を使う。ブランチを切り替えたら `docker compose ... restart web`。

## 8. 参考資料
`docs/requirements.md`、`docs/google-routes.md`、`docs/algorithm-selection.md`、`docs/exact-search-design.md`、`docs/research-fares.md`、`docs/research-demo-distances.md`、`docs/research-routing-apis.md`、`docs/research-hosting.md`、`docs/routing-eval.md`、`docs/ux-redesign.md`、`docs/remote-access.md`。
