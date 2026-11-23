# tollroute 公開先ホスティング調査（無料・低価格）

- 調査日: **2026-11-23**（本文の価格・条件はすべてこの日に公式ページで見たもの。ページから読み取れなかったものは **未確認** と書いた）
- 価格はよく変わる。申し込み前に各リンク先で必ず再確認すること。
- 為替は概算で 1 USD ≈ 150 円、1 EUR ≈ 165 円として円換算した（為替レート自体は **未確認**・目安）。

---

## 1. このアプリに必要なもの

`.devcontainer/compose.yaml` と手元のデータから見積もった。

| 構成要素 | 中身 | ディスク | メモリ（見積もり） |
|---|---|---|---|
| web | Django 5.2 + gunicorn（2 workers）、Python 3.12、GDAL | イメージ 1〜2 GB 程度 | 0.3〜0.6 GB |
| db | `postgis/postgis:17-3.5` | 数百 MB〜（データ量しだい） | 0.2〜0.5 GB |
| osrm | `ghcr.io/project-osrm/osrm-backend:26.11.0-debian`、MLD、関東グラフ | **3.1 GB**（`data/osrm/kanto`） | **約 2.4〜3 GB**（下記） |
| jageocoder 辞書 | 読み取り専用ファイル | 約 1.4 GB（`data/jageocoder` は zip 込みで 1.8 GB） | OS のページキャッシュ頼み（固定確保は少ないはず、**未確認**） |

### OSRM のメモリ見積もり

- OSRM 公式 wiki: 「基本的に全ファイルをメモリに読み込むので、必要 RAM ≒ 前処理済みファイルの合計 − `.fileIndex`（mmap でオンデマンド読み込み）」
  <https://github.com/Project-OSRM/osrm-backend/wiki/Disk-and-Memory-Requirements>
- 手元の `data/osrm/kanto` の内訳: 合計 3.1 GB。最大は `kanto.osrm.cell_metrics`（1.43 GB、除外クラスごとのメトリクス）。`.fileIndex` は 180 MB。
- `.ebg` `.cnbg` `.cnbg_to_ebg` `.enw` `.edges`（計 約 560 MB）は前処理用の中間ファイルで、`osrm-routed` は読まないと考えられる（**未確認**）。
- 以上から、**OSRM の常駐メモリは約 2.4〜2.9 GB** と見積もった（実測ではない。`docker stats` で要確認）。
- `osrm-routed --mmap`（`-m`）: 「データファイルを RAM に読み込まず、メモリマップする」。
  <https://project-osrm.org/docs/v26.5.0/tools>
  - これを使うと、使われた部分だけがページキャッシュに載る。少人数利用なら RAM 4 GB の VM でも動く見込み。
  - ただし RAM が足りずディスクから読むと遅くなる（discussion #6840 の報告）。
    <https://github.com/Project-OSRM/osrm-backend/discussions/6840>
- 前処理（extract/partition/customize）は約 6 GB 必要。開発 PC で作ってアップロードする想定。

**結論: RAM は 4 GB で「ぎりぎり（`--mmap` 推奨）」、6〜8 GB あれば余裕。ディスクは 20 GB 以上（OS とイメージ込みで 30〜40 GB あると安心）。**

### ARM64（Oracle A1、Hetzner CAX、Azure B2pts など）で動くか

2026-11-23 に `docker buildx imagetools inspect` で確認した。

| イメージ | linux/arm64 | 対応 |
|---|---|---|
| `ghcr.io/project-osrm/osrm-backend:26.11.0-debian` | **あり**（amd64 と arm64） | そのまま使える。ただし compose はダイジェスト固定（`@sha256:e1929ae…`）。これはマルチアーキのインデックスなので arm64 でも解決される |
| `postgis/postgis:17-3.5`（`17-3.6`、`latest` も） | **なし（amd64 のみ）** | ARM では **`imresamu/postgis:17-3.5`**（amd64 と arm64/v8 あり）に差し替えるか、自前でビルドする。`imresamu/postgis` はコミュニティ版（PostGIS docker のメンテナ個人のリポジトリと言われているが **未確認**） |
| `python:3.12-trixie`（web のベース） | **あり** | Dockerfile はそのままビルドできる見込み。`jageocoder` と依存パッケージの arm64 wheel は **未確認**（無ければ pip がソースからビルドする） |
| OSRM の前処理済みファイル（x86_64 で作成） | — | arm64 の `osrm-routed` でそのまま読めるかは **未確認**。読めなければ VM 上で再前処理する（Oracle A1 なら RAM 12 GB あるので可能） |

---

## 2. サービス別の比較

### 2.1 Oracle Cloud（OCI）Always Free — Ampere A1（ARM64）

出典: <https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm>（2026-11-23 閲覧）

- **無料枠**:
  - A1: 毎月最初の 1,500 OCPU 時間と 9,000 GB 時間が無料。Always Free テナンシーでは **2 OCPU・12 GB RAM** 相当（以前は 4 OCPU・24 GB と広く紹介されていたが、2026-11-23 時点の公式ページはこの値）。このアプリには十分。
  - 1 台にまとめても、2 台に分けてもよい。
  - ブロックボリューム（ブート込み）合計 **200 GB**。
  - 外向き転送 **10 TB/月**。
- **月額（4〜8 GB RAM、20 GB ディスク）**: **0 円**（無料枠内）。
- **クレジットカード**: 本人確認に必要。一時的なオーソリはあるが、アップグレードしない限り請求されない。プリペイド・バーチャルカードは不可。
  <https://www.oracle.com/in/cloud/free/faq/>
- **日本の近く**: 東京・大阪リージョンがある（一般的な情報。Always Free の A1 がそのリージョンで取れるかは **未確認**）。
  - Always Free のインスタンスは**ホームリージョン**にしか作れず、ホームリージョンは後から変えられない。
- **Docker Compose**: 普通の Linux VM なので使える（Ubuntu/Oracle Linux に Docker を入れる）。
- **永続ディスク**: ブート/ブロックボリューム。
- **Claude によるデプロイ**:
  - VM の作成: `oci` CLI（`oci compute instance launch …`）。Console で作るなら所有者が行う。
  - その後は Claude が `ssh` / `scp`（または `rsync`）でデータを送り、`docker compose up -d` を実行できる。
- **注意点**:
  - **容量不足**: 「Out of host capacity」で A1 が作れないことがある。対処は別の AD で試す・時間をおいて再試行・Pay As You Go へのアップグレード（アップグレード後も Always Free の範囲は無料）。
  - **アイドル回収**: 7 日間、CPU（95 パーセンタイル）・ネットワーク・メモリ（A1 のみ）が**すべて** 20% 未満だと回収されることがある。OSRM を全読み込みすればメモリ使用率が 20% を超えるので該当しにくい見込み（`--mmap` だとメモリ使用率が下がるので注意）。PAYG にすると回収対象外になるという話もあるが **未確認**。
  - 無料のまま使う場合、My Oracle Support に問い合わせできない。
  - postgis イメージは arm64 版がない（1 章を参照）。

### 2.2 Google Cloud — 無料枠（e2-micro）と Cloud Run

出典: <https://docs.cloud.google.com/free/docs/free-cloud-features>（2026-11-23 閲覧）

- **e2-micro の無料枠**:
  - 対象は **us-west1 / us-central1 / us-east1 の 1 台だけ**（アジアは対象外）。
  - 標準永続ディスク 30 GB-月、外向き転送 1 GB/月（北米発）。
  - e2-micro は RAM 1 GB（一般的な仕様）なので **OSRM が載らず、このアプリには不向き**。
- **Cloud Run の無料枠**: 月 200 万リクエスト、360,000 GiB 秒、180,000 vCPU 秒、外向き 1 GB（北米発）。
  - 単価・東京（asia-northeast1）の料金 Tier・最大メモリは、料金ページ <https://cloud.google.com/run/pricing> の本文が取得できず **未確認**。
  - 不向きな理由:
    - OSRM の 3 GB のデータをイメージに焼くか、Cloud Storage FUSE でマウントする必要がある。
    - PostGIS は別に Cloud SQL などが必要で、Cloud SQL は無料枠がない（**未確認**）。
    - 常時起動にすると 4 GiB × 1 か月 ≒ 1,050 万 GiB 秒で、無料枠を大きく超える。
- **$300 トライアル**: 90 日間。支払い方法の登録が必要。期限が切れると請求アカウントが閉じ、30 日後に削除される。
  - 東京の e2-standard / e2-medium で試す用途には使えるが、無料で続けて使うことはできない。
- **Claude によるデプロイ**: `gcloud compute instances create …` → `gcloud compute ssh` で `docker compose`。Cloud Run なら `gcloud run deploy`。
- **月額（4〜8 GB の VM、東京）**: 料金ページを開いていないため **未確認**（e2-medium（4 GB）で月 30〜40 USD 程度という記憶はあるが確認していない）。

### 2.3 AWS — 新しい無料枠（2025 年〜のクレジット制）と Lightsail

出典: <https://aws.amazon.com/free/>、<https://aws.amazon.com/free/free-tier-faqs/>、<https://aws.amazon.com/lightsail/pricing/>（2026-11-23 閲覧）

- **無料プラン**:
  - サインアップ時に 100 USD、さらに所定のアクティビティで最大 100 USD、**合計最大 200 USD のクレジット**。
  - 無料プランは **6 か月**、またはクレジットを使い切った時点で終了する。延長はできない。
  - 終了後はアカウントが停止され、90 日後にデータが削除される（有料プランに移行しない場合）。
  - FAQ では「ほとんどの新規顧客は支払い方法なしでサインアップできる」（本人確認で求められる場合もある）。
  - 対象の EC2 インスタンスタイプ（t4g.small など）や、Lightsail がクレジットの対象かどうかはページに記載がなく **未確認**。
- **Lightsail（Linux、月額 USD）**: 東京リージョンあり。転送量の半減対象に東京は含まれない。

  | RAM | IPv4 あり | IPv6 のみ | vCPU | SSD | 転送 |
  |---|---|---|---|---|---|
  | 2 GB | $12 | $10 | 2 | 60 GB | 3 TB |
  | 4 GB | **$24（≈3,600 円）** | $20 | 2 | 80 GB | 4 TB |
  | 8 GB | **$44（≈6,600 円）** | $40 | 2 | 160 GB | 5 TB |

- **Docker Compose**: Lightsail も EC2 も普通の VM なので使える。
- **Claude によるデプロイ**: `aws lightsail create-instances …` / `aws ec2 run-instances …` → `ssh` で `docker compose`。
- **注意点**: 無料はクレジットがある間（最長 6 か月）だけ。Lightsail は料金が定額で分かりやすい。

### 2.4 Azure — 無料アカウント

出典: <https://learn.microsoft.com/azure/cost-management-billing/manage/create-free-services>、<https://azure.microsoft.com/en-us/pricing/free-services>（2026-11-23 閲覧）

- **無料枠**:
  - 最初の 30 日間は 200 USD のクレジット。
  - 12 か月間、**B1s / B2pts v2（ARM）/ B2ats v2（AMD）を各 750 時間/月**。P6（64 GiB）のマネージドディスクで使う場合が対象（Microsoft Q&A の回答）。
  - 12 か月の無料サービスを続けるには、30 日以内に従量課金へ移行する必要がある。
- **このアプリへの適合性**: 無料 VM の RAM は 1 GiB 程度（B2ats v2 / B2pts v2 は 2 vCPU・1 GiB。一般的な仕様で、この調査では未確認）なので、**OSRM が載らず不向き**。
- **その他**:
  - 東日本・西日本リージョンあり。
  - 4〜8 GB の VM の月額は **未確認**。
  - クレジットカードは通常必要（**未確認**。Azure for Students だけはカード不要と明記されている）。
  - B シリーズ v1 は 2028 年に廃止予定で、リージョンによっては作れない。
- **Claude によるデプロイ**: `az vm create …` → `ssh` で `docker compose`。

### 2.5 Fly.io

出典: <https://docs.fly.io/about/pricing>、<https://docs.fly.io/reference/regions>（2026-11-23 閲覧）

- **料金（iad/ewr の基準価格）**:
  - shared-cpu-2x 2 GB が $13.39/月。追加 RAM は $6/GB/月。
  - したがって **4 GB は約 $25、8 GB は約 $49**（計算値）。performance-2x（4 GB）は $66。
  - 価格はリージョンで変わり、東京（nrt）の価格は **未確認**（例: シンガポールは割高）。
- **ボリューム**: $0.15/GB/月（20 GB で $3）。停止中も課金される。
- **無料枠**: カードなしの新規アカウントは $1 のクレジットだけ。カードを登録すると Free プランの月 $5 分の利用枠が付く。
- **外向き転送**: アジア太平洋は $0.04/GB。
- **日本**: **nrt（東京）あり**。Managed Postgres も nrt で使える。
- **Docker Compose**: **非対応**。web / osrm / db を別々の Fly App（または Machine）に分け、6PN のプライベートネットワークでつなぐ必要がある。
  - PostGIS は Managed Postgres で使えるか **未確認**。postgis イメージを自前の App とボリュームで動かすのが確実。
- **Claude によるデプロイ**: `flyctl`（`fly launch`、`fly deploy`、`fly volumes create`、`fly sftp` でデータを送る）。CLI で完結しやすい。
- **注意点**:
  - ボリュームは 1 台の Machine に紐づき、冗長化されない。
  - OSRM のデータ（3 GB）はボリュームに入れるか、イメージに焼く。

### 2.6 Render

出典: <https://render.com/docs/free>、<https://render.com/docs/disks>、<https://render.com/docs/regions>（2026-11-23 閲覧）

- **無料枠**:
  - Web サービスは 15 分アクセスがないとスリープし、復帰に約 1 分かかる。月 750 時間まで。
  - **無料のサービスには永続ディスクを付けられない**。
  - 無料の Postgres は 1 GB で、**作成から 30 日で期限切れ**（その後 14 日の猶予）。
- **リージョン**: オレゴン、オハイオ、バージニア、フランクフルト、**シンガポール**（日本はない）。
- **有料**: インスタンスの価格とディスクの GB 単価は、料金ページ <https://render.com/pricing> の本文が取得できず **未確認**。
- **ディスクの制約**: 1 インスタンス限定で、ゼロダウンタイムデプロイができない。ビルド中はディスクにアクセスできない。
- **Docker Compose**: **非対応**。代わりに `render.yaml`（Blueprint）でサービスを列挙する。
- **Claude によるデプロイ**: Blueprint を git に置いて連携する、または Render API / Render CLI を使う。
- **向き不向き**: RAM 4 GB 以上のプランが高価な可能性が高く（**未確認**）、このアプリには割高。

### 2.7 Railway

出典: <https://docs.railway.com/reference/pricing/plans>、<https://docs.railway.com/reference/regions>、<https://docs.railway.com/guides/dockerfiles>（2026-11-23 閲覧）

- **プラン**:
  - Free: $0（月 $1 分の利用、カード不要）。
  - Trial: 一度だけ $5 のクレジット。
  - **Hobby: $5/月**（$5 分の利用を含む）。
  - Pro: $20/月。
- **従量単価**: RAM **$10/GB/月**、vCPU $20/vCPU/月、ボリューム $0.15/GB/月、外向き転送 $0.05/GB。
  - 試算: OSRM と DB と web で常時 4 GB 使うと **RAM だけで約 $40/月**。CPU は使った分だけ（アイドル時は少ない）。
- **ボリュームの上限**:
  - Free/Trial は 0.5 GB、**Hobby は 5 GB**、Pro は最大 1 TB。
  - OSRM（3.1 GB）と辞書（1.4 GB）と DB を足すと Hobby の 5 GB を超えるので、**実質 Pro が必要**（またはデータをイメージに焼く。イメージサイズの上限は **未確認**）。
- **リージョン**: アジアは**シンガポールだけ**。
- **Docker Compose**: compose ファイルをキャンバスにドロップしてインポートできる（すべての設定に対応しているわけではない）。
- **Claude によるデプロイ**: `railway` CLI（`railway up` など。今回のページでは確認できず **未確認**）。

### 2.8 Koyeb

出典: <https://www.koyeb.com/docs/reference/instances>、<https://www.koyeb.com/docs/reference/volumes>、<https://www.koyeb.com/pricing>（2026-11-23 閲覧）

- **無料インスタンス**: 512 MB、0.1 vCPU。リージョンはフランクフルトかワシントンのみ。1 時間アクセスがないとゼロにスケールする。**ボリュームは使えない**。
- **有料**:
  - large（4 vCPU・4 GB）が **$42.85/月**、xlarge（8 GB）が $85.71/月。
  - eco-large（2 vCPU・4 GB）は $21.43/月で、シンガポールでも使える。
  - プランの基本料（Pro $29/月 など）が別にかかるかもしれない（料金ページ）。必要かどうかは **未確認**。
- **ボリューム**: **1〜10 GB、ワシントン/フランクフルトのみ、パブリックプレビュー（「テスト用途向け」）**。
- **Docker Compose**: 非対応。
- **Claude によるデプロイ**: `koyeb` CLI / API。
- **向き不向き**: 日本に近いリージョンで永続ボリュームが使えないため、**不向き**。

### 2.9 Hetzner Cloud

出典: <https://www.hetzner.com/cloud/cost-optimized/>、<https://www.hetzner.com/cloud/regular-performance/>（2026-11-23 閲覧。価格は EUR・税抜・IPv4 込み）

| プラン | CPU | RAM | NVMe | 転送 | 月額 | 場所 |
|---|---|---|---|---|---|---|
| CX23 | 2（x86） | 4 GB | 40 GB | 20 TB | **€5.99（≈990 円）** | ドイツ・フィンランド |
| CAX11 | 2（ARM） | 4 GB | 40 GB | 20 TB | €6.49 | 同上 |
| CX33 | 4（x86） | 8 GB | 80 GB | 20 TB | **€8.99（≈1,480 円）** | 同上 |
| CAX21 | 4（ARM） | 8 GB | 80 GB | 20 TB | €10.99 | 同上 |
| CPX22（シンガポール） | 2 | 4 GB | 80 GB | 1 TB | €26.99 | SIN1 |
| CPX32（シンガポール） | 4 | 8 GB | 160 GB | 2 TB | €49.49 | SIN1 |

- **注意点**:
  - 2026-11-23 の時点で、ページ上では Cost-Optimized の全プランと CPX の作成ボタンに **「This product is currently unavailable」** と表示されていた。在庫切れか、ページの表示上の問題かは **未確認**。
  - **日本リージョンはない**。ドイツやフィンランドからだと往復の遅延が 200 ms 台になる（一般論）。少人数の個人利用なら実用範囲。
  - 新規アカウントには本人確認がある場合がある（**未確認**）。
- **Docker Compose**: 普通の VM なので使える。
- **Claude によるデプロイ**: `hcloud server create …` → `ssh` で `docker compose`。

### 2.10 日本の VPS（さくら / ConoHa / Xserver）

- **さくらの VPS**: <https://vps.sakura.ad.jp/specification/>（2026-11-23 閲覧、税込月額、初期費用無料）

  | プラン | 石狩 | 大阪 | 東京 | CPU | SSD |
  |---|---|---|---|---|---|
  | 2 GB | 1,738 円 | 1,848 円 | 1,958 円 | 3 | 100 GB |
  | 4 GB | **3,520 円** | 3,740 円 | 3,960 円 | 4 | 200 GB |
  | 8 GB | 7,040 円 | 7,480 円 | 7,920 円 | 6 | 400 GB |

  - **2 週間の無料お試し**あり（クレジットカード払いの場合）。年払いだと約 1 か月分安くなる。
  - Ubuntu や Docker が使えるかはページで確認できず **未確認**（一般には Ubuntu を選べる）。
  - API（さくらのクラウド API）で VPS を操作できるかは **未確認**。OS の初期化までは所有者がコントロールパネルで行い、その後は Claude が `ssh` するのが確実。

- **ConoHa VPS**: <https://vps.conoha.jp/pricing/>（2026-11-23 閲覧）
  - 4 GB（4 コア・SSD 100 GB）: 長期契約の「まとめトク」で **月 2,189 円〜**（より長い契約だと 1,691 円の表示もあった。契約期間との対応は **未確認**）。時間課金だと月の上限 3,608 円。
  - **8 GB プランはない**（4 GB の次は 12 GB）。
  - 支払いはカード、Amazon Pay、PayPal、銀行振込、コンビニなど（ConoHa チャージ）。カードがなくても可。
  - **注意**: ページに「新規申し込みをメンテナンスのため一時停止中」というバナーが出ていた。
  - ConoHa は OpenStack 互換の API がある（**未確認**）。

- **XServer VPS**: <https://vps.xserver.ne.jp/>（2026-11-23 閲覧）
  - 4 GB（4 コア・NVMe 150 GB）: **月 2,035 円〜**。
  - 8 GB（6 コア・NVMe 400 GB）: **月 3,850 円〜**。
  - いずれも長期契約の最安値と思われる。1 か月契約の価格は **未確認**。
  - データセンターは国内。
  - **注意**: ページに「申し込みが多くサーバーの空きが少ない（新規受付ができない場合あり）」と表示されていた。

- **共通**:
  - 日本国内なので遅延が小さい。普通の VM なので Docker Compose がそのまま使える。
  - Claude によるデプロイは `ssh` と `docker compose`。サーバーの契約と OS の選択は所有者が Web で行う。

### 2.11 Vercel（フロントエンド用途のみ）

出典: <https://vercel.com/docs/plans/hobby>（2026-11-23 閲覧、ページの最終更新 2026-11-12）

- **Hobby（無料）**:
  - Fast Data Transfer 100 GB、Active CPU 4 CPU 時間、Provisioned Memory 360 GB 時間、関数の実行は最長 300 秒。
  - 上限を超えると、最長 30 日間その機能が止まる。
  - 個人・非商用が前提（Fair Use。詳細は **未確認**）。
- **このアプリへの適合性**: サーバーレス関数なので、**OSRM（常駐で 3 GB）や PostGIS は動かせない**。
  - Django の画面だけを置いても、結局 OSRM と DB を別の場所に置く必要がある。
  - **このアプリでは使う理由がほとんどない。**

### 2.12 Neon / Supabase（PostGIS 対応のマネージド Postgres）

- **Neon**: <https://neon.com/pricing>、<https://neon.com/docs/extensions/postgis>（2026-11-23 閲覧）
  - 無料: プロジェクトあたり 1 GB、100 CU 時間/月。5 分アイドルで停止（無効にできない）。転送 5 GB/月。**カード不要**。
  - **PostGIS 対応**（`CREATE EXTENSION postgis;`）。
  - 東京リージョンがあるかは **未確認**。

- **Supabase**: <https://supabase.com/pricing>、<https://supabase.com/docs/guides/database/extensions/postgis>（2026-11-23 閲覧）
  - 無料: 500 MB、共有 CPU、**1 週間アクセスがないと一時停止**。アクティブなプロジェクトは 2 つまで。
  - PostGIS は拡張として有効化できる（無料プランで使えるかの明記はない、**未確認**）。
  - Pro は $25/月〜。

- **評価**:
  - DB だけを外に出しても、**OSRM の 3 GB とメモリの問題は解決しない**。
  - VM の中の PostGIS（compose の `db`）で十分なので、使う必要は薄い。
  - DB を VM から切り離したい場合の選択肢にとどまる。

---

## 3. 一覧表（RAM 4〜8 GB・ディスク 20 GB 以上の目安、2026-11-23 時点）

| サービス | 月額（4 GB / 8 GB） | 無料枠で足りるか | カード | 日本の近く | Compose | 永続ディスク | Claude の操作手段 | 主な注意点 |
|---|---|---|---|---|---|---|---|---|
| **Oracle Always Free A1** | **0 円** | **足りる**（ARM、2 OCPU・RAM 12 GB / 200 GB） | 必要（請求なし） | 東京・大阪（A1 が取れるかは**未確認**） | ○ | ○ | `oci` CLI + `ssh` | 容量不足、アイドル回収、postgis に arm64 版なし |
| GCP e2-micro / Cloud Run | 無料枠では足りない | 足りない（1 GB・US のみ） | 必要 | 東京あり（有料） | VM なら ○ | ○ | `gcloud` | Cloud Run は OSRM と PostGIS に不向き |
| AWS 無料プラン / Lightsail | $24 / $44 | クレジット最大 $200・最長 6 か月 | 多くは不要（FAQ） | 東京 | ○ | ○ | `aws` CLI + `ssh` | 無料は期間限定 |
| Azure 無料 | **未確認** | 足りない（無料 VM は約 1 GiB） | 通常必要（**未確認**） | 東日本・西日本 | ○ | ○ | `az` + `ssh` | RAM 不足 |
| Fly.io | 約 $25 / $49 + ボリューム $3（iad 基準、nrt は**未確認**） | 足りない | 必要 | **東京（nrt）** | ×（App に分割） | ○ | `flyctl` | 構成の作り直しが必要 |
| Render | **未確認**（高め） | 足りない（無料はディスク不可・DB は 30 日） | 必要（**未確認**） | シンガポール | ×（Blueprint） | ○（有料のみ） | Blueprint / API | 割高、ディスクの制約 |
| Railway | RAM だけで約 $40 / $80 + プラン料 | 足りない | Hobby 以上は必要 | シンガポール | △（インポート） | ○（Hobby は 5 GB まで） | `railway` CLI | 常駐メモリが高くつく |
| Koyeb | $42.85 / $85.71 | 足りない | 必要（**未確認**） | シンガポール（eco のみ） | × | △（プレビュー・10 GB・米欧のみ） | `koyeb` CLI | ボリュームが未成熟 |
| **Hetzner CX23 / CX33** | **€5.99 / €8.99**（ARM は €6.49 / €10.99） | — | 必要（**未確認**） | なし（EU。シンガポールは高い） | ○ | ○ | `hcloud` + `ssh` | 遅延、在庫切れ表示 |
| **さくらの VPS** | **3,520〜3,960 円 / 7,040〜7,920 円** | 2 週間お試し | 不要（他の支払い方法あり） | **国内** | ○ | ○ | `ssh` | 価格は高め |
| ConoHa VPS | 2,189 円〜（長期）/ 8 GB なし | — | 不要 | 国内 | ○ | ○ | `ssh`（API は**未確認**） | 新規受付が一時停止中 |
| XServer VPS | 2,035 円〜 / 3,850 円〜（長期） | — | **未確認** | 国内 | ○ | ○ | `ssh` | 空き不足の表示 |
| Vercel | 0 円（Hobby） | 画面だけ | 不要 | — | × | × | `vercel` CLI | OSRM・DB を置けない |
| Neon / Supabase | 0 円（DB だけ） | DB だけ | 不要 | **未確認** | — | — | API / `psql` | OSRM の問題は解決しない |
| **現状（自宅 PC + Tailscale）** | **0 円** | — | 不要 | 自宅 | ○（すでに稼働中） | ○ | 今のまま | PC を常時起動する必要、電気代 |

---

## 4. おすすめ

| 区分 | おすすめ | 理由 |
|---|---|---|
| **無料で一番良い** | **Oracle Cloud Always Free（A1、東京か大阪をホームに）** | 無料枠に RAM 12 GB と 200 GB があり、OSRM を全部メモリに載せられる。Compose がそのまま使える。ただし postgis を `imresamu/postgis:17-3.5` に替える必要がある。A1 が作れないときは時間をおいて再試行する |
| **安い有料で一番良い** | **Hetzner CX33（8 GB・€8.99）**。日本国内にこだわるなら **XServer VPS 4 GB（2,035 円〜）か さくら 4 GB（3,520 円〜）** | Hetzner は 8 GB でも 1,500 円程度で x86 なので、今の compose をそのまま使える。遅延が気になるなら国内 VPS |
| **一番かんたん** | **現状維持（自宅 PC + Tailscale、0 円）**。クラウドの中では **AWS Lightsail 4 GB（東京、$24）** | 現状維持は何も変えなくてよい。Lightsail は定額・東京・x86 で、`aws` CLI と `ssh` だけで Claude が作業できる |

**現状維持（自宅 PC + Tailscale）について**: 今の利用者（所有者と友人数人）だけなら、0 円で一番確実。

- 欠点: PC を常に起動しておく必要がある、電気代がかかる、自宅回線の上り速度に左右される、PC 停止中は使えない。
- 友人のアクセス: Tailscale のノード共有か、Tailscale Funnel（公開 URL）で対応できる。Funnel の利用条件は **未確認**。
- クラウドに移すのは「PC を止めたい」「友人に Tailscale を入れてもらいたくない」ときで十分。

---

## 5. 第 1 候補（Oracle Always Free A1）のデプロイ手順の概要

役割分担: **所有者** はアカウント作成・カード登録・ログイン・API キーの登録。**Claude** は CLI と ssh で以降の作業。

1. **所有者**: Oracle Cloud に申し込む。ホームリージョンは**東京（ap-tokyo-1）か大阪（ap-osaka-1）**。後から変えられない。
2. **所有者**: Console で API 署名キーを作り、`~/.oci/config` を用意する。または Claude が `oci setup config` を案内する。SSH 公開鍵も用意する。
3. **Claude**: `oci compute instance launch` で VM を作る。
   - シェイプ `VM.Standard.A1.Flex`（2 OCPU / 12 GB）、Ubuntu 24.04 arm64、ブートボリューム 100 GB 程度。
   - 「Out of host capacity」になったら、AD を変えるか時間をおいて再試行する。
4. **Claude**: `ssh` で Docker Engine と compose plugin を入れる。公開方法を決める。
   - **Tailscale を VM に入れて、これまでどおり Tailscale 経由だけで使う**（ポートを開けない。一番安全）。
   - または、セキュリティリストで 443 を開けて Caddy などで HTTPS にする。
5. **Claude**: 本番用の `compose.prod.yaml` を作る（今の `.devcontainer/compose.yaml` は変更しない）。
   - `db` のイメージを `imresamu/postgis:17-3.5` に替える。
   - `web` はコードをマウントせずイメージにビルドする。
   - `osrm` はそのまま。メモリに余裕があるので `--mmap` は不要。
   - パスワードと `SECRET_KEY` は `.env` に置く。
6. **Claude**: データを送る。
   - `rsync -avz --progress data/osrm/kanto/ data/jageocoder/db/ ubuntu@VM:/srv/tollroute/data/…`（合計 約 4.5 GB）。
   - x86 で作った OSRM のファイルが arm64 で読めない場合（**未確認**）は、VM 上で `osrm-extract` / `osrm-partition` / `osrm-customize` をやり直す（A1 の RAM で足りる）。
7. **Claude**: VM 上で `docker compose -f compose.prod.yaml up -d --build` を実行する。
   - `migrate` と `collectstatic` は起動時に自動で走る。必要なら `pg_dump` で手元の DB を移す。
8. **Claude**: 動作確認と保守の設定。
   - `curl` で経路検索の API、`docker stats` で OSRM の実メモリを確かめる。
   - `restart: unless-stopped` で再起動に備える。
   - DB の定期バックアップ（`pg_dump` の cron）を設定する。

---

## 参考 URL（すべて 2026-11-23 閲覧）

- Oracle Always Free: <https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm>
- Oracle Free Tier FAQ: <https://www.oracle.com/in/cloud/free/faq/>
- Google Cloud Free: <https://docs.cloud.google.com/free/docs/free-cloud-features>
- Cloud Run 料金（本文を取得できず）: <https://cloud.google.com/run/pricing>
- AWS 無料枠: <https://aws.amazon.com/free/>
- AWS 無料枠 FAQ: <https://aws.amazon.com/free/free-tier-faqs/>
- Lightsail 料金: <https://aws.amazon.com/lightsail/pricing/>
- Azure 無料サービス: <https://learn.microsoft.com/azure/cost-management-billing/manage/create-free-services>
- Azure 無料サービス一覧: <https://azure.microsoft.com/en-us/pricing/free-services>
- Fly.io 料金: <https://docs.fly.io/about/pricing>
- Fly.io リージョン: <https://docs.fly.io/reference/regions>
- Render: <https://render.com/docs/free>、<https://render.com/docs/disks>、<https://render.com/docs/regions>
- Railway: <https://docs.railway.com/reference/pricing/plans>、<https://docs.railway.com/reference/regions>、<https://docs.railway.com/guides/dockerfiles>
- Koyeb: <https://www.koyeb.com/docs/reference/instances>、<https://www.koyeb.com/docs/reference/volumes>、<https://www.koyeb.com/pricing>
- Hetzner: <https://www.hetzner.com/cloud/cost-optimized/>、<https://www.hetzner.com/cloud/regular-performance/>
- さくらの VPS: <https://vps.sakura.ad.jp/specification/>
- ConoHa VPS: <https://vps.conoha.jp/pricing/>
- XServer VPS: <https://vps.xserver.ne.jp/>
- Vercel Hobby: <https://vercel.com/docs/plans/hobby>
- Neon: <https://neon.com/pricing>、<https://neon.com/docs/extensions/postgis>
- Supabase: <https://supabase.com/pricing>、<https://supabase.com/docs/guides/database/extensions/postgis>
- OSRM メモリ: <https://github.com/Project-OSRM/osrm-backend/wiki/Disk-and-Memory-Requirements>
- OSRM ツール: <https://project-osrm.org/docs/v26.5.0/tools>
- OSRM discussion #6840: <https://github.com/Project-OSRM/osrm-backend/discussions/6840>
- イメージのアーキテクチャ: `docker buildx imagetools inspect` で直接確認（`ghcr.io/project-osrm/osrm-backend:26.11.0-debian`、`postgis/postgis:17-3.5`、`imresamu/postgis:17-3.5`、`python:3.12-trixie`）

---

## 6. PaaS に絞った比較（2026-11-23 追記）

所有者の希望で、VM ではなく PaaS（コンテナを置くだけで動くサービス）に絞って比べ直した。

- 価格・条件はすべて 2026-11-23 に公式ページで見たもの。読み取れなかったもの、公式以外（検索結果の抜粋やコミュニティ投稿）でしか見ていないものは **未確認** と書いた。
- 為替は 1 USD ≈ 150 円（目安、**未確認**）。
- 月額は「30 日間ずっと起動」で計算した。スリープさせれば下がる。

### 6.1 前提: 2 つの構成

| | 構成 A（フル） | 構成 B（軽量） |
|---|---|---|
| PaaS に置くもの | web（Django + gunicorn）、osrm、db（PostGIS） | web だけ |
| web の RAM | 0.5〜1 GB | 0.5〜1 GB |
| 一般道の所要時間 | OSRM（`osrm-routed`、関東 MLD 3.1 GB）。全読み込みで RAM 2.5〜3 GB、`--mmap` ならもっと少なくてよい | 外部 API（OpenRouteService の無料枠） |
| OSRM のデータ置き場 | ボリューム（約 5 GB）か、イメージに焼く | 不要 |
| DB | PostGIS（PaaS 上かマネージド） | 無料のマネージド DB（Neon / Supabase）。SQLite も検討（下記） |
| jageocoder 辞書（約 1〜1.4 GB、読み取り専用） | ボリュームかイメージに焼く | イメージに焼く（イメージは約 2.5〜3 GB になる見込み、**未確認**）か、別の方法に替える |

**構成 B にする場合のアプリ側の作業**（コードを見て確認した）:

- **ORS 用の実装がまだない**。`routes/travel.py` の `TRAVEL_TIME_PROVIDER` は今 `osrm` と `estimate` だけ。ORS を使うなら `ors` の実装を足す必要がある。
  - ORS 無料（Standard）プランの上限は Directions **2,000 回/日・40 回/分**、Matrix **500 回/日・40 回/分**（公式ページ <https://openrouteservice.org/plans/> の内容を検索結果の抜粋で確認。ページ本文はリダイレクト先で読めず **未確認**）。
  - 1 リクエストの上限は Matrix 3,500 地点組（50×50）、Directions は 6,000 km まで（<https://giscience.github.io/openrouteservice/hosted-api-restrictions>）。
  - 有料道路を避けるオプション（`avoid_features: tollways`）が使えるかは今日のページでは確認できず **未確認**。
  - 出発地・目的地の座標が外部（HeiGIT）に送られる。今の「外部に何も送らない」方針（`routes/geocode.py` の説明）とは変わるので、所有者の了解が必要。
  - 少人数の利用なら 2,000 回/日で足りる見込み。上限を超えたら `estimate` に切り替える作りにする。
- **SQLite について**: `config/settings.py` は `DATABASE_URL` を `engine="django.contrib.gis.db.backends.postgis"` 固定で読んでいる。
  - 空間クエリはまだ使っていないので SQLite でも動くはず。ただし settings の変更が必要（`django.contrib.gis` を外して `sqlite3` にする。GIS を残すなら SpatiaLite）。
  - ボリュームのない PaaS では、SQLite のファイルは再デプロイで消える（管理ユーザーなどが消える）。**無料のマネージド Postgres（Supabase 東京など）を使うほうが手間が少ない**。
- **jageocoder 辞書**: イメージに焼くのがいちばん簡単。イメージが大きくなるので、各 PaaS のイメージサイズ上限（下記）に注意。
  - jageocoder にはリモートサーバーに問い合わせるモード（`jageocoder/remote.py`、`init(url=…)`）もあるが、使える公開サーバーとその利用条件は **未確認**。

### 6.2 サービス別

#### 6.2.1 Fly.io（東京 nrt）

出典: <https://docs.fly.io/about/pricing>、<https://docs.fly.io/reference/regions>、<https://docs.fly.io/volumes/overview/>、<https://docs.fly.io/launch/autostop-autostart/>、<https://docs.fly.io/mpg>（2026-11-23 閲覧）

- **料金（iad/ewr の基準価格・月額）**: shared-cpu-1x 256 MB $2.19、512 MB $3.69、1 GB $6.70、shared-cpu-2x 2 GB $13.39、performance-2x 4 GB $66。追加 RAM は $6/GB/月。
  - リージョン差: 1 GB の例で iad $6.70、fra $7.73、sin $8.50（約 1.27 倍）。**nrt の価格は未確認**。下の試算は iad 価格で、nrt はそれより 1〜3 割高い可能性がある。
- **無料枠**: カードなしは $1 のクレジットだけ。カードを登録すると Free プランで **毎月 $5 分の利用**が付く（Machine は 3 台まで）。
- **ボリューム**: $0.15/GB/月（停止中も課金）。既定 1 GB、**最大 500 GB**。1 ボリュームは 1 Machine にだけ付く。日次スナップショット（既定 5 日保持）。ビルド中と `release_command` の一時 Machine には付かない。
- **イメージサイズ**: 公式ドキュメントでは確認できず。コミュニティの告知では上限が 2 GB から約 8 GB に引き上げられた（**未確認**）。<https://community.fly.io/t/docker-image-size-limit-raised-from-2gb-to-8gb/14749>
- **スリープ**: `auto_stop_machines = "stop"/"suspend"` と `auto_start_machines` で、アクセスがないと止まり、リクエストで起きる。**止まっている間は CPU と RAM は無料**で、rootfs の $0.15/GB/月とボリュームだけかかる。
- **東京**: **nrt あり**（Managed Postgres も nrt 可）。
- **Docker Compose**: 使えない。web / osrm / db を別々の Fly App にして、プライベートネットワーク（`<app>.internal` や Flycast）でつなぐ。
- **Managed Postgres（MPG）**: Basic（Shared-2x・1 GB）**$38/月** + ストレージ $0.28/GB。**PostGIS は作成時に有効にすれば使える**。
  - 料金ページの Free プランの説明には「$4 の Managed Postgres Developer プラン」が出てくるが、MPG のページの表には載っていない。**未確認**。
- **Claude のデプロイ手段**: `flyctl` だけで完結する（`fly launch --no-deploy`、`fly deploy`、`fly volumes create`、`fly secrets set`、`fly sftp shell` でデータを送る、`fly mpg create`）。
- **構成 A の試算（月額、iad 価格）**:
  - web: shared-cpu-1x 1 GB $6.70
  - osrm: shared-cpu-2x 4 GB（2 GB $13.39 + 追加 2 GB $12）= $25.39。`--mmap` で 2 GB にすれば $13.39
  - db: postgis イメージを自前の App で動かす（shared-cpu-1x 1 GB $6.70 + ボリューム 3 GB $0.45）。MPG にすると $38 + ストレージ
  - ボリューム: osrm 5 GB $0.75、辞書 2 GB $0.30（イメージに焼くなら不要）
  - **合計 約 $28〜40（≈4,200〜6,000 円）**。Free プランの $5 を引くと約 $23〜35。nrt 価格はこれより高い可能性あり（**未確認**）。MPG にすると約 $60〜70。
- **構成 B の試算**: web 1 GB（$6.70）を auto stop にすると、使った時間だけの課金 + 停止中の rootfs（3 GB で約 $0.45）。**少人数なら $5 の無料分にほぼ収まる見込み（≈0〜1,000 円）**。DB は Supabase（東京）か Neon の無料枠。
  - 注意: 止まった Machine の起動に数秒かかる。起動時間は **未確認**（jageocoder 辞書の読み込み込みで実測が必要）。

#### 6.2.2 Render

出典: <https://render.com/pricing.md>、<https://render.com/docs/free>、<https://render.com/docs/disks>、<https://render.com/docs/regions>、<https://render.com/docs/postgresql-extensions>、<https://render.com/docs/blueprint-spec>（2026-11-23 閲覧。`render.com/pricing` の HTML は本文が取れず、同じ内容の `pricing.md` で確認）

- **料金（月額）**: プラン ID が 2026 年 8 月から変わった（検索結果の抜粋による、**未確認**）。
  - web / private service / worker: free（512 MB）$0、0.5c-512mb $7、1c-2g $25、**2c-4g $85**、2c-8g $135。
  - ディスク $0.25/GB/月。
  - ワークスペース: Hobby $0（帯域 5 GB/月）、Pro $25/月（帯域 25 GB/月）。超過は $0.15/GB。
- **無料枠**: web は 15 分アクセスがないと止まり、起動に約 1 分。月 750 時間。**ディスクは付けられない**。無料 Postgres は 1 GB・**30 日で期限切れ**（その後 14 日の猶予）。
- **ディスク**: 有料の web / private service / worker に付けられる。最大サイズはページに記載なし（**未確認**）。1 インスタンス限定、ゼロダウンタイムデプロイ不可、ビルド中は使えない、増やせるが減らせない、日次スナップショット 7 日。
- **イメージサイズ**: 公式ドキュメントに記載が見つからず **未確認**。
- **リージョン**: オレゴン、オハイオ、バージニア、フランクフルト、**シンガポール**。**日本はない**。
- **Postgres**: free $0（256 MB RAM・1 GB・30 日）、0.1c-256mb $6、0.5c-1g $19、1c-2g $40。ストレージ $0.30/GB。**PostGIS 対応**（PostgreSQL 13 以降で `CREATE EXTENSION`）。
- **Docker Compose**: 使えない。`render.yaml`（Blueprint）に web / private service（osrm）/ databases を書く。`disk:`（`mountPath`、`sizeGB`）も書ける。
- **Claude のデプロイ手段**: `render.yaml` を Git リポジトリに置いて、所有者がダッシュボードで Blueprint を一度つなぐ。以降は push で自動デプロイ。Render CLI（v2.7.0 以降）で Blueprint の検証ができる。CLI で Blueprint を適用するコマンドはページで見つからず **未確認**（Render API はある）。
- **構成 A の試算**: web 0.5c-512mb $7（512 MB で jageocoder が動くかは **未確認**、だめなら $25）+ osrm 2c-4g $85（`--mmap` で 1c-2g $25）+ ディスク 7 GB $1.75 + Postgres 0.5c-1g $19 + ストレージ → **約 $53〜113（≈8,000〜17,000 円）**。
- **構成 B の試算**: 無料の web（スリープあり・512 MB）で **$0**、常時起動なら $7。DB は無料 Postgres が 30 日で消えるので Neon / Supabase を使う。

#### 6.2.3 Railway

出典: <https://docs.railway.com/reference/pricing/plans>、<https://docs.railway.com/reference/regions>、<https://docs.railway.com/reference/app-sleeping>、<https://docs.railway.com/guides/volumes>、<https://docs.railway.com/guides/cli>（2026-11-23 閲覧）

- **プラン**:

  | プラン | 月額 | 含まれる利用 | サービスあたり RAM 上限 | ボリューム上限 | イメージサイズ上限 |
  |---|---|---|---|---|---|
  | Free | $0 | 約 $1 | 0.5 GB | 0.5 GB | 4 GB |
  | **Hobby** | **$5** | $5 | 48 GB | **5 GB** | **100 GB** |
  | Pro | $20 | $20 | 1 TB | 1 TB | 無制限 |

- **従量単価**: RAM $10/GB/月、vCPU $20/vCPU/月、ボリューム $0.15/GB/月、外向き $0.05/GB、ビルド無料。**使った分だけ**課金（割り当てではない）。
- **スリープ（Serverless）**: 外向き通信が 5 分止まると 5〜10 分後に寝る。最初のリクエストで起きる（最初の 1 回は 502 になることがある）。寝ている間の課金の詳細はページに記載なし（**未確認**）。
- **リージョン**: US West、US East、EU West、**シンガポール**。**日本はない**。
- **Docker Compose**: compose ファイルをキャンバスにドロップしてインポートできる（すべての設定には対応しない。2.7 節）。1 プロジェクトの中に複数サービスを並べ、プライベートネットワークでつなぐ。
- **イメージに焼ける**: Hobby でもイメージ 100 GB まで OK なので、**OSRM（3.1 GB）と辞書をイメージに焼けばボリューム 5 GB の制限を避けられる**。
- **PostGIS**: Railway の Postgres テンプレートで PostGIS が使えるかは **未確認**。`postgis/postgis` イメージをサービスとして置き、ボリュームを付ければ動くはず。
- **Claude のデプロイ手段**: `railway login --browserless`（または `RAILWAY_TOKEN`）、`railway init`、`railway up`、`railway add --database postgres`、`railway volume add`、`railway variable set KEY=value`。
- **構成 A の試算**: RAM 使用量 web 0.7 + osrm 3 + db 0.3 ≈ 4 GB → $40、CPU（平均 0.1 vCPU と仮定）$2、ボリューム 1 GB $0.15 → 約 $42。Hobby の $5 はこの中に含まれるので **合計 約 $42（≈6,300 円）**。`--mmap` で常駐が減れば $25〜30（mmap のページキャッシュが課金対象のメモリに数えられるかは **未確認**）。
- **構成 B の試算**: web 0.5 GB 常駐で $5 + CPU 少し → **約 $5〜7（≈750〜1,050 円）**。Serverless で寝かせればもっと下がる見込み。Free（0.5 GB・$1 分）では常時起動は足りない見込み。

#### 6.2.4 Koyeb

出典: <https://www.koyeb.com/pricing>、<https://www.koyeb.com/docs/reference/instances>、<https://www.koyeb.com/docs/reference/volumes>（2026-11-23 閲覧）

- **料金**: Pro $29/月（コンピュート $10 分を含む）。インスタンス（月額）: small 1 GB $10.71、large 4 GB $42.85、eco-small 1 GB $5.36、**eco-large 4 GB $21.43**。外向き 1 TB/月まで込み、超過はアジア $0.04/GB。
  - 有料インスタンスを使うのに Pro の月額が必須かは **未確認**。
- **無料インスタンス**: 0.1 vCPU・512 MB・2 GB SSD、1 組織 1 台、**フランクフルトかワシントンのみ**、ボリューム不可、**1 時間アクセスがないとゼロにスケール**。
- **リージョン**: Eco はワシントン・フランクフルト・**シンガポール**。標準インスタンスのリージョン一覧、東京があるかは **未確認**。
- **ボリューム**: 1〜10 GB、**ワシントン/フランクフルトのみ**、パブリックプレビュー（「テスト用途向け」）、eco と free には付かない。
- **Postgres**: 無料（0.25 vCPU・1 GB RAM・1 GB、月 5 時間）、Small $29.76/月〜、ストレージ $0.50/GB/月。リージョンはワシントン・フランクフルト・シンガポール。PostGIS 対応は **未確認**。
- **イメージサイズ上限**: **未確認**。
- **Docker Compose**: 使えない（サービスを分ける）。
- **Claude のデプロイ手段**: `koyeb` CLI / API（コマンドの詳細は今回は **未確認**）。
- **構成 A の試算**（シンガポール、データはイメージに焼く。eco-large のディスクは 20 GB）: osrm eco-large $21.43 + web eco-small $5.36 + DB は Neon 無料 → $27。Pro 必須なら $29 + ($27 − $10) = **約 $27〜46**。シンガポールではボリュームが使えないので自前の PostGIS は置けない。
- **構成 B の試算**: 無料インスタンス（フランクフルト/ワシントン、512 MB）で **$0**。日本から遠い。シンガポールの eco-small なら $5.36（+ プラン料の可能性）。

#### 6.2.5 Google Cloud Run（東京 asia-northeast1）

出典: <https://cloud.google.com/run/pricing>（本文はまた取得できず。単価は検索結果の抜粋で見たもので **未確認**）、<https://docs.cloud.google.com/run/docs/configuring/services/memory-limits>、<https://docs.cloud.google.com/run/docs/container-contract>、<https://docs.cloud.google.com/run/docs/configuring/services/cloud-storage-volume-mounts>、<https://docs.cloud.google.com/free/docs/free-cloud-features>（2026-11-23 閲覧）

- **単価（Tier 1。東京は Tier 1 とされる。どちらも検索結果の抜粋で **未確認**）**:
  - リクエスト課金: $0.000024/vCPU 秒、$0.0000025/GiB 秒、$0.40/100 万リクエスト。無料枠 180,000 vCPU 秒・360,000 GiB 秒・200 万リクエスト/月（無料枠は 2.2 節で公式確認済み）。
  - インスタンス課金（常時 CPU）: $0.000018/vCPU 秒、$0.000002/GiB 秒。無料枠 240,000 vCPU 秒・450,000 GiB 秒。
- **メモリ**: 最大 32 GiB。1 vCPU で 4 GiB まで、2 vCPU で 8 GiB まで。
- **ファイルシステム**: 書き込み先は**メモリ上**（書いた分がメモリを使う）。永続ディスクはない。
  - Cloud Storage のボリュームマウント（FUSE）はあるが、完全な POSIX ではない。OSRM のファイルを FUSE 越しに mmap するのは遅いと考えられる（**未確認**）。
- **イメージサイズ上限**: ドキュメントに記載がなく **未確認**。イメージ内のファイル（辞書など）がメモリを使うかどうかも **未確認**。
- **スリープ**: 既定でゼロにスケール（リクエストがないと 0 台）。最小インスタンス数を 1 以上にすると常時起動。
- **DB**: Cloud SQL は無料枠がない（2.2 節、**未確認**）。Neon / Supabase を使う。
- **Docker Compose**: 使えない（サービスを分ける）。
- **Claude のデプロイ手段**: `gcloud run deploy --source .`（または `gcloud builds submit` + `gcloud run deploy --image …`）、`gcloud run services update`。`gcloud` だけで完結する。
- **構成 A の試算**: osrm を 1 vCPU・4 GiB で常時起動（インスタンス課金）にすると、vCPU 259 万秒 × $0.000018 ≈ $46.7 + 4 GiB × 259 万秒 × $0.000002 ≈ $20.7 − 無料枠約 $5 → **約 $62（≈9,300 円）+ DB**。ゼロスケールにすると 3 GB の読み込みで起動が遅すぎる見込み（**未確認**）。**構成 A には不向き**。
- **構成 B の試算**: web（1 vCPU・1 GiB）をゼロスケール + リクエスト課金なら、少人数の利用は無料枠内で **$0** の見込み。Artifact Registry のイメージ保管料（約 3 GB）が少しかかる（単価 **未確認**）。コールドスタートで辞書を読み込むので最初の応答が遅い（秒数は **未確認**）。

#### 6.2.6 Heroku（参考）

出典: <https://www.heroku.com/pricing/>（2026-11-23 閲覧）

- Eco $5（0.5 GB、30 分でスリープ）、Basic $7（0.5 GB）、Standard-2X $50（1 GB）、Performance-M $250（2.5 GB）。無料枠はない。
- Postgres Essential-0 $5（1 GB）、Essential-1 $9。PostGIS の可否は **未確認**。
- 東京リージョン（Common Runtime）は料金ページに記載がなく **未確認**。dyno に永続ディスクはない。
- **構成 A は RAM 2.5 GB で $250 なので現実的でない**。構成 B は Basic $7 + Essential-0 $5 = $12 だが、他より高く、東京もない（**未確認**）ので**候補から外す**。

### 6.3 DB（構成 B 用、構成 A でも DB を外に出す場合）

| サービス | 無料枠 | PostGIS | 日本/アジア | 止まる条件 | 有料の最小 |
|---|---|---|---|---|---|
| **Supabase** | 500 MB、アクティブ 2 プロジェクト（2.12 節） | 拡張として有効化できる。ページに**プランの制限の記載なし**（無料で使えると読めるが明記はなく **未確認**） | **東京（ap-northeast-1）あり** | 1 週間アクセスがないと一時停止 | Pro $25/月 |
| **Neon** | 1 GB/プロジェクト（全体 20 GB）、100 CU 時間/月、カード不要 | **対応** | 東京なし。**シンガポール** | 5 分アイドルで停止（無効化不可。次の接続で起動） | Launch: 従量（$0.106/CU 時間、$0.35/GB 月） |
| Fly Managed Postgres | なし（$4 Developer プランの記載があるが **未確認**） | **対応**（作成時に有効化） | **nrt あり** | — | Basic $38/月 + $0.28/GB |
| Render Postgres | 1 GB、**30 日で期限切れ** | **対応** | シンガポール | — | $6/月（256 MB） |
| Koyeb Postgres | 1 GB、月 5 時間 | **未確認** | シンガポール | ゼロスケール | $29.76/月 |

出典: <https://supabase.com/docs/guides/platform/regions>、<https://supabase.com/docs/guides/database/extensions/postgis>、<https://neon.com/pricing>、<https://neon.com/docs/introduction/regions>、<https://docs.fly.io/mpg>、<https://render.com/docs/postgresql-extensions>、<https://render.com/docs/free>（2026-11-23 閲覧）

- **構成 B の DB は Supabase（東京）がいちばん近い**。今の用途（admin とヘルスチェックだけ）なら 500 MB で十分。1 週間使わないと止まるので、止まったらダッシュボードで再開する（または定期的にアクセスする）。
- Neon はシンガポールだが、5 分で止まって自動で起きるので放置しても困りにくい。どちらでもよい。

### 6.4 一覧表（2026-11-23 時点）

| サービス | A の月額（試算） | B の月額（試算） | 無料枠 | ボリューム | イメージ上限 | 1 台の RAM | スリープ | 日本/アジア | Compose | Claude の CLI |
|---|---|---|---|---|---|---|---|---|---|---|
| **Fly.io** | **$28〜40**（iad 価格。nrt は**未確認**） | **$0〜5** | カード登録で月 $5 分 | ○ 最大 500 GB、1 Machine に 1 つ | 約 8 GB（**未確認**） | 256 MB〜（追加 RAM で増やせる） | auto stop/start（停止中は CPU・RAM 無料） | **東京 nrt** | ×（App に分割） | `flyctl` |
| Render | $53〜113 | $0（スリープ）〜$7 | web 750 時間、DB 30 日 | ○ 有料のみ（最大は**未確認**） | **未確認** | 512 MB〜 | 無料は 15 分で停止、起動約 1 分 | シンガポール | ×（Blueprint） | Blueprint + CLI / API |
| Railway | 約 $42（mmap で $25〜30） | $5〜7 | 約 $1/月 | ○ Hobby 5 GB / Pro 1 TB | Hobby 100 GB | 使った分だけ（上限 48 GB） | Serverless（5〜10 分で停止） | シンガポール | △（インポート） | `railway` |
| Koyeb | $27〜46（シンガポール、焼き込み） | $0（米欧）〜$5.36 | 512 MB 1 台（米欧のみ） | △ プレビュー、1〜10 GB、米欧のみ | **未確認** | 256 MB〜 | 無料は 1 時間でゼロスケール | シンガポール（eco） | × | `koyeb` |
| Cloud Run | 約 $62 + DB | **$0**（無料枠内の見込み） | 毎月の無料枠あり | ×（メモリ上のみ、GCS FUSE） | **未確認** | 最大 32 GiB | 既定でゼロスケール | **東京** | × | `gcloud` |
| Heroku | 非現実的（2.5 GB で $250） | $12 | なし | × | **未確認** | 0.5〜2.5 GB | Eco は 30 分 | **未確認** | × | `heroku` |

### 6.5 おすすめ

| 区分 | おすすめ | 理由 |
|---|---|---|
| **構成 A（フル）に最適** | **Fly.io（nrt）** | 東京にあり、ボリュームが最大 500 GB、RAM を GB 単位で足せる。web / osrm / db の 3 App が Free プランの 3 台に収まり、約 $28〜40/月。`flyctl` だけで Claude が完結できる。次点は Railway（イメージ 100 GB に焼けるが、シンガポールで RAM が割高） |
| **構成 B（軽量）に最適** | **Fly.io（nrt）+ Supabase（東京）**。次点は Cloud Run（東京）+ Supabase | どちらも東京・ほぼ 0 円。Fly は辞書入りの大きいイメージでも動かしやすく、あとで構成 A に広げやすい。Cloud Run は無料枠が大きいが、コールドスタートとイメージ上限が **未確認** |
| **総合** | **Fly.io（nrt）。まず構成 B で始め、必要になったら osrm App を足して構成 A にする** | 1 つのサービス・1 つの CLI で両方の構成に対応できる。ただし nrt の実際の単価と、イメージサイズ上限は申し込み後に `fly` で確認すること（**未確認**） |

**構成 B の注意（再掲）**: ORS 用の `TRAVEL_TIME_PROVIDER` の実装が要る。座標を外部に送ることになる。ORS が使えないときは `estimate` に落ちる。

### 6.6 総合おすすめ（Fly.io nrt）のデプロイ手順の概要

役割分担: **所有者** はアカウント作成・カード登録・Supabase のプロジェクト作成（東京）。**Claude** は `flyctl` で以降の作業。

**構成 B（最初の段階）**

1. **所有者**: Fly.io に登録してカードを登録する（月 $5 の無料分を得るため）。Supabase で東京リージョンのプロジェクトを作り、接続文字列を Claude に渡す。ORS の API キーを取る。
2. **Claude**: `fly auth login`（またはトークン）で接続を確認する。
3. **Claude**: 本番用の `Dockerfile` を作る（`.devcontainer/Dockerfile` は変更しない）。
   - コードと jageocoder 辞書をイメージに入れる（`JAGEOCODER_DB2_DIR` を指定）。
   - gunicorn で起動、`collectstatic` はビルド時。
   - ORS の provider を `routes/travel.py` に足す（別作業）。
4. **Claude**: `fly launch --no-deploy --region nrt` で `fly.toml` を作る。
   - `[http_service]` に `auto_stop_machines = "stop"`、`auto_start_machines = true`、`min_machines_running = 0`。
   - VM は shared-cpu-1x・1 GB。
   - `release_command = "python manage.py migrate"`。
5. **Claude**: `fly secrets set SECRET_KEY=… DATABASE_URL=… ORS_API_KEY=… TRAVEL_TIME_PROVIDER=ors`。
6. **Claude**: `fly deploy`。イメージが大きすぎて失敗したら、辞書をボリュームに移す（`fly volumes create jgdict --region nrt --size 2` → `fly sftp shell` で転送）。
7. **Claude**: `curl` で動作確認、`fly logs` と `fly status` で起動時間とメモリを見る。

**構成 A に広げるとき**

8. **Claude**: osrm 用の App を作る（`fly apps create tollroute-osrm`）。
   - `fly volumes create osrm_data --region nrt --size 5`。
   - `fly sftp shell` で `data/osrm/kanto` を送る（3.1 GB）。
   - VM は shared-cpu-2x・4 GB（`--mmap` なら 2 GB）。外には公開せず、web から `tollroute-osrm.internal:5000` で呼ぶ。
9. **Claude**: DB を Fly に移す場合は、postgis イメージの App + 3 GB ボリューム（または MPG を PostGIS 付きで作成）。Supabase のままでもよい。
10. **Claude**: web の `TRAVEL_TIME_PROVIDER=osrm` と OSRM の接続先を設定して `fly deploy`。`fly ssh console` で OSRM の実メモリを確かめる。

### 6.7 参考 URL（6 章で追加、すべて 2026-11-23 閲覧）

- Fly.io: <https://docs.fly.io/about/pricing>、<https://docs.fly.io/reference/regions>、<https://docs.fly.io/volumes/overview/>、<https://docs.fly.io/launch/autostop-autostart/>、<https://docs.fly.io/mpg>、<https://docs.fly.io/postgres/>
- Fly.io イメージサイズ（コミュニティ、**未確認**）: <https://community.fly.io/t/docker-image-size-limit-raised-from-2gb-to-8gb/14749>
- Render: <https://render.com/pricing.md>、<https://render.com/docs/free>、<https://render.com/docs/disks>、<https://render.com/docs/regions>、<https://render.com/docs/postgresql-extensions>、<https://render.com/docs/blueprint-spec>
- Railway: <https://docs.railway.com/reference/pricing/plans>、<https://docs.railway.com/reference/regions>、<https://docs.railway.com/reference/app-sleeping>、<https://docs.railway.com/guides/volumes>、<https://docs.railway.com/guides/cli>
- Koyeb: <https://www.koyeb.com/pricing>、<https://www.koyeb.com/docs/reference/instances>、<https://www.koyeb.com/docs/reference/volumes>
- Cloud Run: <https://cloud.google.com/run/pricing>（本文取得できず）、<https://docs.cloud.google.com/run/docs/configuring/services/memory-limits>、<https://docs.cloud.google.com/run/docs/container-contract>、<https://docs.cloud.google.com/run/docs/configuring/services/cloud-storage-volume-mounts>
- Heroku: <https://www.heroku.com/pricing/>
- Neon: <https://neon.com/pricing>、<https://neon.com/docs/introduction/regions>
- Supabase: <https://supabase.com/docs/guides/platform/regions>、<https://supabase.com/docs/guides/database/extensions/postgis>
- OpenRouteService: <https://openrouteservice.org/plans/>（リダイレクト先の本文は取得できず、数値は検索結果の抜粋）、<https://giscience.github.io/openrouteservice/hosted-api-restrictions>
