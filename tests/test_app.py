import importlib.util
from fastapi.testclient import TestClient
import pytest

@pytest.fixture
def client(tmp_path):
    assert importlib.util.find_spec('ledger') is not None, 'ledger application missing'
    from ledger import create_app
    with TestClient(create_app(tmp_path), base_url='http://127.0.0.1:8765', headers={'Origin':'http://127.0.0.1:8765'}) as c:
        yield c

def test_categories_dashboard_csv_backup(client):
    import io, zipfile, sqlite3
    cats=client.get('/api/categories').json()
    cid=cats[0]['id']
    assert client.put(f'/api/categories/{cid}',json={'name':'肉類','description':'精肉と加工肉'}).status_code==200
    assert client.post('/api/categories',json={'name':'日用品','description':'掃除用品'}).status_code==200
    r=client.post('/api/receipts').json()
    body={'date':'2026-02-03','store':'=evil','total':123,'items':[{'name':'+evil','category_id':cid,'amount':123}],'reviewed':True}
    client.put(f"/api/receipts/{r['id']}",json=body)
    assert client.get('/api/dashboard?month=2026-02').json()['total']==0
    client.post(f"/api/receipts/{r['id']}/confirm")
    d=client.get('/api/dashboard?month=2026-02').json()
    assert d['total']==123 and len(d['days'])==28 and d['days'][2]['categories'][str(cid)]==123
    assert d['days'][0]['total']==0
    assert "'=evil" in client.get('/api/export.csv?month=2026-02').text
    z=zipfile.ZipFile(io.BytesIO(client.get('/api/backup').content))
    assert 'ledger.sqlite3' in z.namelist()
    assert client.get('/api/dashboard?month=bad').status_code==422

def test_empty_manual_review_confirm_reopen(client):
    assert client.get('/api/receipts').json() == []
    cats=client.get('/api/categories').json()
    assert [c['name'] for c in cats] == ['食料品（肉）','食料品（野菜）','おやつ','育児','その他']
    r=client.post('/api/receipts',json={}).json()
    assert client.post(f"/api/receipts/{r['id']}/confirm").status_code == 422
    body={'date':'2026-10-03','store':'店','total':120,'items':[{'name':'牛肉','category_id':cats[0]['id'],'amount':120}], 'reviewed':True}
    assert client.put(f"/api/receipts/{r['id']}",json=body).status_code == 200
    assert client.post(f"/api/receipts/{r['id']}/confirm").json()['status']=='confirmed'
    assert client.put(f"/api/receipts/{r['id']}",json=body).status_code == 409
    assert client.post(f"/api/receipts/{r['id']}/reopen").json()['status']=='draft'
    body['total']=121
    client.put(f"/api/receipts/{r['id']}",json=body)
    assert client.post(f"/api/receipts/{r['id']}/confirm").status_code==422


def test_input_suggestions_use_confirmed_history_and_latest_rule(client):
    assert client.get('/api/input-suggestions').json() == {'items': [], 'stores': []}
    for category, store, confirm in [(1, '以前の店', True), (2, '最近の店', True), (3, '下書き店', False)]:
        receipt = client.post('/api/receipts').json()
        body = {'date': '2026-10-04', 'store': store, 'total': 100,
                'items': [{'name': '牛乳', 'category_id': category, 'amount': 100}], 'reviewed': True}
        client.put(f"/api/receipts/{receipt['id']}", json=body)
        if confirm:
            assert client.post(f"/api/receipts/{receipt['id']}/confirm").status_code == 200
    assert client.get('/api/input-suggestions').json() == {
        'items': [{'name': '牛乳', 'category_id': 2}], 'stores': ['最近の店', '以前の店']}
