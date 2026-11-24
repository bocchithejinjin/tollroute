# 関東のルート検索エンジン評価

2026-11-23 時点。出発地から周辺の高速 IC まで、有料道路を除外した車の所要時間を一括取得する用途を対象にした。

## 実行環境とデータ

| 項目 | 確認結果 |
| --- | --- |
| 開発 PC | Windows 11、メモリ 16 GB、Docker Desktop（WSL 2）。依頼時の環境情報 |
| Docker の `MemTotal` と CPU 数 | 8,173,834,240 バイト（7.61 GiB）、12 論理 CPU。計測は 4 スレッド |
| 関東の PBF | 525,321,130 バイト（525 MB）、SHA-256 `2a36667ce190eb307049b212eae75b22c5b4c2b0a96c48cb9f2971db68c0b2b8` |
| 全国の PBF | HTTP HEAD で 2,579,639,449 バイト（2.58 GB）。ダウンロードと前処理は未実施 |

配布サイズの出典は [Geofabrik の関東ページ](https://download.geofabrik.de/asia/japan/kanto.html) と [日本ページ](https://download.geofabrik.de/asia/japan.html)。

## 前処理と実測結果

タグとダイジェストで固定したイメージを使い、両エンジンで同一の関東 PBF を前処理した。各工程は終了コード 0 で完了した。

| 項目 | OSRM | Valhalla |
| --- | --- | --- |
| イメージ | `ghcr.io/project-osrm/osrm-backend:26.11.0-debian` | `ghcr.io/valhalla/valhalla:3.6.3` |
| 前処理 | `car.lua`、MLD の extract → partition → customize | 関東 PBF からの行政境界 DB と車用タイルの生成 |
| ピークメモリ（サンプル最大） | 6.07 GB（extract） | 4.03 GB（タイル生成） |
| 前処理時間 | 14 分 07 秒 | 30 分 49 秒 |
| 前処理後のグラフ容量 | 3.26 GB | 0.65 GB |
| 起動確認 | 経路・行列とも HTTP 200 | 経路・行列とも HTTP 200 |

公開イメージの出典は [OSRM のタグ一覧](https://github.com/Project-OSRM/osrm-backend/pkgs/container/osrm-backend/versions?filters%5Bversion_type%5D=tagged) と [Valhalla のタグ一覧](https://github.com/valhalla/valhalla/pkgs/container/valhalla/versions?filters%5Bversion_type%5D=tagged)。

前処理時間は Docker が記録する各コンテナの起動から終了までを合計する。イメージ取得、PBF 取得、Valhalla の設定生成、IC の抽出、サービス起動は計測区間外。既定のスレッド数は Docker が報告する CPU 数と 4 の小さい方。メモリは各処理中に `docker stats --no-stream` を繰り返し、各取得後に 1 秒待つ。全工程でサンプルを取得した。短いピークを取りこぼす可能性がある。GB と MB は十進表記。

容量は OSRM のグラフファイル一式、または Valhalla のタイル、行政境界 DB、設定ファイルの論理サイズの合計。PBF、コンテナイメージ、ログ、一時ファイル、WSL の仮想ディスクの割当容量は集計対象外。Valhalla は標高、タイムゾーン DB、交通データを追加せず、タイルをディレクトリから配信する。

## 問い合わせ

横浜駅から新宿駅への経路と、横浜駅から IC 候補 30 地点への所要時間表を計測した。有料道路を許可する試行では各エンジンの標準設定を使う。除外時は OSRM で `exclude=toll`、Valhalla で `auto.exclude_tolls=true`（`costing_options` 配下）と位置候補の `search_filter.exclude_toll=true` を指定する。有料区間の判定はエンジンが応答で報告した情報に基づく。 [OSRM の car プロファイル](https://github.com/Project-OSRM/osrm-backend/blob/v26.11.0/profiles/car.lua) [Valhalla の除外設定](https://github.com/valhalla/valhalla/blob/3.6.3/scripts/valhalla_build_config)

| 問い合わせ | OSRM | Valhalla |
| --- | --- | --- |
| 有料道路を許可した経路の所要時間・距離・有料区間の有無・応答時間 | 39 分 11 秒、39.72 km、あり、53 ms | 33 分 24 秒、37.05 km、あり、4,336 ms |
| 有料道路を除外した経路の所要時間・距離・有料区間の有無・応答時間 | 46 分 14 秒、36.55 km、検出なし、14 ms | 36 分 31 秒、31.10 km、検出なし、3,408 ms |
| 1 対 30 の所要時間表（有料道路を除外）と応答時間 | 27/30 地点に到達、269 ms | 27/30 地点に到達、4,846 ms |

IC 候補は両エンジンと同じ PBF から `highway=motorway_junction` の名前付きノードを抽出する。出発地から 120 km 以内を近い順に並べ、同名・相互に 3 km 未満の候補と JCT と読める名前を除き、30 地点を選ぶ。道路への座標の割り当てはエンジンごとに行われるため、本番で使う IC については一般道側の接続点を確認したい。

起動確認のあと、各問い合わせをローカル HTTP で 1 回ずつ送る。応答時間は送信開始からレスポンス本文の読み取り完了まで。経路・行列の所要時間はエンジンによる推定秒数で、到達不能セルは `null` として保存する。 [OSRM Table API](https://project-osrm.org/docs/v5.24.0/api/#table-service) [Valhalla Matrix API](https://valhalla.github.io/valhalla/api/matrix/)

## 全国版の概算と判断

全国と関東の PBF サイズの比率（4.91 倍）を関東実測に掛けた概算。道路網の構成やビルドの並列度、キャッシュ、スワップの影響を受ける。

| 指標 | OSRM の全国概算 | Valhalla の全国概算 |
| --- | --- | --- |
| 前処理ピークメモリ | 29.82 GB | 19.77 GB |
| 前処理時間 | 約 69 分 | 約 151 分 |
| グラフ容量 | 16.01 GB | 3.20 GB |

全国の前処理は、両エンジンとも概算のピークが開発 PC の 16 GB と Docker の 7.61 GiB を上回る。ディスクは PBF とグラフに加え、途中の一時領域と Docker イメージの容量も必要になる。

デモには関東の OSRM MLD を採用した。今回の 1 回ずつの計測では両方の行列が 27 地点に到達し、OSRM は応答と前処理が速かった。Valhalla は前処理ピークのメモリとグラフ容量を抑えられた。全国へ広げる際は、境界で重複する地域別グラフを用意するか、別マシンで全国グラフを前処理して配布する案がある。

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
