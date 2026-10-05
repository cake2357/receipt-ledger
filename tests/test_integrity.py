from test_app import client
import pytest

def test_integer_storage_and_rule_application(client):
    r=client.post('/api/receipts').json(); rid=r['id']
    body={'date':'2026-02-03','store':'店','total':123,'items':[{'name':'牛肉','category_id':1,'amount':123}],'reviewed':True}
    for wrong in [1.5,True,'123']:
        body['items'][0]['amount']=wrong
        assert client.put(f'/api/receipts/{rid}',json=body).status_code==422
    body['items'][0]['amount']=123
    client.put(f'/api/receipts/{rid}',json=body);client.post(f'/api/receipts/{rid}/confirm')
    with client.app.state.store.db() as db:
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert 'entries' in tables, 'confirmed yen needs INTEGER ledger entries'
        assert db.execute('SELECT amount,typeof(amount) FROM entries').fetchone()[:]==(123,'integer')
    client.post(f'/api/receipts/{rid}/reopen')
    with client.app.state.store.db() as db: assert db.execute('SELECT count(*) FROM entries').fetchone()[0]==0

def test_canonical_date_required(client):
    r=client.post('/api/receipts').json()
    client.put(f"/api/receipts/{r['id']}",json={'date':'20260203','store':'店','total':1,'items':[{'name':'肉','category_id':1,'amount':1}],'reviewed':True})
    assert client.post(f"/api/receipts/{r['id']}/confirm").status_code==422
