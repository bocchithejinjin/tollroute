## 何を・なぜ変えたか

<!-- 例: 中央道（高井戸〜八王子）の 630 円上限に対応。公式の料金と合わない区間があったため。 -->

## どう確かめたか

- [ ] `python -m pytest -q engine` が通る
- [ ] `docker compose -f .devcontainer/compose.yaml exec -T app pytest -q` が通る
- [ ] 画面を変えた場合: http://localhost:8000/ で表示と操作を確認した（スクリーンショットがあれば貼る）

## 料金・割引に関わる変更の場合

- 出典（公式ページの URL と確認日）:
- 公式の料金と照合した区間と結果:

## 関連する Issue

<!-- 例: Closes #12 -->
