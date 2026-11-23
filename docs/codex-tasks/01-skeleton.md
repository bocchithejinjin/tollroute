# Codex タスク 01: Dev Container と Django の骨組み

## 背景
`tollroute/` は「高速代の予算内で最速のルート（乗る IC・降りる IC）を出す」Django アプリ。
ローカル専用（インターネットに公開しない）。探索アルゴリズムと料金エンジンは別担当（Claude）が
`explore/` で検討中なので、**このタスクでは触らない**。

## やること
1. `.devcontainer/`（VS Code Dev Container、Docker Compose）
   - `Dockerfile`: `python:3.12-bookworm` ベース。GeoDjango 用に `gdal-bin libgdal-dev libgeos-dev libproj-dev binutils` と `postgresql-client` を入れる。非 root ユーザー `vscode`。
   - `compose.yaml`: サービス `app`（上の Dockerfile、ワークスペースを `/workspaces/tollroute` にマウント、`sleep infinity`）と `db`（`postgis/postgis:17-3.5`、ユーザー/DB/パスワードは `tollroute`/`tollroute`/`tollroute-dev-pass`、名前付きボリューム、healthcheck）。`app` に `DATABASE_URL=postgis://tollroute:tollroute-dev-pass@db:5432/tollroute`。ポート 8000 を転送。
   - `devcontainer.json`: Python 拡張、`postCreateCommand` で `pip install -r requirements.txt`。
   - ルート検索エンジン（OSRM/Valhalla）はまだ入れない。compose にコメントで「後で追加」と書くだけ。
2. `requirements.txt`: Django 5.2.x、psycopg[binary] 3.x、dj-database-url、pytest、pytest-django。バージョンは `~=` で固定。
3. Django プロジェクト `config/`（settings, urls, wsgi, asgi）とアプリ `routes/`。
   - `INSTALLED_APPS` に `django.contrib.gis` と `routes`。DB は `dj_database_url` で `DATABASE_URL` から（`ENGINE` は `django.contrib.gis.db.backends.postgis`）。
   - `LANGUAGE_CODE="ja"`, `TIME_ZONE="Asia/Tokyo"`, `USE_TZ=True`。`SECRET_KEY`・`DEBUG` は環境変数から（開発用の既定値あり）。`ALLOWED_HOSTS` は localhost 系のみ。
   - `routes` に `GET /health/` を返すビュー（`{"status": "ok", "postgis": <PostGIS のバージョン文字列>}` の JSON）と URL。
   - モデルはまだ作らない（料金・IC のモデルは Claude が設計する）。
4. テスト: `pytest.ini`（`DJANGO_SETTINGS_MODULE=config.settings`、`testpaths = routes`）と `routes/tests/test_health.py`（`/health/` が 200 で `status == "ok"`）。
5. `README.md`（日本語、短く）: 起動方法（Reopen in Container → `python manage.py migrate` → `runserver 0.0.0.0:8000` → `pytest`）と、VS Code なしで `docker compose -f .devcontainer/compose.yaml up -d` から動かす方法。
6. `.gitattributes` に `* text=auto eol=lf`。

## 守ること
- `explore/` と `docs/research-fares.md` は変更しない。
- 秘密情報をコミットしない（開発用パスワードは上記の固定値のみ）。
- 新しいファイルの文章は日本語、コードのコメントも日本語で短く。

## 完了の条件
- 可能なら `docker compose -f .devcontainer/compose.yaml up -d --build` → `docker compose ... exec app python manage.py migrate` → `... exec app pytest` が通ることを確認する。サンドボックスの制限で Docker やネットワークが使えなければ、確認できなかったと報告する（その場合も、ファイルは書き終える）。
- 最後に、作成・変更したファイルの一覧と、確認できたこと・できなかったことを短く報告する。git のコミットはしない。
