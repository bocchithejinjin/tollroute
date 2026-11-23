# 関東のルート検索エンジン評価

2026-11-23 時点。出発地から周辺の高速 IC まで、有料道路を除外した車の所要時間を一括取得する用途を対象にした。

## 実行環境とデータ

| 項目 | 確認結果 |
| --- | --- |
| 開発 PC | Windows 11、メモリ 16 GB、Docker Desktop（WSL 2）。依頼時の環境情報 |
| Docker の `MemTotal` と CPU 数 | **未確認**。標準の Docker パイプと Desktop Linux エンジンのパイプの両方で `Access is denied`。接続失敗時の `0` は計測値に採用していない |
| 関東の PBF | 配布ページの表示は **501 MB**。端末からの HTTPS 接続に失敗したため、`data/osm/` への取得は未完了。実ファイルのバイト数とハッシュは未確認 |
| 全国の PBF | 配布ページの表示は **2.4 GB**。端末での HEAD は接続に失敗し、正確なバイト数は未確認。全国版のダウンロードと前処理は未実施 |

配布サイズの出典は [Geofabrik の関東ページ](https://download.geofabrik.de/asia/japan/kanto.html) と [日本ページ](https://download.geofabrik.de/asia/japan.html)。

## 前処理と実測結果

以下のイメージはタグとダイジェストで固定した。公開タグ、Compose の設定解析、Bash の構文を確認した。IC 選択、問い合わせの組み立てと応答の集計、全国への外挿計算はテストデータで確認した。イメージの取得とコンテナでの実行は未確認。

| 項目 | OSRM | Valhalla |
| --- | --- | --- |
| イメージ | `ghcr.io/project-osrm/osrm-backend:26.11.0-debian` | `ghcr.io/valhalla/valhalla:3.6.3` |
| 前処理 | `car.lua`、MLD の extract → partition → customize | 関東 PBF からの行政境界 DB と車用タイルの生成 |
| ピークメモリ | 未確認 | 未確認 |
| 前処理時間 | 未確認 | 未確認 |
| 前処理後のグラフ容量 | 未確認 | 未確認 |
| 起動確認 | 未確認 | 未確認 |

公開イメージの出典は [OSRM のタグ一覧](https://github.com/Project-OSRM/osrm-backend/pkgs/container/osrm-backend/versions?filters%5Bversion_type%5D=tagged) と [Valhalla のタグ一覧](https://github.com/valhalla/valhalla/pkgs/container/valhalla/versions?filters%5Bversion_type%5D=tagged)。

前処理時間は Docker が記録する各コンテナの起動から終了までを合計する。画像取得、PBF 取得、Valhalla の設定生成、IC の抽出、サービス起動は計測区間外。既定のスレッド数は Docker が報告する CPU 数と 4 の小さい方。メモリは各処理中に `docker stats --no-stream` を繰り返し、各取得後に 1 秒待つ。記録から最大値を求めるため、短いピークを取りこぼす可能性がある。サンプルが取れなかったステージの値は未確認として扱う。

容量は OSRM のグラフファイル一式、または Valhalla のタイル、行政境界 DB、設定ファイルの論理サイズの合計。PBF、コンテナイメージ、ログ、一時ファイル、WSL の仮想ディスクの割当容量は集計対象外。Valhalla は標高、タイムゾーン DB、交通データを追加せず、タイルをディレクトリから配信する。

## 問い合わせ

出発地は神奈川県内の駅、単一路線の到着地は東京都内の駅（直線で約 30km）。今後の計測は横浜駅 → 新宿駅で行う（routing/evaluate.py）。有料道路を許可する試行では各エンジンの標準設定を使い、結果が実際に有料道路を通ったかも記録する。除外時は OSRM で `exclude=toll`、Valhalla で `auto.exclude_tolls=true`（`costing_options` 配下）と位置候補の `search_filter.exclude_toll=true` を指定する。OSM の有料道路タグの網羅性は別途検証が必要。 [OSRM の car プロファイル](https://github.com/Project-OSRM/osrm-backend/blob/v26.11.0/profiles/car.lua) [Valhalla の除外設定](https://github.com/valhalla/valhalla/blob/3.6.3/scripts/valhalla_build_config)

| 問い合わせ | OSRM | Valhalla |
| --- | --- | --- |
| 有料道路を許可した経路の所要時間・距離・有料区間の有無・応答時間 | 未確認 | 未確認 |
| 有料道路を除外した経路の所要時間・距離・有料区間の有無・応答時間 | 未確認 | 未確認 |
| 1 対 30 の所要時間表（有料道路を除外）と応答時間 | 未確認 | 未確認 |

IC 候補は両エンジンと同じ PBF から `highway=motorway_junction` の名前付きノードを抽出する。出発地から 120 km 以内を近い順に並べ、同名・相互に 3 km 未満の候補と JCT と読める名前を除き、30 地点を選ぶ。道路への座標の割り当てはエンジンごとに行われるため、本番で使う IC については一般道側の接続点を確認したい。

起動確認のあと、各問い合わせをローカル HTTP で 1 回ずつ送る。応答時間は送信開始からレスポンス本文の読み取り完了まで。経路・行列の所要時間はエンジンによる推定秒数で、到達不能セルは `null` として保存する。 [OSRM Table API](https://project-osrm.org/docs/v5.24.0/api/#table-service) [Valhalla Matrix API](https://valhalla.github.io/valhalla/api/matrix/)

## 全国版の概算と判断

公称の PBF サイズは全国が関東の **約 5 倍**。各エンジンの関東実測に、この比率を掛ける一次見積もりとする。関東実測が未取得のため、以下は計算式の段階。道路網の構成やビルドの並列度、キャッシュ、スワップの影響で、とくにメモリと所要時間はこの概算から外れ得る。

| 指標 | OSRM の全国概算 | Valhalla の全国概算 |
| --- | --- | --- |
| 前処理ピークメモリ | 関東の OSRM のピーク × 約 5 | 関東の Valhalla のピーク × 約 5 |
| 前処理時間 | 関東の OSRM の時間 × 約 5 | 関東の Valhalla の時間 × 約 5 |
| グラフ容量 | 関東の OSRM の容量 × 約 5 | 関東の Valhalla の容量 × 約 5 |

16 GB 機で全国版を前処理できるかは保留。仮に Docker の `MemTotal` が 8 GiB なら、比例計算でその上限に達する関東のピークは約 1.6 GiB。Docker 内の他の使用分とサンプリング誤差も見込んで判断する。ディスクは全国 PBF 約 2.4 GB と推定グラフ容量に、処理途中の一時領域と Docker イメージの分を加えて確保する。

まず関東で両方の行列が有料道路除外つきで成立するかを確認し、到達率と資源使用量で選ぶ。OSRM MLD を先に試す候補とする。標準の car プロファイルと Table API で今回の問い合わせを構成できるため。Valhalla の採用は、厳格な除外が行列でも機能し、実測で資源使用量や到達率に利点がある場合に検討する。全国処理がメモリ上限に近い場合は、近隣 IC の検索に合わせて地域別のデータを用意し、境界をまたぐ検索に重複範囲を確保する。全国で一つのグラフが必要なら別マシンで前処理して配布する。スワップを増やす案は、前処理の時間増加も許容できる場合に限って試す。

## 再現

Docker Desktop の Linux エンジンに接続できる Git Bash で、リポジトリ直下から実行する。Docker エンジンと公開ポートの両方に接続できる WSL からも実行できる。Docker Compose v2、curl、Python 3.11 以上が必要。

```bash
bash routing/evaluate.sh
```

`osrm` または `valhalla` を引数に渡すと片方だけ実行できる。`ROUTING_THREADS=2` のようにスレッド数を指定できる。ポートは OSRM が `127.0.0.1:5000`、Valhalla が `127.0.0.1:8002`。計測後にコンテナを停止・削除し、PBF と生成データは `data/` に保存する。

| 実行ごとの保存先 `data/routing/kanto-*/` | 内容 |
| --- | --- |
| `environment.json`、`threads.txt` | Docker の CPU 数とメモリ総バイト数、PBF のバイト数と SHA-256、スレッド数 |
| `japan-headers.txt` | 全国 PBF の HEAD 応答 |
| `targets.json` | 共通の 30 地点の名前、OSM ノード ID、緯度経度 |
| 各エンジンの `build.json` とステージ別のログ・CSV | 前処理時間、サンプル最大メモリ、グラフ容量。全国 PBF の `Content-Length` が得られた場合は比率と外挿結果も併記 |
| 各エンジンの `queries.json` と `*.response.json` | 経路の所要時間・距離・有料道路の判定、各 IC への所要時間、HTTP 応答時間と元の応答 |
