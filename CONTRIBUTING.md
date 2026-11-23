# 貢献の手引き

tollroute への貢献を歓迎します。Issue・Pull Request は日本語で大丈夫です。

## 開発環境

1. Docker（Docker Desktop など）を入れます。VS Code の Dev Containers 拡張があると便利です。
2. リポジトリを clone し、[README.md](README.md) の「クイックスタート」に従ってコンテナを起動します。
   - VS Code: 「Reopen in Container」
   - Docker Compose: `docker compose -f .devcontainer/compose.yaml up -d --build`
3. OSRM のグラフと住所の辞書（jageocoder）は任意です。なくても画面とテストは動きます（README の該当節を参照）。

料金エンジンと探索（`engine/`）だけを触る場合は、Docker なしで Python 3.12 と pytest があれば開発できます。

```sh
python -m venv .venv
. .venv/bin/activate        # Windows は .venv\Scripts\activate
pip install pytest
python -m pytest -q engine
```

## ブランチと Pull Request の流れ

### ブランチの種類

| ブランチ | 役割 | 作る元 → マージ先 |
|---|---|---|
| `main` | リリース用。本番にデプロイするのはこのブランチだけ。リリースごとに `v0.1.0` のようなタグを付ける | develop → main（リリースの PR） |
| `develop` | 開発の本流（GitHub の既定ブランチ） | feature / fix → develop |
| `feature/<内容>` | 機能の追加・改良（例: `feature/chuo-630-cap`） | develop から作る → develop |
| `fix/<内容>` | 不具合の修正（例: `fix/shutoko-night-discount`） | develop から作る → develop |
| `hotfix/<内容>` | 本番の緊急修正 | main から作る → main と develop の両方 |

`main` と `develop` には直接 push できません（ブランチ保護）。必ず Pull Request を通します。

### Pull Request の流れ

1. `develop` から作業用のブランチを作ります。名前は英小文字とハイフンで、内容が分かるように付けます。
2. 変更は小さくまとめ、1 つの PR では 1 つの目的に絞ります。
3. PR の説明には「何を・なぜ変えたか」「どう確かめたか（テスト、画面の確認）」を書きます（PR のひな形に沿って書けば足ります）。料金に関わる変更は出典も書きます（下記）。
4. CI（GitHub Actions）が通り、レビューで承認されたら **Squash and merge** でマージします（履歴を 1 PR = 1 コミットに保つため）。マージ後、作業用のブランチは削除します。
5. 大きな変更（探索方式の変更、新しい道路網・データの追加など）は、先に Issue で相談してください。

### リリース

1. `develop` から `main` への PR を作り、タイトルを `Release v0.x.y` にします。
2. マージしたら、`main` にタグ `v0.x.y` を付け、GitHub の Release に変更点を書きます。
3. 本番環境へのデプロイは `main` からだけ行います（手順は `docs/remote-access.md` と、今後追加するデプロイ手順書を参照）。

バージョンは `v0.<機能追加>.<修正>` で、1.0 までは画面や API が変わることがあります。

コミットメッセージは日本語でも英語でも構いません。

## テスト（必ず通すこと）

PR を出す前に、次のテストがすべて通ることを確認してください。

```sh
# 料金エンジンと探索（Django なし）
python -m pytest -q engine

# Django アプリを含む全テスト（コンテナの中、PostGIS が必要）
docker compose -f .devcontainer/compose.yaml exec -T app pytest -q
```

挙動を変えたり直したりしたときは、それを確かめるテストを追加してください。

## 探索の正しさのルール

`engine/search.py`（多目的ラベル法）は、枝刈り・支配判定を少し間違えるだけで「予算内のもっと速いルート」を黙って落とします。そのため:

- **探索に関わる変更では、総当たりとの一致テストを必ず通すこと。** `engine/tests/test_search.py` の `test_search_matches_brute`、`test_night_v2_matches_brute` などは、ランダムな道路網で `engine/search.py` の結果と `engine/brute.py`（総当たり）の結果が一致することを確かめています。
- これらのテストを弱める（ケースを減らす、比較をゆるめる、skip する）変更はしないでください。必要なら理由を PR に書き、レビューで合意してから行います。
- 新しい料金規則や枝刈りを入れたときは、それが効くケースを総当たり照合のテストに加えてください。
- 速度改善は `explore/` のスクリプトで計測し、計測値を PR に書いてください。

## 料金データ・料金規則の変更

料金の数値・割引の条件・適用除外日などを変更・追加するときは、**公式の出典を必ず示してください**。

- 出典は NEXCO 各社・首都高速道路株式会社・国土交通省などの公式ページや公式資料（PDF）にします。個人のブログやまとめサイトは不可です。
- [docs/research-fares.md](docs/research-fares.md) の形式にならい、値・確認状況（確認済 / 未確認）・出典番号（`[S1]` など）と、出典一覧に URL・確認日を追記します。
- 確認できなかったことは「未確認」と書き、推測と確認済みの事実を区別します。
- 公式の料金検索などで照合した例は、テストに固定ケースとして加えてください。

## 書いてはいけないもの

- **秘密情報**: API キー、パスワード、トークン、`SECRET_KEY`、`.env` の中身などをコミットしないでください。設定は環境変数で渡します（`.devcontainer/.env` は Git の対象外です）。開発用データベースのパスワード（`tollroute-dev-pass`）はローカル専用の固定値です。
- **個人の住所**: テスト・ドキュメント・Issue に、自分や他人の自宅など個人の住所を書かないでください。住所の例が必要なときは、駅・役所・公共施設など公開されている場所の住所や、架空の番地を使います。
- **個人の環境の情報**: 自分の PC の絶対パス（`C:/Users/<名前>/...` など）、ホスト名、Tailscale のマシン名などは書かず、リポジトリからの相対パスにします。
- **大きなデータ**: OSM データ、OSRM のグラフ、jageocoder の辞書などは `data/` に置き、コミットしません（`.gitignore` 済み）。

## データのライセンス

新しいデータを追加するときは、ライセンスと出典を確認し、[NOTICE.md](NOTICE.md) に追記してください。OpenStreetMap 由来のデータは ODbL 1.0 になります。

## ライセンス

貢献したコードは、このリポジトリの [MIT License](LICENSE) で公開されることに同意したものとします。
