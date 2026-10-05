"""Local OCR boundary: no network, no production DB or user samples."""
import importlib.util
import json
from pathlib import Path
import subprocess
import pytest


def test_local_vision_boundary(tmp_path, monkeypatch):
    assert importlib.util.find_spec('local_ocr') is not None, 'free local OCR implementation missing'
    import local_ocr
    images=tmp_path/'images'; images.mkdir()
    image=images/('a'*64+'.jpg'); image.write_bytes(b'fixture')
    binary=tmp_path/'vision'; binary.write_bytes(b'fixture')
    monkeypatch.setattr(local_ocr,'ensure_binary',lambda:binary)
    calls=[]
    def run(args, **kwargs):
        calls.append((args,kwargs))
        return subprocess.CompletedProcess(args,0,json.dumps({'lines':[{'text':'牛肉 ¥120','confidence':0.9,'x':0.1,'y':0.2,'width':0.5,'height':0.02}]}),'')
    monkeypatch.setattr(local_ocr.subprocess,'run',run)
    assert local_ocr.recognize(image,images)['lines'][0]['text']=='牛肉 ¥120'
    assert calls[0][0]==[str(binary),str(image.resolve())]
    assert calls[0][1]['timeout']==60
    assert not calls[0][1].get('shell',False)
    with pytest.raises(local_ocr.LocalOCRError): local_ocr.recognize(tmp_path/'outside.jpg',images)
    assert len(calls)==1


def line(text,y,x=.1,confidence=1,width=.35):
    return dict(text=text,y=y,x=x,width=width,height=.012,confidence=confidence,slope=0)


def test_parser_keeps_uncertain_prices_and_printed_totals():
    import local_ocr
    assert hasattr(local_ocr,'parse_receipt'), 'conservative local parser missing'
    raw={'lines':[line('テスト商店',.05),line('2026年04月03日',.1),
        line('F牛肉',.2),line('¥200',.2,.7,width=.1),
        line('F薄い品',.23),line('¥7',.23,.7,confidence=.5,width=.1),
        line('2コX単50',.25),line('割引前合計',.3),line('¥300',.3,.7),
        line('食料品3/103割引',.33),line('-9',.33,.7),line('小計',.36),line('¥291',.36,.7),
        line('8%対象',.39),line('税 23',.39,.7),line('合計',.42),line('¥314',.42,.7),
        line('3点',.42,.5,width=.1),line('単品の価格は本体価格(税抜)です。',.5)]}
    parsed=local_ocr.parse_receipt(raw,{'牛肉':2})
    assert parsed['date']=='2026-04-03' and parsed['store']=='テスト商店'
    assert parsed['total']==314 and parsed['pre_discount_total']==300
    assert parsed['subtotal']==291 and parsed['discount_total']==9 and parsed['tax_total']==23
    assert parsed['quantity_total']==3 and parsed['tax_rates']==[], 'do not infer all items share rate'
    assert parsed['tax_exclusive'] and not parsed['reviewed']
    assert len(parsed['items'])==2
    assert parsed['items'][0]['pre_tax']==200 and parsed['items'][0]['category_id']==2
    assert parsed['items'][1]['pre_tax'] is None and parsed['items'][1]['quantity']==2
    assert parsed['items'][1]['category_id'] is None
    assert all(item['amount'] is None for item in parsed['items'])
    assert parsed['warnings']


def test_local_endpoint_without_paid_credentials_or_consent(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import io
    from PIL import Image
    import local_ocr, providers
    from ledger import create_app
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    monkeypatch.delenv('OPENAI_MODEL',raising=False)
    monkeypatch.setattr(providers,'extract',lambda *a,**k:pytest.fail('paid API must never be used'))
    raw={'engine':'Apple Vision','lines':[line('テスト商店',.05),line('2026年04月03日',.1),line('F牛肉',.2),line('¥200',.2,.7),line('合計',.3),line('¥200',.3,.7),line('税抜',.4)]}
    monkeypatch.setattr(local_ocr,'recognize',lambda *a:raw)
    app=create_app(tmp_path)
    with app.state.store.db() as db: db.execute('INSERT INTO rules VALUES(?,?)',('牛肉',1))
    with TestClient(app,base_url='http://127.0.0.1:8765',headers={'Origin':'http://127.0.0.1:8765'}) as c:
        img=io.BytesIO(); Image.new('RGB',(30,30)).save(img,format='JPEG')
        r=c.post('/api/upload',files={'file':('fixture.jpg',img.getvalue(),'image/jpeg')}).json()
        url=f"/api/receipts/{r['id']}/ocr/local"
        response=c.post(url)
        assert response.status_code==200, response.text
        data=response.json()
        assert data['status']=='draft' and not data['reviewed']
        assert data['items'][0]['category_id']==1 and data['items'][0]['amount'] is None
        assert json.loads(data['raw'])['engine']=='Apple Vision'
        assert 'F牛肉' in json.loads(data['raw'])['text']
        assert c.get(f"/api/receipts/{r['id']}").json()==data
        assert c.get('/api/settings').json()['ocr_consent'] is False
        assert 'local_ocr' in c.get('/api/settings').json()
        assert c.post(url,headers={'Origin':'http://evil.example'}).status_code==403
        manual=c.post('/api/receipts').json()
        assert c.post(f"/api/receipts/{manual['id']}/ocr/local").status_code==409
        with app.state.store.db() as db:
            assert db.execute('SELECT count(*) FROM ocr_runs').fetchone()[0]==1
            db.execute("UPDATE receipts SET status='confirmed' WHERE id=?",(r['id'],))
        assert c.post(url).status_code==409


def test_inline_and_ambiguous_amounts_are_conservative():
    import local_ocr
    raw={'lines':[line('2026年05月04日',.1),line('F菓子 ¥120',.2),line('合計 ¥120',.3),line('税抜',.4)]}
    p=local_ocr.parse_receipt(raw)
    assert p['total']==120
    assert p['items'][0]['name']=='菓子' and p['items'][0]['pre_tax']==120
    raw['lines'].insert(-1,line('合計 ¥128',.35))
    p=local_ocr.parse_receipt(raw)
    assert p['total'] is None, 'conflicting printed totals must not pick last'
    raw={'lines':[line('2026年02月30日',.1),line('合計 ¥5.449',.3)]}
    p=local_ocr.parse_receipt(raw)
    assert p['date']=='' and p['total'] is None and p['items']==[]


def test_local_timeouts_and_path_escape_are_safe(tmp_path, monkeypatch):
    import local_ocr
    images=tmp_path/'images'; images.mkdir()
    image=images/('b'*64+'.jpg'); image.write_bytes(b'x')
    monkeypatch.setattr(local_ocr,'ensure_binary',lambda:tmp_path/'vision')
    def timeout(*a,**kw): raise subprocess.TimeoutExpired(a[0],60)
    monkeypatch.setattr(local_ocr.subprocess,'run',timeout)
    with pytest.raises(local_ocr.LocalOCRError,match='60秒'): local_ocr.recognize(image,images)
    link=images/('c'*64+'.jpg'); link.symlink_to(image)
    with pytest.raises(local_ocr.LocalOCRError,match='保存済み'): local_ocr.recognize(link,images)
    with pytest.raises(local_ocr.LocalOCRError): local_ocr.recognize(images/'../../outside.jpg',images)
    monkeypatch.setattr(local_ocr.platform,'system',lambda:'Linux')
    assert not local_ocr.availability()['available']
    assert '手入力' in local_ocr.availability()['message']


def test_compile_failure_does_not_leak_diagnostics_or_retry(tmp_path,monkeypatch):
    import local_ocr
    (tmp_path/'native').mkdir();(tmp_path/'native/vision_ocr.swift').write_text('// fixture')
    monkeypatch.setattr(local_ocr,'ROOT',tmp_path)
    monkeypatch.setattr(local_ocr,'availability',lambda:{'available':True})
    calls=[]
    def fail(args,**kwargs):
        calls.append((args,kwargs))
        raise subprocess.CalledProcessError(1,args,stderr='PRIVATE PATH AND TEXT')
    monkeypatch.setattr(local_ocr.subprocess,'run',fail)
    with pytest.raises(local_ocr.LocalOCRError) as exc: local_ocr.ensure_binary()
    assert 'PRIVATE' not in str(exc.value) and len(calls)==1
    assert calls[0][1]['timeout']==120
    assert not list((tmp_path/'artifacts/local-ocr-cache').glob('*.building'))


def test_native_contract_and_slope_rows():
    import local_ocr
    source=(local_ocr.ROOT/'native/vision_ocr.swift').read_text()
    assert 'VNRecognizeTextRequest' in source and 'supportedRecognitionLanguages' in source
    assert 'ja-JP' in source and 'observation.topRight' in source
    raw={'lines':[line('テスト店',.05),line('2026年04月03日',.1),line('F牛肉',.2),line('¥200',.224,.7,width=.1),line('合計',.3),line('¥200',.324,.7,width=.1),line('税抜',.4)]}
    for l in raw['lines']:
        l['slope']=.04
        l['width']=.1 if l['text'].startswith('¥') else .1
    # Provide long-line orientation metadata independently of the short labels.
    raw['lines'].append({**line('単品価格は税抜です',.5,width=.35),'slope':.04})
    p=local_ocr.parse_receipt(raw)
    assert p['total']==200 and p['items'][0]['pre_tax']==200


def test_multiple_tax_groups_do_not_become_total_tax():
    import local_ocr
    raw={'lines':[line('2026年04月03日',.1),line('合計 ¥1000',.3),line('8%対象',.4),line('税 40',.4,.7),line('10%対象',.5),line('税 50',.5,.7)]}
    p=local_ocr.parse_receipt(raw)
    assert p['tax_total'] is None, 'neither last tax group nor an inferred sum is a printed total'
    assert p['tax_rates']==[]
