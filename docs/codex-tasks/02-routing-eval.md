# Codex タスク 02: ルート検索エンジンの評価（関東で OSRM と Valhalla を比べる）

## 背景
`tollroute/` は「高速代の予算内で最速のルート」を出す、ローカル専用の Django アプリ。
一般道の所要時間（有料道路を除外）を、出発地から周辺の IC 数十か所まで、まとめて求める必要がある。
開発 PC は Windows 11、メモリ 16GB、Docker Desktop（WSL 2）。将来は日本全国を対象にしたい。

## やること
1. `docker info` で Docker が使えるメモリ量（MemTotal）と CPU 数を記録する。
2. Geofabrik の関東の抽出データ（`https://download.geofabrik.de/asia/japan/kanto-latest.osm.pbf`）を `data/osm/` にダウンロードする（`data/` は .gitignore 済み）。日本全国のファイル（`asia/japan-latest.osm.pbf`）は**サイズだけ**確認する（ダウンロードしない）。
3. **OSRM**（`ghcr.io/project-osrm/osrm-backend` の固定バージョン、car プロファイル、MLD）で extract → partition → customize し、`osrm-routed` を起動する。
4. **Valhalla**（`ghcr.io/valhalla/valhalla` の固定バージョンなど、よく使われているイメージ）でタイルを作り、サービスを起動する。
5. それぞれ、前処理の**ピークメモリ**（`docker stats` を数秒おきに記録するなど）、**所要時間**、**ディスク使用量**を測る。
6. それぞれで次の問い合わせを試し、結果と応答時間を記録する。
   - 神奈川県内の駅 → 東京都内の駅（直線で約 30km）の経路。**有料道路を使う場合と、除外する場合**の所要時間と距離（OSRM は `exclude=toll`、Valhalla は auto の `use_tolls=0` か `exclude_tolls`）。
   - 1 対 30 の所要時間の表（出発地は神奈川県内の駅、行き先は関東の高速 IC 付近の 30 地点。地点は OSM の `highway=motorway_junction` から適当に選んでよい）。有料道路を除外して。
7. 日本全国でやった場合のメモリ・時間・ディスクを、関東の結果とファイルサイズの比から**見積もる**（全国の前処理は実行しない）。16GB の PC で全国がいけそうか、いけないならどうするか（地域を分ける、スワップ、Valhalla にする等）の意見を書く。

## 置き場所
- `routing/`: 再現用のスクリプト（bash。コンテナの起動、前処理、計測、問い合わせ）と compose ファイル（`routing/compose.osrm.yaml`、`routing/compose.valhalla.yaml`）。ポートは `127.0.0.1` のみに公開。
- `docs/routing-eval.md`: 結果の報告（日本語、表で）。使ったイメージのバージョン、測り方、数値、見積もり、おすすめ。
- 計測のあとはコンテナを停止してよい（データは `data/` に残す）。

## 守ること
- `explore/`、`config/`、`routes/`、`engine/`、`docs/research-fares.md` は変更しない。
- git のコミットはしない。
- 確認できなかったことは「未確認」と書き、推測と実測を区別する。

## 完了の条件
- `docs/routing-eval.md` があり、OSRM と Valhalla の実測値（メモリ・時間・ディスク・問い合わせ結果）と全国の見積もりが載っている。
- 最後に、作ったファイルの一覧と結論を短く報告する。
