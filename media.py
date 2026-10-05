import hashlib
import io
import warnings
from urllib.parse import urlsplit
from PIL import Image, ImageOps
import pillow_heif
from fastapi import HTTPException, UploadFile
from fastapi.responses import JSONResponse, FileResponse
pillow_heif.register_heif_opener()
LIMIT=12*1024*1024
Image.MAX_IMAGE_PIXELS=25000000

def ingest(store,data,mime,drive_id=None):
    if len(data)>LIMIT: raise HTTPException(413,'画像は12MB以内にしてください')
    if mime not in {'image/jpeg','image/png','image/heic','image/heif'}: raise HTTPException(415,'JPEG / PNG / HEIC のみ対応')
    digest=hashlib.sha256(data).hexdigest()
    with store.db() as db:
        if drive_id:
            old=db.execute('SELECT receipt_id FROM drive_files WHERE file_id=?',(drive_id,)).fetchone()
            if old: return store.receipt(old[0])
        old=db.execute('SELECT id FROM receipts WHERE hash=?',(digest,)).fetchone()
        if old: rid=old[0]
        else:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('error',Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(data)) as source:
                        # iPhone HDR JPEGs may be detected as MPO; use primary image only.
                        if source.format not in {'JPEG','MPO','PNG','HEIF'}: raise ValueError('format')
                        source.seek(0)
                        image=ImageOps.exif_transpose(source).convert('RGB'); image.thumbnail((3000,3000))
                        output=io.BytesIO(); image.save(output,format='JPEG',quality=92)
            except Exception: raise HTTPException(415,'画像が読めません。形式・破損・画素数を確認してください')
            folder=store.root/'images'; folder.mkdir(exist_ok=True)
            name=digest+'.jpg'; (folder/name).write_bytes(output.getvalue())
            from ledger import Review
            rid=db.execute('INSERT INTO receipts(body,image,hash) VALUES(?,?,?)',(Review().model_dump_json(),name,digest)).lastrowid
        if drive_id: db.execute('INSERT INTO drive_files VALUES(?,?)',(drive_id,rid))
    return store.receipt(rid)

def install_media(app,store):
    @app.middleware('http')
    async def guard(request,call_next):
        host=request.headers.get('host','')
        try:
            parsed=urlsplit('http://'+host)
            allowed=parsed.hostname in {'127.0.0.1','localhost','::1'} and not parsed.username and parsed.path==''
            port=parsed.port or 80
        except ValueError: allowed=False
        if not allowed: return JSONResponse({'detail':'localhost のみ利用できます'},status_code=403)
        if request.method not in {'GET','HEAD','OPTIONS'}:
            origin=request.headers.get('origin')
            if origin != f'http://{host}': return JSONResponse({'detail':'同一 Origin が必要です'},status_code=403)
            if request.headers.get('sec-fetch-site')=='cross-site': return JSONResponse({'detail':'cross-site 拒否'},status_code=403)
        length=request.headers.get('content-length')
        try:
            if length and int(length)>LIMIT+65536: return JSONResponse({'detail':'12MB 上限です'},status_code=413)
        except ValueError: return JSONResponse({'detail':'Content-Length が不正です'},status_code=400)
        if request.method not in {'GET','HEAD','OPTIONS'}:
            chunks=[]; size=0
            async for chunk in request.stream():
                size+=len(chunk)
                if size>LIMIT+65536: return JSONResponse({'detail':'12MB 上限です'},status_code=413)
                chunks.append(chunk)
            request._body=b''.join(chunks)
        response=await call_next(request)
        response.headers.update({'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'"})
        return response
    @app.post('/api/upload')
    async def upload(file:UploadFile):
        data=await file.read(LIMIT+1)
        return ingest(store,data,file.content_type)
    @app.get('/api/receipts/{rid}/image')
    def image(rid:int):
        r=store.receipt(rid)
        if not r['image']: raise HTTPException(404,'画像なし')
        return FileResponse(store.root/'images'/r['image'],media_type='image/jpeg')
