import importlib.util, json
import httpx
import pytest
from test_app import client
from test_upload import png

def test_provider_contracts():
    assert importlib.util.find_spec('providers') is not None, 'providers missing'
    from providers import extract, drive_files, drive_download
    seen=[]
    result={'date':'2026-10-03','store':'店','total':108,'tax_inclusive':False,'warnings':['税別'],'items':[{'name':'牛肉','amount':100,'category_id':1}]}
    def handler(req):
        seen.append(req)
        if req.url.host=='api.openai.com':
            body=json.loads(req.content)
            assert body['text']['format']['type']=='json_schema'
            assert '精肉' in body['input'][0]['content'][0]['text']
            assert body['store'] is False
            schema=body['text']['format']['schema']
            assert 'pre_tax' in schema['properties']['items']['items']['properties']
            assert 'pre_discount_total' in schema['properties']
            assert 'subtotal' in schema['properties']
            assert 'tax_rates' in schema['properties']
            return httpx.Response(200,json={'output':[{'content':[{'type':'output_text','text':json.dumps(result)}]}]})
        if req.url.params.get('alt')=='media': return httpx.Response(200,content=png())
        if req.url.params.get('pageToken')=='next': return httpx.Response(200,json={'files':[{'id':'b','mimeType':'image/png'}]})
        assert "'folder' in parents" in req.url.params['q']
        return httpx.Response(200,json={'files':[{'id':'a','mimeType':'image/png'}],'nextPageToken':'next'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        parsed,raw=extract(png(),'key','model',[{'id':1,'name':'肉','description':'精肉'}],transport)
        assert parsed['tax_inclusive'] is False and raw['output']
        assert [f['id'] for f in drive_files('folder','token',transport)]==['a','b']
        assert drive_download('a','token',transport)==png()

def test_settings_ocr_consent_raw_and_rules(client,monkeypatch):
    assert client.get('/api/settings').status_code==200
    s=client.get('/api/settings').json(); assert s['ocr_consent'] is False and not s['ocr_ready']
    r=client.post('/api/upload',files={'file':('r.png',png(),'image/png')}).json()
    assert client.post(f"/api/receipts/{r['id']}/ocr").status_code==409
    monkeypatch.setenv('OPENAI_API_KEY','test-key')
    monkeypatch.setenv('OPENAI_MODEL','test-model')
    assert client.put('/api/settings',json={'ocr_consent':True,'drive_folder':''}).status_code==200
    import providers
    data={'date':'2026-10-03','store':'店','total':108,'tax_inclusive':False,'warnings':['税別'],'items':[{'name':'牛肉','amount':100,'category_id':1}]}
    monkeypatch.setattr(providers,'extract',lambda *a,**k:(data,{'original':'raw'}))
    out=client.post(f"/api/receipts/{r['id']}/ocr").json()
    assert out['raw'] and out['warnings'] and out['items'][0]['amount'] is None and not out['reviewed']
    assert out['tax_exclusive'] is True
    assert client.post(f"/api/receipts/{r['id']}/confirm").status_code==422

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
