# データと外部サービスの出典・ライセンス

このリポジトリの**コード**は [MIT License](LICENSE) です。ただし、次のデータ・外部サービスにはそれぞれのライセンス・利用条件があります。データを再配布・改変するときは、各ライセンスに従ってください。

## リポジトリに含まれるデータ

### `routes/demo_ics.json`（OpenStreetMap 由来、ODbL 1.0）

デモ道路網の IC・JCT の名前と座標です。OpenStreetMap の `highway=motorway_junction` を Overpass API で取得し（2026-11-23）、同じ名前の点の座標を平均して作成しました。

- © OpenStreetMap contributors
- ライセンス: [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/)
- 著作権・ライセンスの説明: https://www.openstreetmap.org/copyright

**このファイルには MIT License ではなく ODbL 1.0 が適用されます。** ODbL は「継承（share-alike）」の条件があるデータベースライセンスです。

- このファイル（またはこれを改変・拡張したデータベース）を公開・配布するときは、ODbL 1.0 のもとで公開し、OpenStreetMap への出典表示を残してください。
- 改変したデータベースを公開するときは、改変後のデータベース（または改変内容）も ODbL で提供する必要があります。
- このファイルを読み込むコード（`routes/demo.py` など）は ODbL の対象ではなく、MIT License のままです。
- このデータから作った画面・結果（Produced Work）を公開するときは、「© OpenStreetMap contributors」の表示が必要です。

### `engine/holidays_jp.json`（内閣府「国民の祝日」、PDL1.0）

- 出典: 内閣府「[国民の祝日について](https://www8.cao.go.jp/chosei/shukujitsu/gaiyou.html)」（[CSV](https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv)）の CSV を加工して作成
- 加工の内容: CSV（CP932）を JSON に変換し、日付を ISO 8601 形式にした（`tools/update_holidays.py`）
- ライセンス: [公共データ利用規約（第1.0版）（PDL1.0）](https://www.digital.go.jp/resources/open_data/public_data_license_v1.0)

NEXCO の休日割引の適用除外日（`engine/calendar.py`）は、NEXCO 各社の発表をもとに手で入力しています（出典は `docs/research-fares.md`）。

### 料金規則（`engine/tariffs.py` ほか）

料金エンジンの料金表・割引の条件は、NEXCO 各社・首都高速道路株式会社・国土交通省などの公式資料をもとに実装しています。各数値の出典（URL・確認日）は [docs/research-fares.md](docs/research-fares.md) にまとめています。料金は推定値であり、公式の料金ではありません。

### `routes/census_speeds.json`（国土交通省「道路交通センサス」、PDL1.0）

一般道の所要時間の見積もりに使う、地域別の平均旅行速度です。

- 出典: 「令和3年度 全国道路・街路交通情勢調査 一般交通量調査 集計表」5. 旅行速度整理表（都道府県別道路種別別）（国土交通省） https://www.mlit.go.jp/road/census/r3/
- 加工の内容: CSV（CP932）から「一般道路計」の行の、混雑時（朝夕）と非混雑時（昼間）の旅行速度の「合計」の列を取り出して JSON にした（`tools/update_census_speeds.py`）。上の資料を加工して作成したもので、国土交通省が作成したものではありません。
- ライセンス: [公共データ利用規約（第1.0版）（PDL1.0）](https://www.digital.go.jp/resources/open_data/public_data_license_v1.0)（[国土交通省ウェブサイトの利用条件](https://www.mlit.go.jp/link.html)）

## リポジトリに含まれないデータ（各自で取得）

### jageocoder 住所データベース（街区レベル）

住所の検索に使う辞書です。リポジトリには含めていません（README の手順で各自ダウンロードします）。株式会社情報試作室が次のデータを加工して作成したもので、利用条件は辞書に同梱の `README.md`（導入後は `data/jageocoder/db/README.md`）に従います。辞書を複製・配置するときは、その `README.md` を必ず同じ場所に置いてください。

- 国土交通省「[位置参照情報](https://nlftp.mlit.go.jp/cgi-bin/isj/dls/_choose_method.cgi)」（大字町丁目レベル・街区レベル、令和5年）: 政府標準利用規約（第2.0版）
- ROIS-DS 人文学オープンデータ共同利用センター「[歴史的行政区域データセットβ版地名辞書](https://geonlp.ex.nii.ac.jp/dictionary/geoshape-city/)」: CC BY 4.0
- 株式会社Geolonia「[Geolonia 住所データ](https://geolonia.github.io/japanese-addresses/)」: CC BY 4.0
- 日本郵便「[郵便番号データ](https://www.post.japanpost.jp/zipcode/dl/readme.html)」: 自由に配布可
- デジタル庁「[アドレス・ベース・レジストリ](https://www.digital.go.jp/policies/base_registry_address_tos/)」（日本 町字マスター データセット）: 政府標準利用規約（第2.0版）

辞書の利用条件により、このアプリを公開する場合は、利用者から見えるところに次の文言を表示します（画面の出典欄）。

> 「位置参照情報（大字町丁目・街区レベル）令和5年」（国土交通省）、「Geolonia 住所データ」（株式会社Geolonia） https://geolonia.github.io/japanese-addresses/、「アドレス・ベース・レジストリ」（デジタル庁） https://www.digital.go.jp/policies/base_registry_address_tos/ をもとに、株式会社情報試作室が加工した jageocoder 用住所データベース（街区レベル）を利用

jageocoder 本体（Python パッケージ）は `requirements.txt` でインストールします。

### OpenStreetMap の関東データと OSRM のグラフ

一般道の所要時間に使う OSRM のグラフは、Geofabrik が配布する OpenStreetMap の関東データ（`kanto-latest.osm.pbf`）から `routing/evaluate.sh` で作成します（リポジトリには含めません）。

- データ: © OpenStreetMap contributors、[ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/)（配布: [Geofabrik](https://download.geofabrik.de/asia/japan/kanto.html)）
- 作成したグラフ（派生データベース）を配布する場合は ODbL 1.0 に従ってください。

## 外部サービス・ソフトウェア

### HeartRails Express（駅名検索 API）

駅名から座標を求めるのに [HeartRails Express](https://express.heartrails.com/) の API を使っています。無料で使う条件として、**画面に「HeartRails Express」のクレジットを表示する必要があります**（[API の説明](https://express.heartrails.com/api.html)、[利用規約](https://www.heartrails.com/company/terms.html)）。API に送るのは駅名だけです。

### OSRM（Open Source Routing Machine）

一般道の所要時間の計算に [OSRM](https://github.com/Project-OSRM/osrm-backend) の公式 Docker イメージを使っています。ライセンス: BSD 2-Clause License。

### 地理院タイル

現在は地図タイル（地理院タイルを含む）を使っていません。将来使う場合は、[国土地理院コンテンツ利用規約](https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html)に従って出典を表示し、この NOTICE に追記します。

### 地図・ナビアプリとの連携

選んだルートを Google マップ・Yahoo!カーナビで開くためのリンク（URL スキーム）を生成しています。これらのサービスのデータは使っていません。各サービス名は各社の商標です。

### Python パッケージ

Django、psycopg、dj-database-url、jageocoder、gunicorn、WhiteNoise、pytest などは、それぞれのライセンスで提供されています（`requirements.txt`）。
