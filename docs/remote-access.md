# スマホから使う（自宅の PC ＋ Tailscale）

アプリは自宅の PC で動かし、Tailscale の私的なネットワークでスマホからだけ開けるようにします。
インターネットには公開しません（同じ Tailscale アカウントの機器からだけ見えます）。

## 構成

```
スマホ（Tailscale アプリ）
   │ https://<PC の名前>.<tailnet 名>.ts.net   … Tailscale の中だけで通じる URL（証明書は Tailscale が用意）
   ▼
PC（Windows、Tailscale）  tailscale serve が 127.0.0.1:8080 へ中継
   ▼
Docker の web サービス（gunicorn、127.0.0.1:8080 だけで受け付ける）
   ▼
db（PostgreSQL + PostGIS）
```

## 最初に 1 回だけやること

1. PC とスマホに Tailscale を入れ、同じアカウントでログインする（https://tailscale.com/download ）。
2. Tailscale の管理画面で MagicDNS と HTTPS 証明書を有効にする（DNS のページ）。
3. PC の名前を確かめる: PowerShell で `tailscale status`（例: `my-pc.tail1234.ts.net`）。
4. 常用サーバーを起動する（PowerShell、`tollroute` フォルダで）:
   ```powershell
   $env:TOLLROUTE_HOST = "my-pc.tail1234.ts.net"   # 3 で確かめた名前
   docker compose -f .devcontainer/compose.yaml up -d --build web
   ```
   `restart: unless-stopped` なので、以後は Docker Desktop が起動すれば自動で立ち上がります。
   （`TOLLROUTE_HOST` は `.devcontainer/.env` に `TOLLROUTE_HOST=my-pc.tail1234.ts.net` と書いておくと毎回の指定が不要です）
5. Tailscale で中継する（PC の PowerShell）:
   ```powershell
   tailscale serve --bg 8080
   ```
   この設定は Tailscale に保存され、再起動後も残ります。やめるときは `tailscale serve --https=443 off`。
6. スマホの Tailscale を ON にして、ブラウザで `https://my-pc.tail1234.ts.net/` を開く。ホーム画面に追加しておくと便利です。

## 使えないとき

| 症状 | 確かめること |
|---|---|
| 開けない | PC が起動しているか（スリープしていないか）、Docker Desktop が動いているか、スマホの Tailscale が ON か |
| 400 Bad Request | `TOLLROUTE_HOST` が PC の Tailscale 名と一致しているか（`docker compose ... up -d web` をやり直す） |
| 住所で検索できない | 住所の辞書（README の「住所の辞書」）が `data/jageocoder/db` にあるか |

## 注意
- PC の電源・スリープの設定によっては、外出先から使えません。
- 開発用の runserver（8000）とは別のサーバーです。コードを変えたら `docker compose -f .devcontainer/compose.yaml restart web`。
