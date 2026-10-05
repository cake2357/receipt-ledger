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
    import providers
    monkeypatch.setenv('OPENAI_API_KEY','test');monkeypatch.setenv('OPENAI_MODEL','test')
    client.put('/api/settings',json={'ocr_consent':True})
    first=client.post('/api/receipts').json()
    client.put(f"/api/receipts/{first['id']}",json={'date':'2026-10-03','store':'店','total':108,'items':[{'name':'商品','category_id':4,'amount':108}],'reviewed':True})
    client.post(f"/api/receipts/{first['id']}/confirm")
    r=client.post('/api/upload',files={'file':('r.png',png(),'image/png')}).json()
    parsed={'date':'2026-10-03','store':'店','total':108,'tax_inclusive':True,'warnings':[],'items':[{'name':'商品','category_id':1,'amount':108}]}
    monkeypatch.setattr(providers,'extract',lambda *a:(parsed,{'first':'raw'}))
    response=client.post(f"/api/receipts/{r['id']}/ocr")
    assert response.json()['items'][0]['category_id']==4
    monkeypatch.setattr(providers,'extract',lambda *a:(None,{'refusal':'raw'}))
    assert client.post(f"/api/receipts/{r['id']}/ocr").status_code==502
    with client.app.state.store.db() as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='ocr_runs'").fetchone(), 'retain every extraction raw output'
        assert db.execute('SELECT count(*) FROM ocr_runs WHERE receipt_id=?',(r['id'],)).fetchone()[0]==2

def test_request_without_origin_rejected(client):
    request=client.build_request('POST','/api/receipts');del request.headers['origin']
    assert client.send(request).status_code==403

def test_oversize_streamed_request_rejected(client):
    def chunks():
        for _ in range(14): yield b' '*(1024*1024)
    response=client.post('/api/receipts',content=chunks(),headers={'Content-Type':'application/json'})
    assert response.status_code==413
