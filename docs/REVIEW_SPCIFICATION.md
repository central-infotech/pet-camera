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
