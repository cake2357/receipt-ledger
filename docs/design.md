# 基本・詳細設計

## 構成
ブラウザ（HTML/CSS/vanilla JavaScript）→ FastAPI → SQLite / images。
外部接続は手動操作のGoogle Drive read-onlyとPaddleOCRの初回モデル取得。OCR画像の処理は端末内。サーバーは単一worker、RLockでDB操作・画像取り込み・バックアップを直列化する。大規模運用ではジョブキュー/ページング/別ロック設計が必要。

- `ledger.py`: データモデル、下書き/確定/再編集、分類、集計、CSV、バックアップ
- `media.py`: Host/Origin・本文容量検査、画像の検証/変換、SHA-256重複検出
- `local_ocr.py` / `paddle_ocr_worker.py`: PaddleOCRローカル日本語OCR、初回モデル取得とキャッシュ、座標による行復元、保守的な下書き解析。画像の外部送信なし。内部画像パス検証、実行timeout、完全一致分類、監査保存。
- `providers.py`: Drive RESTのHTTP adapter、設定、Drive取り込み
- `oauth_setup.py`: Desktop OAuth、PKCE、127.0.0.1 ephemeral callback、read-only scope
- `server.py`: .env読み込み、localhost固定bind、umask 077
- `static/`: 日本語画面、DOMノード生成、外部CDNなし

## データモデル
`categories(id,name UNIQUE,description)`：分類の説明をAI入力に含める。
`receipts(id,status,body,image,hash UNIQUE,raw,warnings)`：bodyはPydanticで検証した下書きJSON。円はfloatでなくStrictInt。NULL/空文字で不明を表現。imageはアプリ生成SHA256名のみ。
`entries(receipt_id,line,category_id,amount INTEGER CHECK(typeof(amount)='integer'))`：確定時に原子的に作られる整数円台帳。再編集では原子的に削除。
`rules(name PRIMARY KEY,category_id)`：確定時に学習する完全一致ルール。最後に確定した分類を採用。
`drive_files(file_id PRIMARY KEY,receipt_id)`：同一内容の複数Drive IDも一つのレシートに対応する。
`settings(key,value)`：同意フラグとフォルダIDのみ。APIキーは保存しない。
`ocr_runs(id,receipt_id,created_at,raw)`：成功/不完全/拒否応答を全て監査保存。HTTP通信自体が失敗した場合は応答JSONを取得できないため記録不可。

## 状態遷移
手入力/画像/Drive → draft → OCR（任意・常にdraft）→ 編集保存 → 確定検証 → confirmed。
confirmedは直接保存/OCRを拒否し、reopen → draftを要求。reopenでは確認チェックを解除、再確定するまで集計に含めない。
OCR税別/不確実 → 税抜額/数量/印字総額/税率保持＋税込額null＋警告 → 手入力修正または配賦案→明示適用→配賦承認＋確認 → 合計検証 → confirmed。

配賦は `largest-remainder-v1`。割引は税抜額、税は割引後額を重みとし、整数商と剰余だけで配分する。剰余同順位は明細順。`pre_tax` は書き換えず `allocated_discount` / `allocated_tax` / `amount_source=calculated` を別保存。小計を入力した場合は割引前額−割引と一致検証。`tax_rates` が[0]/[8]/[10]以外は拒否。これは店舗の税計算の再現ではない。確定時にも全配賦を再計算して改変を検査する。

## API
- GET/POST `/api/receipts`、GET/PUT `/api/receipts/{id}`
- POST `/api/receipts/{id}/confirm`、`/reopen`、`/ocr/local`（PaddleOCR・APIキー不要）
- POST `/api/receipts/{id}/allocation-preview`（書込なしの案）、`/allocate`（下書きへ明示適用）
- GET `/api/receipts/{id}/image`
- POST `/api/upload`（multipart、file）
- GET/POST `/api/categories`、PUT `/api/categories/{id}`
- GET/PUT `/api/settings`、POST `/api/drive/import`
- GET `/api/dashboard?month=YYYY-MM`、`/api/export.csv?month=YYYY-MM`、`/api/backup`
書き込みは `Origin: http://127.0.0.1:8765` 等の正確な同一Originが必要。

## バックアップと復元
処理中ロックで画像追加・DB更新を止め、SQLite backup APIで一時DBへスナップショット後、画像とZIP化。秘密ファイルは含めない。復元はサーバー停止中に信頼できるバックアップからDB/imagesをdataに置く。アプリ内の任意ZIP展開エンドポイントは作らない。

## 外部仕様の参照と検証範囲
実装時に以下公式資料を取得・確認。HTTPリクエスト形状、JSON schema、Driveページング、ダウンロード、OAuth範囲をモック契約試験で確認。実アカウントOAuth・Driveは未接続。
- Google Drive files.list: https://developers.google.com/drive/api/reference/rest/v3/files/list
- Google Desktop OAuth: https://developers.google.com/identity/protocols/oauth2/native-app

## テスト方針
縦方向のRED→GREENを、手入力確定→分類/集計/出力→画像/保護→外部adapter→UI→整数永続化→OAuth→ブラウザ→堅牢化の順に実施。pytest TestClientでDBを実際に書き、外部のみMockTransport/adapter差し替え。Playwrightは実uvicorn＋使い捨てデータ領域で実行。課金APIを呼ばず、画像fixtureはテスト内で生成する。
