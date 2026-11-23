Dev Container と Django 5.2／PostGIS の骨組みを作成しました。ポート 8000 は `127.0.0.1` に割り当て、`GET /health/` は PostGIS のバージョンを JSON で返します。

**確認結果**

- `docker compose -f .devcontainer/compose.yaml up -d --build` と `python manage.py migrate` は成功しました。
- `pytest` は **1 件成功**し、`/health/` の HTTP 200、`status: ok`、PostGIS のバージョン文字列を確認しました。
- コンテナ内の `pip install -r requirements.txt` は成功しました。VS Code の「Reopen in Container」操作は未確認です。
- マイグレーション時に、Bookworm の GDAL 3.6.2 に対する Django の警告 `gis.W001` が出ました。

**作成ファイル（17 件）**

- `.devcontainer/` — `Dockerfile`、`compose.yaml`、`devcontainer.json`
- `config/` — `__init__.py`、`settings.py`、`urls.py`、`wsgi.py`、`asgi.py`
- `routes/` — `__init__.py`、`urls.py`、`views.py`、`tests/test_health.py`
- ルート — `manage.py`、`requirements.txt`、`pytest.ini`、`.gitattributes`、[README.md](/README.md)

Git コミットは作成していません。