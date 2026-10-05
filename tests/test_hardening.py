import io, json, zipfile, sqlite3
import httpx
from PIL import Image
from test_app import client
from test_upload import png

def test_heic_and_backup_restore(client,tmp_path):
    from pillow_heif import from_pillow
    b=io.BytesIO(); from_pillow(Image.new('RGB',(32,32),'white')).save(b)
    r=client.post('/api/upload',files={'file':('r.heic',b.getvalue(),'image/heic')})
    assert r.status_code==200
    data=client.get('/api/backup').content
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(tmp_path/'restored')
    from ledger import Store
    restored=Store(tmp_path/'restored')
    assert restored.receipt(r.json()['id'])['hash']==r.json()['hash']
    assert (restored.root/'images'/r.json()['image']).exists()

def test_ocr_exact_rule_and_failed_raw_history(client,monkeypatch):
    import local_ocr
    from test_local_ocr import line
    first=client.post('/api/receipts').json()
    client.put(f"/api/receipts/{first['id']}",json={'date':'2026-10-03','store':'店','total':108,'items':[{'name':'商品','category_id':4,'amount':108}],'reviewed':True})
    client.post(f"/api/receipts/{first['id']}/confirm")
    r=client.post('/api/upload',files={'file':('r.png',png(),'image/png')}).json()
    raw={'lines':[line('テスト店',.05),line('2026年10月03日',.1),line('F商品 ¥108',.2),line('合計 ¥108',.3)]}
    monkeypatch.setattr(local_ocr,'recognize',lambda *a:raw)
    url=f"/api/receipts/{r['id']}/ocr/local"
    response=client.post(url)
    assert response.json()['items'][0]['category_id']==4
    monkeypatch.setattr(local_ocr,'parse_receipt',lambda *a:None)
    assert client.post(url).status_code==422
    with client.app.state.store.db() as db:
        assert db.execute('SELECT count(*) FROM ocr_runs WHERE receipt_id=?',(r['id'],)).fetchone()[0]==2

def test_request_without_origin_rejected(client):
    request=client.build_request('POST','/api/receipts');del request.headers['origin']
    assert client.send(request).status_code==403

def test_oversize_streamed_request_rejected(client):
    def chunks():
        for _ in range(14): yield b' '*(1024*1024)
    response=client.post('/api/receipts',content=chunks(),headers={'Content-Type':'application/json'})
    assert response.status_code==413
