# tollroute

> **English summary:** tollroute suggests the fastest (and best-value) driving routes in Japan that fit within a highway-toll budget you set. It models ETC tolls including holiday / late-night discounts and time-of-day pricing, shows up to 5 alternatives with a "value" score (yen saved per minute), and sends the chosen route's waypoints to Google Maps. Status: early prototype covering a small demo network around Yokohama – Shinjuku (Tokyo). Fares are estimates, not official. Code is MIT-licensed; some bundled data has its own license (see [NOTICE.md](NOTICE.md)). Docs are in Japanese.

高速代の予算を決めると、その範囲で**いちばん早く着くルート**と**お得なルート**を提案する Web アプリです。

## できること

- 高速代の予算内で最速のルートと、払う価値が高い（1 分短縮あたりの金額が小さい）ルートを提案
- ETC 料金を自前の料金エンジンで計算（NEXCO・首都高・アクアラインなど）
  - 休日割引・深夜割引、首都高の時間帯別料金、出発時刻による料金の違いを反映
- 候補は最大 5 ルート。「最速」「いちばんお得」などのラベルとお得度（円/分）を表示
- 出発地・目的地は住所（jageocoder、外部に送らない）または駅名（HeartRails Express）で入力
- 選んだルートの経由地を Google マップで開く

## 現在の状況

**操作確認版**です。実用には次の制約があります。

- 道路網は**横浜〜新宿周辺のデモ道路網**だけ（`routes/demo.py`、IC の座標は `routes/demo_ics.json`）
- 高速道路の**区間距離は概算**（公式の距離・料金との照合を進めています）
- 一般道の所要時間は**関東の OSRM**（有料道路を除外）で求め、混雑を見込んで係数を掛けています。OSRM が動いていないときは直線距離からの概算に切り替わります

## 構成

| 部分 | 内容 |
|---|---|
| `engine/` | 純 Python の料金エンジンと探索（Django に依存しない）。料金表・割引（`tariffs.py`）、祝日（`calendar.py`、`holidays_jp.json`）、予算内のパレート最適ルートを求める多目的ラベル法（`search.py`）、検証用の総当たり（`brute.py`） |
| `routes/` | Django アプリ。画面（`templates/`、`static/`）、検索 API（`views.py`）、住所・駅名の変換（`geocode.py`）、一般道の所要時間（`travel.py`）、デモ道路網（`demo.py`） |
| `config/` | Django の設定 |
| OSRM | 一般道の所要時間（関東のグラフ、`exclude=toll`）。`.devcontainer/compose.yaml` の `osrm` サービス |
| jageocoder | 住所 → 座標。手元の辞書だけで変換し、住所を外部に送らない |
| HeartRails Express | 駅名 → 座標（駅名だけを送る） |
| PostGIS | データベース（現在はモデルがなく、ヘルスチェックで接続を確認するだけ） |
| `routing/` | OSRM / Valhalla の評価スクリプト（関東グラフの作成にも使う） |
| `tools/` | 祝日データの更新スクリプト |
| `explore/` | 探索の規模・速度の実験用スクリプト |

## クイックスタート

必要なもの: Docker（Docker Desktop など）。VS Code の Dev Containers 拡張があると便利です。

### VS Code（Dev Container）で起動

Docker を起動し、VS Code の Dev Containers 拡張で「Reopen in Container」を実行します。コンテナ内のターミナルで次を実行します。

```sh
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

### Docker Compose で起動

リポジトリのルートで次を実行します。Python の依存パッケージはイメージのビルド時にインストールされます。

```sh
docker compose -f .devcontainer/compose.yaml up -d --build
docker compose -f .devcontainer/compose.yaml exec app python manage.py migrate
docker compose -f .devcontainer/compose.yaml exec app python manage.py runserver 0.0.0.0:8000
```

- 画面: http://localhost:8000/
- [ヘルスチェック](http://localhost:8000/health/): 接続先の PostGIS のバージョンが JSON で表示されます

OSRM のグラフや住所の辞書がなくても画面は動きます（一般道の時間は概算になり、住所の入力は使えません。駅名とデモ地点は使えます）。

主な環境変数:

| 変数 | 既定値 | 説明 |
|---|---|---|
| `DATABASE_URL` | （compose で設定） | PostGIS の接続先 |
| `TRAVEL_TIME_PROVIDER` | `osrm` | `osrm` または `estimate`（直線距離からの概算、外部に何も送らない） |
| `OSRM_URL` | `http://osrm:5000` | OSRM の URL |
| `LOCAL_CONGESTION_FACTOR` | `1.8` | OSRM の時間に掛ける混雑係数 |
| `JAGEOCODER_DB2_DIR` | `data/jageocoder/db` | jageocoder の辞書の場所 |
| `SECRET_KEY` / `SECRET_KEY_FILE` / `DEBUG` / `EXTRA_ALLOWED_HOSTS` | | 常用サーバー（compose の `web`）向け。`docs/remote-access.md` |

### 関東の OSRM グラフを作る

一般道の所要時間に使う OSRM のグラフは大きいのでリポジトリに含めていません。`routing/evaluate.sh` で作ります（Geofabrik から関東の OSM データ約 500MB を取得し、Docker で前処理します。数 GB のメモリと数十分かかります）。Bash（Windows では Git Bash）で次を実行します。

```sh
bash routing/evaluate.sh osrm
# → data/routing/kanto-XXXXXXXX/osrm/ にグラフができる（「Results:」に表示されるディレクトリ）
mkdir -p data/osrm/kanto
cp -r data/routing/kanto-XXXXXXXX/osrm/. data/osrm/kanto/
docker compose -f .devcontainer/compose.yaml up -d osrm
```

`data/osrm/kanto/kanto.osrm*` があれば、compose の `osrm` サービスが読み込みます。評価結果の詳細は `docs/routing-eval.md` を参照してください。

### 住所の辞書（jageocoder）を入れる

住所の入力には jageocoder の街区レベル辞書を使います（約 350MB、外部には住所を送りません）。辞書はリポジトリに含めていません。

```bash
mkdir -p data/jageocoder
curl -L -o data/jageocoder/gaiku_all_20250423_v22.zip \
  https://www.info-proto.com/static/jageocoder/latest/v2/gaiku_all_20250423_v22.zip
# コンテナの中で
jageocoder install-dictionary -y --db-dir=/workspaces/tollroute/data/jageocoder/db \
  /workspaces/tollroute/data/jageocoder/gaiku_all_20250423_v22.zip
```

辞書の利用条件と出典は、導入後の `data/jageocoder/db/README.md` と [NOTICE.md](NOTICE.md) を参照してください。画面にも出典を表示します。

### 駅名での入力（HeartRails Express）

出発地・目的地に「新宿三丁目駅」のように「駅」で終わる名前を入れると、駅名検索 API の
[HeartRails Express](https://express.heartrails.com/)（`getStations`）で駅の座標を求めます。
「中野」のような短い入力が住所として見つからないときも、駅名として探します。

- 外部に送るのは駅名（末尾の「駅」を除いたもの）だけです。番地を含む住所は送りません。結果はメモリにキャッシュします。
- 同じ名前の駅が複数あるときは、関東の駅を優先します（ほかの候補は `Place.others` に入ります）。
- API に接続できないときは 503、駅が見つからないときは 400 を返します。
- 無料で使う条件として、画面に「HeartRails Express」のクレジットを表示します
  （[API の説明](https://express.heartrails.com/api.html)、[利用規約](https://www.heartrails.com/company/terms.html)）。

### 祝日データの更新（内閣府 CSV）

祝日は内閣府「[国民の祝日について](https://www8.cao.go.jp/chosei/shukujitsu/gaiyou.html)」の CSV を
`engine/holidays_jp.json` に変換して使います（公共データ利用規約 第1.0版 / PDL1.0、出典の記載が必要）。
翌年分が追加されたら（例年 2 月ごろ）、リポジトリのルートで次を実行して更新します。

```sh
python tools/update_holidays.py
```

NEXCO の休日割引の適用除外日（`engine/calendar.py` の `NEXCO_HOLIDAY_EXCLUDED`）は手で更新します。

## テスト

料金エンジンと探索のテストは Django なしで動きます（Python 3.12 と pytest があれば OK）。

```sh
python -m pytest -q engine
```

Django アプリを含む全テストはコンテナの中で実行します（PostGIS が必要）。

```sh
docker compose -f .devcontainer/compose.yaml exec -T app pytest -q
```

テストは OSRM・住所の辞書・外部 API に依存しません（概算の所要時間を使い、住所・駅名の変換は差し替えています）。GitHub Actions（`.github/workflows/ci.yml`）でも同じテストを実行します。

## ドキュメント

| ファイル | 内容 |
|---|---|
| [docs/research-fares.md](docs/research-fares.md) | ETC 料金制度の調査（料金エンジンの仕様、出典つき） |
| [docs/algorithm-selection.md](docs/algorithm-selection.md) | 探索アルゴリズムの選定 |
| [docs/exact-search-design.md](docs/exact-search-design.md) | 時刻で料金が変わる道路網の厳密探索の設計 |
| [docs/routing-eval.md](docs/routing-eval.md) | 関東のルート検索エンジン（OSRM / Valhalla）の評価 |
| [docs/research-routing-apis.md](docs/research-routing-apis.md) | 一般道の所要時間・住所・駅名・祝日の外部 API の調査 |
| [docs/research-demo-distances.md](docs/research-demo-distances.md) | デモ道路網の区間距離の調査 |
| [docs/research-hosting.md](docs/research-hosting.md) | 公開・ホスティングの調査 |
| [docs/ux-redesign.md](docs/ux-redesign.md) | 画面設計の見直し |
| [docs/remote-access.md](docs/remote-access.md) | 自宅の PC で動かしてスマホから使う（Tailscale） |
| [docs/HANDOVER.md](docs/HANDOVER.md) | 作業の引き継ぎメモ |
| [docs/codex-tasks/](docs/codex-tasks/) | Codex への作業依頼と結果の記録 |

## 制限事項・未対応

- **首都圏の起終点を基本とした料金**（NEXCO と首都高を続けて使うときの調整）に未対応。現在は料金プールごとの単純な足し算
- **中央道の 630 円上限**（対象利用）に未対応
- **IC の方向制限**（ハーフ IC など、入れる・出られる方向の制限）に未対応
- 全国の道路網には未対応（デモ道路網のみ）
- 料金は**概算**で、公式の料金と照合している途中です

## 免責

表示する料金・所要時間はこのアプリによる**推定値**であり、NEXCO・首都高速道路株式会社などの公式な料金ではありません。実際の料金は各道路会社の公式サイトで確認してください。このアプリの利用によって生じたいかなる損害についても、作者・貢献者は責任を負いません。

## ライセンス

- コード: [MIT License](LICENSE)
- データ・外部サービス: [NOTICE.md](NOTICE.md)（`routes/demo_ics.json` は ODbL 1.0 です）

貢献の方法は [CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。
