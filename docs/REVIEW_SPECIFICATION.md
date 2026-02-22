# SPECIFICATION レビュー結果

## 対象

- レビュー対象: `docs/SPECIFICATION.md`
- 実装コードは未配置のため、文書レビューとして評価

## 総評

- 文書構成は良好で、MVP/将来拡張の切り分け、技術選定理由、運用前提が整理されています。
- 一方で、API 契約とスナップショット仕様の曖昧さが大きく、実装とテストで解釈差が出るリスクがあります。

## Findings（重大度順）

### High 1: API 契約が不十分で、実装/テストの解釈ずれが起きる

- 根拠: `docs/SPECIFICATION.md:148`, `docs/SPECIFICATION.md:154`, `docs/SPECIFICATION.md:157`
- 問題:
  - `/api/settings` の必須項目、許容範囲、部分更新可否が未定義
  - エラー時ステータスコード/エラーボディ形式が未定義
- 影響:
  - フロント実装とサーバー実装でバリデーション仕様が分岐
  - 異常系テストケースを設計できない
- 推奨:
  - 成功/失敗の HTTP ステータスと JSON エラー形式を明記
  - `resolution/fps/brightness/contrast` の許容値とデフォルト値を仕様化

### High 2: スナップショット仕様が競合している

- 根拠: `docs/SPECIFICATION.md:81`, `docs/SPECIFICATION.md:152`, `docs/SPECIFICATION.md:257`
- 問題:
  - F-03 は「保存・ダウンロード」、API は「JPEG 取得」のみ記載
  - 保存対象、保存タイミング、ファイル命名、削除トリガーが未定義
- 影響:
  - 実装により「毎回保存する/しない」が分かれ、容量要件との整合が崩れる
- 推奨:
  - `GET /snapshot`（取得専用）と `POST /api/snapshots`（保存専用）を分離、または単一仕様へ統一
  - 保存上限 500MB の削除ポリシー（FIFO/日時）を明記

### Medium 1: 可用性要件に対する運用設計が不足

- 根拠: `docs/SPECIFICATION.md:258`, `docs/SPECIFICATION.md:59`, `docs/SPECIFICATION.md:295`
- 問題:
  - 「常時稼働・再起動後自動復帰」はあるが、プロセス異常終了時の復旧戦略がない
- 推奨:
  - タスクスケジューラの再試行設定、監視、ログローテーション方針を追加
  - 可能なら Windows サービス化（NSSM など）を検討

### Medium 2: セキュリティが VPN 単層で、侵害時の防御が弱い

- 根拠: `docs/SPECIFICATION.md:11`, `docs/SPECIFICATION.md:225`, `docs/SPECIFICATION.md:234`
- 問題:
  - アプリ層の認証/監査が仕様にないため、Tailnet 参加済み端末からは無制限アクセスになる
- 推奨:
  - 最低限のアプリ認証（PIN/Basic/Auth token）とアクセスログ要件を追加

### Medium 3: 非機能要件の測定条件が不足

- 根拠: `docs/SPECIFICATION.md:252`, `docs/SPECIFICATION.md:256`
- 問題:
  - レイテンシ・CPU 要件に測定条件（PC スペック、回線、同時接続条件）がない
- 推奨:
  - 計測環境と合否判定手順（例: 5分平均、2クライアント同時）を追記

### Low 1: Phase 2 通知手段の例に陳腐化リスクがある

- 根拠: `docs/SPECIFICATION.md:92`
- 問題:
  - 「LINE Notify 等」の具体候補は提供状況の変化に影響される
- 推奨:
  - サービス名固定ではなく「Webhook 互換通知基盤」として要件化し、実装時に選定

## 優先修正順

1. API 契約（入力制約・エラー仕様）を明文化
2. スナップショットの保存/取得仕様を統一
3. 可用性（異常終了復旧）と測定条件を追加
4. 追加認証・監査ログ要件を定義

---

## 第2弾レビュー（更新版への追記）

## 評価サマリ

- 前回の主要指摘（API 契約、スナップショット仕様、可用性、セキュリティ多層化、測定条件）は概ね解消。
- 追加された「双方向音声」「トークン認証」「HTTPS 化」に伴い、新たな仕様ギャップが存在。

## Findings（第2弾・重大度順）

### High 1: HTTPS 前提と WebSocket 接続仕様が不整合

- 根拠: `docs/SPECIFICATION.md:214`, `docs/SPECIFICATION.md:569`, `docs/SPECIFICATION.md:666`
- 問題:
  - 音声 WebSocket 接続先が `ws://...` と定義されている一方で、仕様全体は HTTPS アクセスを推奨している
  - HTTPS ページから `ws://` は Mixed Content としてブロックされる
- 影響:
  - 音声機能（聞く/話す）が本番想定構成で動作不能になる可能性が高い
- 推奨:
  - `wss://` を正規仕様にする
  - HTTP 運用は「開発限定」と明示し、本番は HTTPS + WSS のみ許可する

### High 2: WebSocket の認証要件が未定義

- 根拠: `docs/SPECIFICATION.md:196`, `docs/SPECIFICATION.md:208`, `docs/SPECIFICATION.md:212`
- 問題:
  - HTTP API は認証要否が定義されているが、Socket.IO 接続時の認証方式・必須性が明文化されていない
- 影響:
  - 実装次第で未認証クライアントが音声 namespace に接続できるセキュリティ欠陥になりうる
- 推奨:
  - Socket.IO ハンドシェイク時に Bearer またはセッション検証を必須化
  - 認証失敗時の切断ルールとエラーイベントを仕様化

### Medium 1: セッション Cookie のセキュリティ属性が不足

- 根拠: `docs/SPECIFICATION.md:208`, `docs/SPECIFICATION.md:210`, `docs/SPECIFICATION.md:467`
- 問題:
  - Cookie の `HttpOnly` `Secure` `SameSite`、有効期限、再認証条件が未定義
- 影響:
  - セッション管理が実装者依存になり、盗用・固定化リスク評価ができない
- 推奨:
  - Cookie 属性と TTL（例: 24 時間）を仕様化
  - ログアウト時の無効化方針を明記

### Medium 2: `/api/auth` のブルートフォース対策が未定義

- 根拠: `docs/SPECIFICATION.md:208`, `docs/SPECIFICATION.md:251`, `docs/SPECIFICATION.md:259`
- 問題:
  - トークン検証 API が公開されるが、試行回数制限・遅延・ロックアウト要件がない
- 影響:
  - Tailnet 内の不正端末から総当たり試行を受ける余地が残る
- 推奨:
  - IP/セッション単位のレート制限（例: 5 回/5 分）を追加
  - 連続失敗時の一時ブロックと監査ログ強化を追加

### Medium 3: HTTPS 提供方式の実装詳細が不足

- 根拠: `docs/SPECIFICATION.md:569`, `docs/SPECIFICATION.md:616`, `docs/SPECIFICATION.md:665`
- 問題:
  - `tailscale cert` 利用は示されているが、証明書配置、Flask/WS の TLS 終端方法、更新運用が未定義
- 影響:
  - 実装で HTTPS が省略され、結果としてモバイルのマイク機能が利用不可になる可能性がある
- 推奨:
  - TLS 終端方式（Flask 直/TLS リバースプロキシ）を明記
  - 証明書更新手順（期限前更新、再起動要否）を運用手順化

### Low 1: スナップショット命名が秒単位で衝突する可能性

- 根拠: `docs/SPECIFICATION.md:400`
- 問題:
  - `snapshot_YYYYMMDD_HHmmss.jpg` は同一秒に複数保存時に重複しうる
- 影響:
  - 上書きまたは保存失敗でユーザー体験が不安定になる
- 推奨:
  - ミリ秒または連番を付与して一意性を保証する

## 第2弾 優先修正順

1. `wss://` への統一と WebSocket 認証要件の明文化
2. Cookie セキュリティ属性と `/api/auth` レート制限の定義
3. HTTPS（証明書運用含む）実装手順の詳細化
4. スナップショット命名の一意性保証

---

# SPECIFICATION レビュー結果（第3弾: Phase2設計）

## 対象

- レビュー対象: `docs/SPECIFICATION.md`
- レビュー範囲: Phase 2「飼い主表示モード（スマホ → PC 逆方向ストリーミング）」の設計

## 総評

- Phase2の目的、通信経路、UI、イベント設計が一貫しており、実装着手しやすい粒度まで具体化されています。
- 一方で「単一送信者制御」「常時トーク時の排他制御」「運用時の認証維持」に未定義があり、実装差・運用停止リスクが残ります。

## Findings（重大度順）

### High 1: 単一送信者（先勝ち）制御の状態遷移が未定義

- 根拠: `docs/SPECIFICATION.md:394`, `docs/SPECIFICATION.md:395`, `docs/SPECIFICATION.md:894`
- 問題:
  - 「1台のみ送信可」は定義されているが、送信権の取得/喪失条件が不足
  - `video_send_stop` が来ない異常終了（回線断・アプリ強制終了）時の解放条件が未定義
- 影響:
  - 送信権が取りっぱなしになり、他端末が送信開始できない
- 推奨:
  - サーバー側で `active_sender_sid` を管理し、`disconnect`/heartbeat timeout で強制解放
  - 拒否時に `video_status` だけでなく明示エラーコード（例: `SENDER_BUSY`）を返す

### High 2: `/video` の認可粒度が粗く、表示画面の乗っ取りリスクがある

- 根拠: `docs/SPECIFICATION.md:386`, `docs/SPECIFICATION.md:396`, `docs/SPECIFICATION.md:397`
- 問題:
  - 認証要件はあるが、送信者と表示端末の役割分離（認可）が定義されていない
  - 認証済み任意端末が `video_frame` 送信や `display_join` 可能に見える
- 影響:
  - 同一アカウント内の別端末や意図しない端末が表示内容を上書きしうる
- 推奨:
  - 役割（`sender` / `display`）をセッション属性またはトークンスコープで分離
  - `/display` 用端末の許可リストまたは固定デバイスIDを導入

### Medium 1: 「顔を見せる中は Listen 自動OFF」の強制仕様が不足

- 根拠: `docs/SPECIFICATION.md:893`, `docs/SPECIFICATION.md:1040`, `docs/SPECIFICATION.md:364`
- 問題:
  - 設計方針はあるが、どのレイヤーで強制するか（UIだけ/サーバー強制）が未定義
  - 複数クライアント時に、別端末の Listen をどう扱うかが不明
- 影響:
  - 実装差でハウリング防止が不完全になりうる
- 推奨:
  - サーバー側で `video_send_start` 受信時に Listen を制御し、`audio_listen_start` を条件付き拒否
  - 拒否時の理由コード（例: `LISTEN_BLOCKED_DURING_OWNER_VIDEO`）を規定

### Medium 2: Phase2運用時の認証維持（24時間TTL）と無人表示運用の整合が不明確

- 根拠: `docs/SPECIFICATION.md:313`, `docs/SPECIFICATION.md:325`, `docs/SPECIFICATION.md:258`
- 問題:
  - `/display` は認証必須だが、TTL 24時間超過時の再認証導線が未定義
  - ケージ横PCの常時表示運用とログイン維持方針が不足
- 影響:
  - 無人運用中にセッション失効で表示停止する可能性
- 推奨:
  - `/display` 専用の長期セッション/デバイス証明方式、または失効時の自動復帰手順を明記

### Medium 3: HTTPS利用方針に文書内不整合が残る

- 根拠: `docs/SPECIFICATION.md:741`, `docs/SPECIFICATION.md:825`, `docs/SPECIFICATION.md:868`
- 問題:
  - アクセス手順に `http://100.x.x.x:5555` が残っており、他節の「本番はHTTPS必須」と矛盾
- 影響:
  - 実運用でHTTPアクセスが混入し、ブラウザ機能制限や接続不具合の原因になる
- 推奨:
  - 手順を `https://<machine>.<tailnet>.ts.net:5555` に統一し、HTTPは開発限定と明記

### Low 1: `video_frame` の受信上限・防御要件が不足

- 根拠: `docs/SPECIFICATION.md:392`, `docs/SPECIFICATION.md:405`, `docs/SPECIFICATION.md:406`
- 問題:
  - フレームサイズ目安はあるが、最大許容サイズ/送信レート超過時の制御が未定義
- 影響:
  - 実装次第でメモリ圧迫・遅延増大が発生しうる
- 推奨:
  - 1フレーム上限（例: 200KB）と最大FPS超過時のドロップ方針を規定

## 第3弾 優先修正順（Phase2）

1. 単一送信者制御の状態遷移（取得・解放・タイムアウト・拒否コード）を仕様化
2. `/video` の認可モデル（sender/display役割分離）を追加
3. 常時トーク時の Listen 強制制御をサーバー仕様として明記
4. `/display` の無人運用を想定した認証維持方式を定義
5. HTTP/HTTPS 手順の記述を統一

---

## 第4弾レビュー（リカバリプラン追加）

## 評価サマリ

- 追加されたリカバリプランは、障害分類から復旧シナリオまで具体的で、運用設計として前進しています。
- 一方で、目標要件と例外シナリオの矛盾、セッション方針の不整合、復旧失敗時の扱い未定義が残っています。

## Findings（第4弾・重大度順）

### High 1: 「手動操作なしで復旧」と復旧不可シナリオが矛盾している

- 根拠: `docs/SPECIFICATION.md:851`, `docs/SPECIFICATION.md:1066`
- 問題:
  - 章冒頭で「あらゆる障害を手動操作なしで復旧」と定義している一方、シナリオFで「ブラウザクラッシュ時は手動再起動が必要」としている
- 影響:
  - 非機能要件の判定基準が曖昧になり、テスト合否や運用期待値が一致しない
- 推奨:
  - 「自動復旧対象の障害範囲」を明示し、手動介入が必要な例外を要件として明確化

### High 2: セッションTTL方針が章間で不整合

- 根拠: `docs/SPECIFICATION.md:325`, `docs/SPECIFICATION.md:1016`, `docs/SPECIFICATION.md:1017`
- 問題:
  - Cookie仕様ではTTL 24時間だが、リカバリ章で`/display`は30日TTL + 自動延長と記載されている
  - 同一Cookieで実現するのか、`/display`専用セッションを分離するのかが未定義
- 影響:
  - 実装時に認証切れ挙動が揺れ、無人表示運用が想定どおり動かない
- 推奨:
  - セッション種別（メイン/ディスプレイ専用）を分離し、Cookie名・TTL・更新条件を明記

### Medium 1: 再接続後の状態復旧で競合時の失敗動作が未定義

- 根拠: `docs/SPECIFICATION.md:894`, `docs/SPECIFICATION.md:898`, `docs/SPECIFICATION.md:1184`
- 問題:
  - `audio_talk_start`/`video_send_start`再送時に、他クライアント先勝ちだった場合の再試行方針がない
- 影響:
  - 復旧時に沈黙失敗（復帰したように見えて実際は未復旧）が起きる
- 推奨:
  - `*_start`失敗時のエラーコード、再試行間隔、UI表示を定義

### Medium 2: グローバル例外ハンドリングの記述が過度に楽観的

- 根拠: `docs/SPECIFICATION.md:861`, `docs/SPECIFICATION.md:949`, `docs/SPECIFICATION.md:951`
- 問題:
  - 「全ハンドラtry-catch」「`@app.errorhandler(500)`」だけでスレッド例外や非同期例外を網羅できる記述になっている
  - Python文脈では `try-except` が正確な用語
- 影響:
  - 実装が仕様どおりでも未捕捉例外が残り、復旧保証を満たせない可能性
- 推奨:
  - 例外捕捉責務をレイヤー別に定義（HTTPハンドラ/Socket.IOイベント/バックグラウンドスレッド）
  - ログ出力・再起動トリガー条件を明文化

### Low 1: 章番号・節参照の整合が崩れている

- 根拠: `docs/SPECIFICATION.md:1087`, `docs/SPECIFICATION.md:1089`, `docs/SPECIFICATION.md:1101`
- 問題:
  - `## 12. 双方向音声の技術設計` 配下の小見出しが `### 11.x` のまま残っている
- 影響:
  - 参照先の混乱を招き、レビュー・実装時に誤読が発生しやすい
- 推奨:
  - 章番号を一括で正規化し、文中の節参照も再点検

## 第4弾 優先修正順（リカバリ）

1. 自動復旧対象と手動介入対象の境界を明文化
2. セッション方針（24h/30d）の統合設計を確定
3. 再接続後の競合失敗時フロー（再試行・通知）を仕様化
4. 例外ハンドリング責務のレイヤー分離
5. 章番号・参照番号の整合修正

---

## 第5弾レビュー（仕様書 + E2E テスト仕様書 + ソースコード照合）

## 評価サマリ

- 仕様書・E2E テスト仕様書ともに粒度は高く、運用シナリオまで踏み込めています。
- ただし、実装照合の結果、音声排他制御に重大な抜け穴があり、加えてセッション要件・セキュリティ前提・テスト観測点に不整合が残っています。

## Findings（第5弾・重大度順）

### High 1: `audio_talk` がトーク権限を検証せず、排他制御を迂回できる

- 根拠: `server/app.py:484`, `server/app.py:492`, `server/app.py:523`, `server/app.py:531`
- 問題:
  - 送話スロットの取得チェックは `audio_talk_start` のみ
  - 実際の音声データ受信 `audio_talk` 側で `request.sid == _talking_sid` の検証がない
- 影響:
  - スロット未取得/排他ブロック中クライアントでも `audio_talk` を直接送るとスピーカー再生されうる
  - 同時送話・ノイズ混在・排他仕様逸脱を引き起こす
- 推奨:
  - `audio_talk` で `request.sid` と `_talking_sid` を厳密照合し、不一致は破棄・ログ記録
  - 必要なら不正送信のレート制限を追加

### High 2: 非トーカー切断でトークスロットが誤解放される

- 根拠: `server/app.py:432`, `server/app.py:434`, `server/audio.py:180`, `docs/E2E_TEST_SPEC.md:716`
- 問題:
  - `audio_disconnect()` が切断 SID に関係なく `release_talk()` を呼ぶ
  - E2E 仕様書の既知リスク記述は「正確にクリーンアップされる」としており、実装実態と逆
- 影響:
  - トーク中でないクライアントの切断を契機にトークスロットが空き扱いになり、同時送話が発生しうる
- 推奨:
  - `release_talk()` は `sid == _talking_sid` の場合のみ実行
  - この不具合を再現する回帰テスト（トーカーA + リスナーB切断 + Cが送話開始）をE2Eへ追加

### High 3: `/display` の 30日TTL + 自動延長仕様が未実装（24時間固定）

- 根拠: `docs/SPECIFICATION.md:380`, `docs/SPECIFICATION.md:399`, `docs/SPECIFICATION.md:412`, `server/auth.py:91`, `server/config.py:11`, `server/config.py:38`
- 問題:
  - 仕様は `/display` 長期セッション（30日 + heartbeat延長）を要求
  - 実装は `SESSION_TTL_SECONDS`（24時間）のみで判定し、`DISPLAY_SESSION_TTL_SECONDS` は未使用
- 影響:
  - 無人表示運用の想定に反して 24 時間で失効し、運用停止リスクが残る
- 推奨:
  - セッション種別（通常/`/display`）を分離し TTL を実装
  - 自動延長は HTTP keepalive エンドポイント等で明示実装し、Socket.IO だけに依存しない

### High 4: セキュリティ前提（Tailscale限定・本番HTTPS必須）と起動実装が乖離

- 根拠: `docs/SPECIFICATION.md:839`, `docs/SPECIFICATION.md:1182`, `server/config.py:16`, `server/app.py:731`, `server/app.py:734`
- 問題:
  - 仕様は Tailscale IP 限定バインドを要求するが、実装既定値は `0.0.0.0`
  - 本番で証明書が無い場合も HTTP 起動を許容している
- 影響:
  - 意図しないネットワーク露出の可能性
  - HTTPS 前提機能（マイク等）や運用要件との不整合
- 推奨:
  - 本番は「証明書未配置なら起動失敗（fail fast）」に変更
  - `HOST` を明示設定必須にし、Tailscale IP 以外を拒否するガードを導入

### Medium 1: 「顔を見せる」中の音声挙動が仕様書内で矛盾

- 根拠: `docs/SPECIFICATION.md:497`, `docs/SPECIFICATION.md:1344`, `docs/SPECIFICATION.md:1397`, `static/js/app.js:36`, `static/js/app.js:335`, `static/js/audio.js:229`
- 問題:
  - 同一スマホで3機能同時利用可（自動制御なし）と、Talkボタン無効化/Listen自動OFFが混在
  - 実装は「無効化しない・自動OFFしない」側
- 影響:
  - 実装/テストの正解条件がぶれ、今後の改修で回帰を生みやすい
- 推奨:
  - どちらかの方針に統一し、競合記述を削除
  - E2E 期待結果とUI仕様を同じ方針で再同期

### Medium 2: E2E テストの観測項目が実装 API 形式と不一致

- 根拠: `docs/E2E_TEST_SPEC.md:341`, `server/app.py:219`, `server/app.py:222`
- 問題:
  - E2E は `/api/status` に `listening_clients` 直下フィールドがある前提
  - 実装は `audio.listening_clients` 配下
- 影響:
  - 手順どおりに実施しても誤判定（偽失敗）になりうる
- 推奨:
  - E2E 仕様の参照パスを `audio.listening_clients` に修正

## 第5弾 優先修正順（仕様 + テスト + 実装）

1. 音声送話の認可チェック修正（`audio_talk` SID検証 + 切断時の誤解放修正）
2. `/display` 長期セッション（30日 + 延長）を仕様どおり実装
3. 本番起動時のセキュリティガード（HTTPS必須・バインド制限）を強制
4. 「顔を見せる」中の音声仕様を一本化し、仕様書とE2Eを再同期
5. E2E の API 観測パスと回帰ケース（排他破綻再現）を更新
