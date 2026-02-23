# WEBRTC_AIORTC_SPEC レビュー結果

## 対象

- レビュー対象: `docs/WEBRTC_AIORTC_SPEC.md`
- 照合対象コード: `server/app.py`, `static/js/app.js`, `templates/index.html`

## ストリーミングアップグレードプラン一覧

1. MJPEG（現状維持）
2. HLS / LL-HLS
3. WebRTC
4. MSE + fMP4（WebSocket）
5. WebCodecs API
6. WebTransport

- 採用決定: **3. WebRTC（aiortc）**

## 総評

- 仕様書は、aiortc 採用理由・構成・段階導入の記述が具体的で、実装着手できる粒度です。
- 一方で、接続ライフサイクルと再接続ロジックに不整合があり、このまま実装すると長時間運用で接続枯渇や再接続ループが起きるリスクがあります。

## Findings（重大度順）

### High 1: `disconnected` 放置により PeerConnection が残留し、接続枯渇する

- 根拠: `docs/WEBRTC_AIORTC_SPEC.md:279`, `docs/WEBRTC_AIORTC_SPEC.md:881`, `docs/WEBRTC_AIORTC_SPEC.md:929`
- 問題:
  - クリーンアップ条件が `failed/closed` のみで、`disconnected` の長時間滞留ケースが未処理
  - `WEBRTC_MAX_PEERS` 判定は残留接続数に依存するため、ゾンビ接続で 429 が出やすくなる
- 影響:
  - スマホ復帰・回線揺れ後に新規接続不能
  - 長時間運用で再起動しないと回復しない状態が発生
- 推奨:
  - `disconnected` タイムアウト（例: 15〜30秒）後の強制クリーンアップを仕様化
  - `iceconnectionstatechange` も監視対象に追加して片系切断を早期検知

### High 2: 意図的な `close()` でも再接続が走る設計で、ループ・誤再接続を起こす

- 根拠: `docs/WEBRTC_AIORTC_SPEC.md:488`, `docs/WEBRTC_AIORTC_SPEC.md:587`, `docs/WEBRTC_AIORTC_SPEC.md:905`
- 問題:
  - `pc.close()` による `closed` 遷移でも `_scheduleRetry()` が発火する
  - `beforeunload` で `close()` を呼んでも再接続タイマーが残る設計
- 影響:
  - ページ離脱時に不要な offer 再送・ログ汚染
  - サーバー側に短命接続が増え、運用診断が困難
- 推奨:
  - 手動切断フラグ（例: `_isClosing`）を導入し、`closed` 時の再接続を抑止
  - 予約済み retry タイマーを `close()` で明示キャンセル

### High 3: `threading` Flask と `asyncio` ループ間の共有状態が非同期安全でない

- 根拠: `docs/WEBRTC_AIORTC_SPEC.md:167`, `docs/WEBRTC_AIORTC_SPEC.md:300`, `docs/WEBRTC_AIORTC_SPEC.md:397`, `docs/WEBRTC_AIORTC_SPEC.md:929`
- 問題:
  - `_peer_connections` を Flask 側と asyncio 側で直接参照・更新
  - `app.py` から `webrtc._loop` / `webrtc._cleanup_pc` / `webrtc._peer_connections` の私有メンバに直接依存
- 影響:
  - レース条件による接続数判定ブレ、将来的な保守性低下
  - 実装時にスレッド境界の不具合が混入しやすい
- 推奨:
  - `webrtc.py` に公開 API（`count_peers()`, `close_peer(pc_id)` など）を定義
  - 共有状態の参照更新はすべて asyncio ループ内に集約

### Medium 1: フォールバック後の再試行ポリシーが本文とコード例で矛盾

- 根拠: `docs/WEBRTC_AIORTC_SPEC.md:750`, `docs/WEBRTC_AIORTC_SPEC.md:571`
- 問題:
  - 本文では「MJPEG フォールバック後 30 秒で再試行」とあるが、提示コードは最大試行到達後に再試行を止める
- 影響:
  - 一時障害からの自動復帰期待と挙動が一致しない
- 推奨:
  - 「停止」か「30秒周期再試行」かを一本化し、状態遷移図を追加

### Medium 2: 既存 UI 置換の影響範囲が不足し、実装漏れを誘発

- 根拠: `docs/WEBRTC_AIORTC_SPEC.md:699`, `docs/WEBRTC_AIORTC_SPEC.md:703`, `static/js/app.js:42`, `static/js/app.js:177`, `templates/index.html:43`
- 問題:
  - `video-stream` の置換方針はあるが、既存参照箇所の網羅リストがない
  - 設定適用後リロード、オーバーレイ制御、ステータス表示の全更新点が明示されていない
- 影響:
  - 実装者差で null 参照や表示不整合が発生しやすい
- 推奨:
  - 変更対象セレクタ・関数のチェックリストを仕様に追加（`videoStream`, `checkVideoLoaded`, 設定適用後処理など）

### Low 1: `DELETE /api/webrtc/<pc_id>` の所有者検証が未定義

- 根拠: `docs/WEBRTC_AIORTC_SPEC.md:393`, `docs/WEBRTC_AIORTC_SPEC.md:526`
- 問題:
  - 認証済みであれば、同一ユーザー内の別タブ接続を任意に閉じられる仕様
- 影響:
  - マルチ端末利用時に意図しない切断を起こす可能性
- 推奨:
  - `pc_id` とセッション（またはクライアント識別子）を紐付け、所有者のみ切断許可

## 優先修正順

1. `disconnected` 残留対策と接続クリーンアップ条件の拡張
2. `close()` 時の再接続抑止（クライアント状態機械の修正）
3. `webrtc.py` 公開 API 化とスレッド境界の整理
4. フォールバック再試行ポリシーの統一
5. UI 変更点チェックリストの明文化

---

## 第2弾レビュー（更新版への追記）

## 評価サマリ

- 前回の主要指摘は概ね解消されています（`disconnected` タイムアウト、`close()` 時の再接続抑止、公開 API 化、所有者検証、UI 変更チェックリスト）。
- 追加された「実装によって起こりうるバグとその対策」は有用ですが、いくつかは本文コードとの整合が取れておらず、実装時に抜け漏れが出るリスクが残っています。

## Findings（第2弾・重大度順）

### High 1: 接続上限チェックが TOCTOU で、同時 offer で上限超過しうる

- 根拠: `docs/WEBRTC_AIORTC_SPEC.md:456`, `docs/WEBRTC_AIORTC_SPEC.md:470`, `docs/WEBRTC_AIORTC_SPEC.md:1191`
- 問題:
  - `webrtc.peer_count()` による上限判定が Flask スレッド側で先行し、その後に非同期で接続作成される
  - 同時リクエスト時に複数 offer が上限判定を通過し、`WEBRTC_MAX_PEERS` を超えて作成されうる
- 影響:
  - DoS 対策としての接続上限が実効的でなくなる
  - 高負荷時に CPU/メモリ見積もりが崩れる
- 推奨:
  - 上限判定と接続登録を `webrtc.py` の asyncio ループ内で原子的に実行
  - 例: `handle_offer()` 内で `if len(_peer_connections) >= MAX: raise` を先に実施し、通過時のみ `pc_id` を登録

### Medium 1: Bug 1 の対策と `main()` 例が矛盾している

- 根拠: `docs/WEBRTC_AIORTC_SPEC.md:499`, `docs/WEBRTC_AIORTC_SPEC.md:502`, `docs/WEBRTC_AIORTC_SPEC.md:1313`
- 問題:
  - Bug 1 対策では「`webrtc.start()` を最初に初期化」と明記
  - 一方で `main()` 例は `camera/audio` の後に `webrtc.start()` を呼んでいる
- 影響:
  - 実装者がどちらを正とすべきか判断できず、起動順序の再現性が下がる
- 推奨:
  - `main()` のサンプル順序を対策記述に合わせて統一

### Medium 2: Bug 10 の `keepalive` 対策が主コード例に反映されていない

- 根拠: `docs/WEBRTC_AIORTC_SPEC.md:754`, `docs/WEBRTC_AIORTC_SPEC.md:1451`
- 問題:
  - Bug 10 では `fetch(..., { keepalive: true })` を推奨
  - 主要実装例の `_internalClose()` は `keepalive` なしのまま
- 影響:
  - ページ離脱時に DELETE が落ちるケースで、仕様どおりの対策が実装されない可能性
- 推奨:
  - 7.1 の本体コード例を `keepalive: true` に揃える

### Medium 3: 解像度変更時の `_source_track` リセットが設計に接続されていない

- 根拠: `docs/WEBRTC_AIORTC_SPEC.md:893`, `docs/WEBRTC_AIORTC_SPEC.md:1394`
- 問題:
  - Bug 7 で `reset_source_track()` が必要と定義されている
  - ただし `/api/settings` 更新フローでの呼び出し箇所が仕様化されていない
- 影響:
  - 実装者が呼び出しを忘れると、解像度変更後の映像乱れ対策が機能しない
- 推奨:
  - `server/app.py` の `PATCH /api/settings` 成功時に `webrtc.reset_source_track()` を呼ぶ手順を明記
  - 併せて Step 5 またはテスト項目に「解像度変更後の source_track 再生成確認」を追加

## 第2弾 優先修正順

1. 接続上限チェックを asyncio ループ内で原子的に実施
2. `main()` 起動順序の記述を一本化
3. `_internalClose()` の DELETE に `keepalive: true` を反映
4. `reset_source_track()` の呼び出し経路を `/api/settings` に明記
