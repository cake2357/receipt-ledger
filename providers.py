"""Google Drive import; OCR is implemented locally in local_ocr.py."""
import re
from contextlib import nullcontext
import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field
from media import LIMIT, ingest

SCOPE='https://www.googleapis.com/auth/drive.readonly'

def drive_files(folder,token,client=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]+',folder): raise ValueError('フォルダIDが不正です')
    with nullcontext(client) if client else httpx.Client(timeout=60) as c:
        page=None; seen=set()
        while True:
            params={'q':f"'{folder}' in parents and trashed = false",'fields':'nextPageToken,files(id,name,mimeType,size)','pageSize':100,'supportsAllDrives':'true','includeItemsFromAllDrives':'true'}
            if page: params['pageToken']=page
            r=c.get('https://www.googleapis.com/drive/v3/files',params=params,headers={'Authorization':'Bearer '+token}); r.raise_for_status(); data=r.json()
            yield from data.get('files',[])
            page=data.get('nextPageToken')
            if not page: break
            if page in seen: raise ValueError('Driveページトークンが循環しています')
            seen.add(page)

def drive_download(file_id,token,client=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]+',file_id): raise ValueError('ファイルIDが不正です')
    with nullcontext(client) if client else httpx.Client(timeout=60) as c:
        with c.stream('GET',f'https://www.googleapis.com/drive/v3/files/{file_id}',params={'alt':'media','supportsAllDrives':'true'},headers={'Authorization':'Bearer '+token}) as r:
            r.raise_for_status(); data=bytearray()
            for chunk in r.iter_bytes():
                data.extend(chunk)
                if len(data)>LIMIT: raise ValueError('画像が12MBを超えています')
            return bytes(data)

def google_token(root):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    path=root/'google-token.json'
    if not path.exists(): raise ValueError('READMEの Google OAuth 設定後 uv run python oauth_setup.py を実行してください')
    creds=Credentials.from_authorized_user_file(str(path),scopes=[SCOPE])
    if not creds.valid:
        creds.refresh(Request()); path.write_text(creds.to_json()); path.chmod(0o600)
    return creds.token

class Settings(BaseModel):
    drive_folder: str = Field(default='',pattern=r'^[A-Za-z0-9_-]*$',max_length=200)

def install_providers(app,store):
    def setting():
        with store.db() as db: row=db.execute("SELECT value FROM settings WHERE key='preferences'").fetchone()
        return Settings.model_validate_json(row[0]) if row else Settings()
    @app.get('/api/settings')
    def status():
        from local_ocr import availability
        return {**setting().model_dump(), 'local_ocr': availability(),
                'google_authorized': (store.root/'google-token.json').exists(),
                'instructions': ['Drive: 自分専用のデスクトップOAuth JSONを data/google-client.json に置き、uv run python oauth_setup.py を実行。フォルダIDを保存。']}
    @app.put('/api/settings')
    def save_settings(body:Settings):
        with store.db() as db: db.execute("INSERT OR REPLACE INTO settings VALUES('preferences',?)",(body.model_dump_json(),))
        return status()
    @app.post('/api/drive/import')
    def import_drive():
        s=setting()
        if not s.drive_folder: raise HTTPException(409,'設定画面にDriveフォルダIDを保存してください')
        try: token=google_token(store.root)
        except Exception: raise HTTPException(409,'Google認証が必要です。READMEのOAuth設定を実行してください')
        imported=0; skipped=0; errors=[]
        try:
            for f in drive_files(s.drive_folder,token):
                if f.get('mimeType') not in {'image/jpeg','image/png','image/heic','image/heif'}: skipped+=1; continue
                with store.db() as db:
                    if db.execute('SELECT 1 FROM drive_files WHERE file_id=?',(f['id'],)).fetchone(): skipped+=1; continue
                    before=db.execute('SELECT count(*) FROM receipts').fetchone()[0]
                try:
                    ingest(store,drive_download(f['id'],token),f['mimeType'],f['id'])
                    with store.db() as db: after=db.execute('SELECT count(*) FROM receipts').fetchone()[0]
                    imported+=after-before; skipped+=int(after==before)
                except Exception: errors.append({'file_id':f['id'],'error':'取得・画像検証失敗（12MB上限）。再実行できます'})
        except Exception: raise HTTPException(502,'Drive一覧取得失敗。取り込み済み分は保持します。認証・権限・フォルダを確認してください')
        return {'imported':imported,'skipped':skipped,'errors':errors}
