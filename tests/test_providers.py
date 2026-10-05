import importlib.util, json
import httpx
import pytest
from test_app import client
from test_upload import png

def test_provider_contracts():
    assert importlib.util.find_spec('providers') is not None, 'providers missing'
    from providers import drive_files, drive_download
    seen=[]
    result={'date':'2026-10-03','store':'店','total':108,'tax_inclusive':False,'warnings':['税別'],'items':[{'name':'牛肉','amount':100,'category_id':1}]}
    def handler(req):
        seen.append(req)
        if req.url.params.get('alt')=='media': return httpx.Response(200,content=png())
        if req.url.params.get('pageToken')=='next': return httpx.Response(200,json={'files':[{'id':'b','mimeType':'image/png'}]})
        assert "'folder' in parents" in req.url.params['q']
        return httpx.Response(200,json={'files':[{'id':'a','mimeType':'image/png'}],'nextPageToken':'next'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        assert [f['id'] for f in drive_files('folder','token',transport)]==['a','b']
        assert drive_download('a','token',transport)==png()

def test_paid_ocr_removed_and_legacy_settings_compatible(client, monkeypatch):
    import providers
    assert not hasattr(providers, 'extract')
    monkeypatch.setenv('OPENAI_API_KEY', 'unused-key')
    monkeypatch.setenv('OPENAI_MODEL', 'unused-model')
    with client.app.state.store.db() as db:
        db.execute("INSERT OR REPLACE INTO settings VALUES('preferences',?)",
                   (json.dumps({'ocr_consent': True, 'drive_folder': 'folder'}),))
    settings = client.get('/api/settings').json()
    assert settings['drive_folder']=='folder'
    assert settings['local_ocr']['engine']=='PaddleOCR'
    assert not {'ocr_consent', 'key_present', 'model', 'ocr_ready', 'ocr_missing'} & settings.keys()
    r=client.post('/api/upload',files={'file':('r.png',png(),'image/png')}).json()
    assert client.post(f"/api/receipts/{r['id']}/ocr").status_code==404
    assert client.put('/api/settings',json={'drive_folder':'new_folder','ocr_consent':True}).status_code==200
    with client.app.state.store.db() as db:
        saved=json.loads(db.execute("SELECT value FROM settings WHERE key='preferences'").fetchone()[0])
    assert saved=={'drive_folder':'new_folder'}
    assert 'id="ocr"' not in client.get('/').text
    assert 'OpenAI' not in client.get('/static/app.js').text

def test_drive_import_file_and_hash_dedup(client,monkeypatch):
    assert client.post('/api/drive/import').status_code==409
    import providers
    client.put('/api/settings',json={'ocr_consent':False,'drive_folder':'folder'})
    monkeypatch.setattr(providers,'google_token',lambda root:'token')
    monkeypatch.setattr(providers,'drive_files',lambda *a:[{'id':'a','mimeType':'image/png'},{'id':'b','mimeType':'image/png'}])
    calls=[]
    def download(*a): calls.append(a[0]); return png()
    monkeypatch.setattr(providers,'drive_download',download)
    assert client.post('/api/drive/import').json()['imported']==1
    assert client.post('/api/drive/import').json()['imported']==0
    assert calls==['a','b']
    assert len(client.get('/api/receipts').json())==1
