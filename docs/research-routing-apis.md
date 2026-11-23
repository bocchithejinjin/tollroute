# 一般道（有料道路回避）所要時間マトリクス API 調査

調査日: 2026-11-23。公式ページを開いて確認した内容には URL を付けています。確認できなかった点は **未確認** と書いています。

## 前提（想定する負荷）

- 1検索あたり、出発地1点→IC 約15点（1×15）と IC 約15点→目的地1点（15×1）で、合計 **約30要素**。
- 1日10〜20検索として、**300〜600要素/日、9,000〜18,000要素/月**（30日換算）。
- リクエスト数で数えると、マトリクス API なら1検索2リクエスト（月600〜1,200）、1経路ずつ呼ぶ方式なら1検索30リクエスト（月9,000〜18,000）。

---

## 1. Google Maps Platform Routes API（`computeRouteMatrix`）

| 項目 | 内容 |
|---|---|
| (1) 有料道路回避 | **公式ガイドどうしで記述が食い違っています。** REST リファレンスでは各 `origins[]` に `routeModifiers` があり、その中の `avoidTolls` は「true の場合、合理的な範囲で有料道路を避ける」と説明されています（リファレンス上 Matrix で非対応と明記されているのは `avoidTunnels` だけです）。一方、ガイド「Specify route features to avoid」（最終更新 2026-11-09）には **「Avoiding route features is not supported by the Compute Route Matrix feature」** と書かれています。Matrix で `avoidTolls` が効くかは **未確認（実機で検証が必要）**。効かない場合は `computeRoutes`（`routeModifiers.avoidTolls=true`）を30回呼ぶ方法に切り替えます。どちらの場合も回避は「where reasonable」で、有料区間がなくなる保証はありません。 |
| 要素数上限 | origins×destinations は最大625。`TRAFFIC_AWARE_OPTIMAL` のときは最大100です。 |
| (2) 無料枠 | 2025-03-01 に月$200クレジットが廃止され、**SKU ごとの月間無料上限**に変わりました。Compute Route Matrix は **Essentials 10,000要素/月、Pro 5,000要素/月、Enterprise 1,000要素/月** です。超過分は1,000件あたり Essentials $5、Pro $10、Enterprise $15（10万件まで）。課金単位は「返された要素ごと」です。 |
| SKU の判定 | **Pro** になる条件は `routingPreference` が `TRAFFIC_AWARE`/`TRAFFIC_AWARE_OPTIMAL` の場合、または side of road / heading / vehicle stopover を指定した場合です。**Enterprise** になる条件は通行料金の計算、二輪、大型車です。avoidTolls は SKU 条件として挙がっていません。 |
| 本件での試算 | 交通情報なし（Essentials）で月9k〜18k要素なので、無料枠ぎりぎりか最大$40程度の超過です。交通情報あり（Pro）は月4k〜13k要素が超過し、約$40〜130/月になります。 |
| (3) キー・カード | API キーが必須で、Cloud プロジェクトに課金アカウント（billing account）を紐付ける手順が前提です。クレジットカード登録は実質必須と考えられますが、公式文面で明示されているかは **未確認** です。 |
| (4) キャッシュ・地図の規約 | 共通規約 3.2.3(b) で、Service Specific Terms が許す範囲を除きキャッシュは禁止です。Routes API の個別規約は次のとおりです。**19.1** Google 地図なしでの利用は可。**19.2** **Google 以外の地図（Leaflet＋OSM タイルなど）と組み合わせて使うことは禁止**。**19.3** 緯度経度は最大30日までキャッシュ可。place_id は無期限で保存できます。所要時間の結果を保存して再利用することは明示的に許可されておらず、方針ページには「directions/distance matrix 結果の一括ダウンロード禁止」とあります。 |
| (5) 日本での品質 | 日本の道路網と交通データの品質は高いと一般に言われていますが、公式の比較資料は **未確認** です。 |
| (6) 交通・出発時刻 | `departureTime` と `routingPreference=TRAFFIC_AWARE(_OPTIMAL)` で対応します（Pro SKU になります）。 |

出典:
- https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRouteMatrix
- https://developers.google.com/maps/documentation/routes/reference/rest/v2/RouteModifiers
- https://developers.google.com/maps/documentation/routes/route-modifiers
- https://developers.google.com/maps/billing-and-pricing/pricing
- https://developers.google.com/maps/billing-and-pricing/sku-details/routes
- https://developers.google.com/maps/billing-and-pricing/overview
- https://developers.google.com/maps/get-started
- https://cloud.google.com/maps-platform/terms （3.2.3(b)(e)）
- https://cloud.google.com/maps-platform/terms/maps-service-terms （19. Routes API）
- https://developers.google.com/maps/documentation/routes/policies

## 2. OpenRouteService（HeiGIT ホスト版 API）

| 項目 | 内容 |
|---|---|
| (1) 有料道路回避 | `POST /v2/matrix/driving-car` のリクエストボディに `options` があり、ソースコード上は `MatrixRequestOptions extends RequestOptions` なので **`"options":{"avoid_features":["tollways"]}`** を受け付けます（GitHub main ブランチで確認）。ホスト版の制限ページには「Locations (with dynamic arguments): 25 per request」とあり、1×15（16地点）は範囲内です。ただし 2022年のフォーラム回答では「matrix は directions と同じ動的引数に非対応」とされていました。**公開 API で現在実際に効くかは未確認**（実機で検証が必要）。 |
| (2) 無料枠 | Standard（無料）プランは **Matrix 500リクエスト/日・40/分、Directions 2,000/日・40/分**（検索結果に出た公式 plans ページの表記より。現在の plans ページは JS 描画のため本文を直接は確認できず、**一部未確認**）。日次枠は最初のリクエストから24時間のローリングです。本件は1日20〜40リクエストなので十分に収まります。 |
| (3) キー・カード | 無料アカウント登録で API キーを発行します。カード登録は不要とされますが **未確認**。 |
| (4) 規約 | データは OSM 由来なので © OpenStreetMap contributors の帰属表示が必要です。結果のキャッシュを制限する条項は **未確認**。 |
| (5) 日本での品質 | OSM ベースです。日本の高速道路に `toll=yes` が網羅的に付いているか、市街地の所要時間の精度（信号や渋滞を考慮しないため過小評価になりがち）は **未確認** です。 |
| (6) 交通・出発時刻 | リアルタイム交通・出発時刻には非対応です（静的な速度モデル）。 |

出典:
- https://giscience.github.io/openrouteservice/api-reference/endpoints/matrix/
- https://giscience.github.io/openrouteservice/hosted-api-restrictions
- https://github.com/GIScience/openrouteservice/blob/main/ors-api/src/main/java/org/heigit/ors/api/requests/matrix/MatrixRequest.java
- https://ask.openrouteservice.org/t/matrix-avoid-tolls/3851
- https://openrouteservice.org/plans/ （account.heigit.org/info/plans へリダイレクト）

## 3. Mapbox Matrix API

| 項目 | 内容 |
|---|---|
| (1) 有料道路回避 | **Matrix API には `exclude` パラメータがありません**（ドキュメント上のパラメータは annotations, approaches, bearings, destinations, sources, fallback_speed, depart_at のみ）。回避するには **Directions API の `exclude=toll`**（driving / driving-traffic で使用可）を30回呼ぶ必要があります。 |
| 上限 | 1リクエスト最大25座標（driving-traffic は10座標）。60リクエスト/分（traffic は30/分）。 |
| (2) 無料枠 | Matrix は **100,000要素/月まで無料**、Directions は **100,000リクエスト/月まで無料**（pricing ページ）。 |
| (3) キー・カード | アクセストークンが必須です。カード登録の要否は **未確認**。 |
| (4) 規約 | 結果の保存や他社地図との併用に関する条項は **未確認**（product terms 本文を取得できませんでした）。 |
| (5) 日本での品質 | **未確認**。 |
| (6) 交通・出発時刻 | Matrix の `depart_at` はベータで、申請が必要です。Directions の driving-traffic は交通を反映します。 |

出典:
- https://docs.mapbox.com/api/navigation/matrix/
- https://docs.mapbox.com/api/navigation/directions/
- https://www.mapbox.com/pricing

## 4. GraphHopper Directions API

| 項目 | 内容 |
|---|---|
| (1) 有料道路回避 | 有料プランでは、Matrix で **`profile=car_avoid_toll`**（「tolls と ferries を強くペナルティ」）を使うか、`custom_model` で `toll` の encoded value を使います。ただし **Free プランは `car`/`bike`/`foot` プロファイルのみで、flexible mode（`ch.disable=true`、つまり custom_model）も使えません**。そのため無料では有料道路回避ができません。 |
| (2) 無料枠 | Free プランは **500クレジット/日、1リクエスト最大5地点、非商用のみ**、サポートはフォーラムのみ。Matrix のコストは origins×destinations/2 クレジット（最低1）です。1×15 は5地点制限のため分割が必要です。有料は Basic 5,000クレジット/日 €69/月から。 |
| (3) キー・カード | API キーは必須で、「No credit card required」と明記されています。 |
| (4) 規約 | 帰属表示が必要です（attribution ページ）。キャッシュに関する条項は **未確認**。 |
| (5) 日本での品質 | OSM（有料プランは TomTom も選択可）。日本での品質は **未確認**。 |
| (6) 交通・出発時刻 | 公開ドキュメント上、Matrix で出発時刻や交通を指定できることは確認できませんでした（**未確認**）。 |

出典:
- https://www.graphhopper.com/pricing/
- https://docs.graphhopper.com/openapi/matrices
- https://docs.graphhopper.com/ （Map Data and Routing Profiles 節）
- https://support.graphhopper.com/support/solutions/articles/44000718211-what-is-one-credit-

## 5. OSRM 公開デモサーバ（router.project-osrm.org）

| 項目 | 内容 |
|---|---|
| (1) 有料道路回避 | `table` サービスは一般オプションとして `exclude` を受け付けます。しかし **デモサーバで `exclude=toll` を付けると `"Exclude flag combination is not supported."`（InvalidValue）が返ります**（2026-11-23 に1回だけ試行して確認）。デモサーバでは有料道路回避はできません。 |
| (2) 利用条件 | **最大1リクエスト/秒**、**「reasonable, non-commercial use-cases」に限定**、稼働・遅延・データ更新の保証なし。 |
| (3) キー・カード | 不要です。 |
| (4) 規約 | OSM 帰属表示が必要です。 |
| (5) 日本 | OSM ベースです。自前でホスティングする場合（Japan extract＋exclude 付き car.lua）なら回避できますが、手間は大きくなります。 |
| (6) 交通 | 非対応です。 |

出典:
- https://github.com/Project-OSRM/osrm-backend/wiki/Demo-server
- https://project-osrm.org/docs/v5.24.0/api/

## 6. 内閣府「国民の祝日」CSV

- URL: **https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv**（掲載ページ https://www8.cao.go.jp/chosei/shukujitsu/gaiyou.html ）
- 1955年〜2027年（令和9年）を収録しています。文字コードは **Shift_JIS（CP932）**、ヘッダは `国民の祝日・休日月日,国民の祝日・休日名称`、日付は `2027/11/23` 形式です。Last-Modified は 2026-02-02（いずれも実取得で確認）。
- 規約: 内閣府ホームページ利用規約（ https://www.cao.go.jp/notice/rule.html ）では、権利表記のないコンテンツには **公共データ利用規約（第1.0版, PDL1.0）** が適用されます。PDL1.0 では商用利用可、**出典記載が必要**、加工した場合はその旨の記載が必要で、CC BY 4.0 と互換です（ https://www.digital.go.jp/resources/open_data/public_data_license_v1.0 ）。
- 毎年2月頃に翌年分が追加されるとみられますが、更新時期の公式な記載は **未確認** です。アプリ側で定期的に取得し直すのが無難です。

## 7. 無料ジオコーディング（日本）

### (a) 国土地理院 住所検索 API（`https://msearch.gsi.go.jp/address-search/AddressSearch?q=...`）
- 地理院地図が内部で使っているエンドポイントです。**外部向け API として公式に公開・保証されているものではなく、利用条件・レート制限の公式記載は見つかりませんでした（未確認）**。同じ趣旨の質問が GitHub に立っていますが、回答は確認できませんでした（ https://github.com/gsi-cyberjapan/gsimaps/issues/29 ）。
- 国土地理院コンテンツ全般の利用規約（出典記載で商用利用可）が API 応答にも及ぶかは **未確認**（ https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html ）。
- 実際に試した精度（2026-11-23）は次のとおりです。
  - 「東京都中野区中野4-11-19」（中野区役所）のような番地付きの住所は「…号」まで返り、**号レベル**でした（住居表示地区）。
  - 「千代田区霞が関2-1-2」は「霞が関二丁目1番」までの**街区レベル**でした。
  - 「〇〇駅」で検索すると、駅そのものではなく「〇〇駅前郵便局」などがヒットすることがあり、**駅名検索には向きません**。
- キー不要です。負荷をかけないようキャッシュし、低頻度で使うのが前提です。

### (b) 駅名検索
- **HeartRails Express API**（ `https://express.heartrails.com/api/json?method=getStations&name=新宿三丁目` ）は、実際に試すと、駅名・路線・座標（x=経度、y=緯度）が返り、駅名から座標を取るのに最適です。キー不要です。利用規約・レート制限は **未確認**（ https://express.heartrails.com/api.html を参照）。入力の「駅」は除いてから検索します。
- **OSM Nominatim（公開インスタンス）** の利用ポリシー（ https://operations.osmfoundation.org/policies/nominatim/ ）は次のとおりです。**最大1リクエスト/秒**、アプリを識別できる User-Agent/Referer が必須（ライブラリ既定の UA は不可）、**結果のキャッシュが必須**、**オートコンプリート用途は禁止**、大量のバルク処理も不可。日本の駅名には `railway=station` で概ねヒットすると見込まれますが **未確認** です。
- 国土地理院の地名検索は上の (a) と同じエンドポイントで、駅名の精度は低いです。

### (c) Google Geocoding / Places（2025-03 以降の無料上限）
- **Geocoding: 10,000件/月無料**、以降 $5/1,000件。
- Places: **Text Search Essentials (IDs Only) は無制限**、Text Search Pro は 5,000件/月、Autocomplete Requests は 10,000件/月、Autocomplete Session Usage は無制限。
- 課金アカウントが必要です。Google のコンテンツを Google 以外の地図に表示することは禁止です（規約 3.2.3(e)）。
- 出典: https://developers.google.com/maps/billing-and-pricing/pricing

---

## 推奨（このユースケース向け）

前提として、既存の抽象化レイヤー（出発地＋地点リストを受け取って分を返す HTTP 呼び出し）があるものとし、そこに差し替える手間を見積もっています。

| 候補 | 有料道路回避 | 無料で回るか | 交通考慮 | 主な制約 | 差し替えの手間 | 評価 |
|---|---|---|---|---|---|---|
| **ORS Matrix**（`options.avoid_features:["tollways"]`） | ○（公開 API で効くかは要実機確認） | ◎ 500 matrix/日で十分 | × | OSM 精度、OSM 帰属表示 | **小**（1×15 を2回 POST） | **第一候補（無料・まず検証）** |
| **Google computeRouteMatrix** | △（ガイドでは Matrix 非対応。リファレンスには `avoidTolls` あり。要検証） | ○ Essentials 10k/月なら概ね収まる。交通ありは $40〜130/月 | ◎（Pro SKU） | 課金アカウント必須、**非 Google 地図と併用不可**、結果保存不可 | **小**（Matrix で効く場合）／**中**（computeRoutes×30 にする場合） | 精度・交通重視なら最有力。地図を Google にする必要あり |
| Mapbox（Directions `exclude=toll` ×30） | ○（Matrix では不可） | ◎ 100k リクエスト/月 | ○ driving-traffic | Matrix で回避できず30回呼び出し、レート制限 | **中** | ORS が駄目な場合の次点 |
| GraphHopper（`car_avoid_toll`） | 有料プランのみ | × Free は car のみ・5地点・非商用 | × | €69/月〜 | 小（コード）／費用が大 | 非推奨 |
| OSRM デモ | ×（exclude=toll は非対応で確認済み） | ― | × | 1 req/s・非商用・保証なし | 小（ただし要件を満たさない） | 非推奨（自前ホストなら**大**） |

**結論**:
1. まず ORS の公開 API で `avoid_features: tollways` 付きの Matrix が効くか、首都高・東名などをまたぐ地点で実機確認します。効けば無料のまま採用できます。
2. 時間帯で変わる所要時間が必要な場合や OSM の精度が不足する場合は、Google Routes API に切り替えます。その場合、地図表示も Google Maps にし、結果は保存しません。Matrix で avoidTolls が効かなければ computeRoutes を30回呼ぶ方式にします。
3. 祝日判定は内閣府 CSV（CP932、PDL1.0 で出典を記載）、駅名は HeartRails Express、住所は国土地理院 AddressSearch（非公式 API である点に注意）を組み合わせるのが手軽です。
