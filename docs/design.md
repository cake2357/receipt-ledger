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
`categories(id,name UNIQUE,description)`：分類名と説明を保存・画面表示する。PaddleOCRには渡さず、OCR後の分類は商品名の完全一致ルールを使用する。
`receipts(id,status,body,image,hash UNIQUE,raw,warnings)`：bodyはPydanticで検証した下書きJSON。円はfloatでなくStrictInt。NULL/空文字で不明を表現。imageはアプリ生成SHA256名のみ。
`entries(receipt_id,line,category_id,amount INTEGER CHECK(typeof(amount)='integer'))`：確定時に原子的に作られる整数円台帳。再編集では原子的に削除。
`rules(name PRIMARY KEY,category_id)`：確定時に学習する完全一致ルール。最後に確定した分類を採用。
`drive_files(file_id PRIMARY KEY,receipt_id)`：同一内容の複数Drive IDも一つのレシートに対応する。
`settings(key,value)`：現在の設定はDriveフォルダID。旧OCR同意フラグは読込時に無視し、次回設定保存時には書き出さない。APIキーは保存しない。
`ocr_runs(id,receipt_id,created_at,raw)`：認識結果を取得・検証できた場合に原文、座標、信頼指標を履歴保存する。下書き解析に失敗しても原文は残る。画像なし・確定済みの拒否、認識失敗、タイムアウトでは新しい履歴を作らない。旧OCRの履歴は保持する。

## PaddleOCRの処理

1. 画像付き下書きに対する POST `/api/receipts/{id}/ocr/local` で実行する。確定済みは409で拒否する。
2. `local_ocr.py` が保存画像の名前・保存先・シンボリックリンクを検証し、サーバーと同じPythonで `paddle_ocr_worker.py` を別プロセスとして起動する。shellは使用しない。初回モデル取得を含め300秒で打ち切る。
3. ワーカーは `PaddleOCR(lang='japan', ocr_version='PP-OCRv5', device='cpu')` を使用。文書の向き分類・歪み補正・文字行の向き分類とMKL-DNNは無効。画素座標の四角形を保持し、画像サイズで正規化した位置・大きさ・傾きを解析用に返す。
4. モデルキャッシュはプロジェクトの `artifacts/paddleocr-cache/`。`LEDGER_DATA_DIR` を変更してもこの場所は変わらない。モデル取得先の事前チェックは無効化しているが、未取得モデルのダウンロードにはネット接続が必要。
5. 認識原文を `receipts.raw` と `ocr_runs.raw` に保存した後、文字と座標から下書きを解析する。成功時は入力中の下書きを置き換え、確認を解除する。税込明細額はnull、税率は未選択で、人による修正・確認を要求する。

認識失敗・タイムアウトは503、原文保存後の下書き解析失敗は422。導入状態は `GET /api/settings` の `local_ocr` で返し、パッケージの検出だけで判定する。モデル取得・認識成功を保証しない。旧 POST `/api/receipts/{id}/ocr` は廃止済み（404）。運用手順は[READMEのPaddleOCR節](../README.md#paddleocr無料端末内で処理)を参照。

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
Driveページング、ダウンロード、OAuth範囲をモック契約試験で確認。実アカウントOAuth・Driveは未接続。PaddleOCRの認識は生成した日本語画像を使用する実OCRブラウザ試験で確認し、座標変換・下書き解析・履歴保存・失敗時の挙動は単体/API試験で確認する。過去の検証結果は[検証記録](verification.md)を参照。
- Google Drive files.list: https://developers.google.com/drive/api/reference/rest/v3/files/list
- Google Desktop OAuth: https://developers.google.com/identity/protocols/oauth2/native-app

## テスト方針
縦方向のRED→GREENを、手入力確定→分類/集計/出力→画像/保護→外部adapter→UI→整数永続化→OAuth→ブラウザ→堅牢化の順に実施。pytest TestClientでDBを実際に書き、外部のみMockTransport/adapter差し替え。Playwrightは実uvicorn＋使い捨てデータ領域で実行。課金APIを呼ばず、画像fixtureはテスト内で生成する。
