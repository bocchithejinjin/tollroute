OSRM と Valhalla の関東比較用スクリプトと[評価報告書](/docs/routing-eval.md)を作成しました。Docker デーモンへの接続が拒否され、端末から Geofabrik にも接続できなかったため、関東 PBF の取得、前処理、経路・1 対 30 の問い合わせは未実測です。Compose の設定、Bash の構文、テストデータでの集計処理は確認しました。

全国 PBF の公称サイズは **2.4 GB** で、関東の **501 MB** の約 5 倍です。この倍率を前処理のメモリ・時間・容量の一次見積もりに使えます。16 GB 機で全国版を処理できるかは、Docker のメモリ上限と関東の実測が得られるまで保留です。関東で最初に試す候補は、標準の車用プロファイルで有料道路を除外した行列を問い合わせられる OSRM MLD です。 [Geofabrik 関東](https://download.geofabrik.de/asia/japan/kanto.html) [Geofabrik 日本](https://download.geofabrik.de/asia/japan.html)

作成したファイルは、評価報告書と以下の 4 件です。

- [evaluate.sh](/routing/evaluate.sh) と [evaluate.py](/routing/evaluate.py)
- [compose.osrm.yaml](/routing/compose.osrm.yaml) と [compose.valhalla.yaml](/routing/compose.valhalla.yaml)