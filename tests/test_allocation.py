"""Values visibly read from user samples; originals are NOT test fixtures.
The second sample's faint prices deliberately remain unknown.
"""
from test_app import client
import pytest

@pytest.mark.parametrize('rates',[[],[8,10],[8,8],[7]])
def test_unsafe_tax_groups_blocked(client,rates):
    body=sample([100],{},'2026-10-02',0,8,108,100,1)
    body['tax_rates']=rates
    rid=client.post('/api/receipts').json()['id']
    assert client.put(f'/api/receipts/{rid}',json=body).status_code==200
    response=client.post(f'/api/receipts/{rid}/allocate')
    assert response.status_code==422
    assert client.get(f'/api/receipts/{rid}').json()['items'][0]['amount'] is None

FIRST=[359,204,238,153,238,208,115,122,211,129,337,691,642,198,306,115,141,195,149,89,216,129]
SECOND=[399,312,327,141,168,122,238,238,131,204,438,71,None,None,125,405,700]

def sample(amounts,quantities,day,discount,tax,total,pre,qty):
    return {'date':day,'store':'OK 梅屋敷店','total':total,'reviewed':True,'tax_exclusive':True,'tax_rates':[8],'pre_discount_total':pre,'subtotal':pre-discount,'discount_total':discount,'tax_total':tax,'quantity_total':qty,'allocation_approved':False,'items':[{'name':f'商品{i+1}','category_id':5,'pre_tax':n,'quantity':quantities.get(i,1),'amount':None} for i,n in enumerate(amounts)]}

def test_sample_0725_deterministic_allocation(client):
    assert len(FIRST)==22 and sum(FIRST)==5185
    body=sample(FIRST,{4:2,5:2,20:2},'2026-09-29',139,403,5449,5185,25)
    r=client.post('/api/receipts').json();rid=r['id']
    client.put(f'/api/receipts/{rid}',json=body)
    result=client.post(f'/api/receipts/{rid}/allocate')
    assert result.status_code==200, 'explicit allocation action missing'
    out=result.json()
    assert len(out['items'])==22 and sum(i['quantity'] for i in out['items'])==25
    assert sum(i['allocated_discount'] for i in out['items'])==139
    assert sum(i['allocated_tax'] for i in out['items'])==403
    assert sum(i['amount'] for i in out['items'])==5449
    assert out['subtotal']==5046
    assert out['allocation_method']=='largest-remainder-v1'
    assert all(i['amount_source']=='calculated' for i in out['items'])
    assert not out['allocation_approved'] and not out['reviewed']
    assert client.post(f'/api/receipts/{rid}/confirm').status_code==422
    assert client.post(f'/api/receipts/{rid}/allocate').json()['items']==out['items']
    out.update(allocation_approved=True,reviewed=True)
    client.put(f'/api/receipts/{rid}',json=out)
    assert client.post(f'/api/receipts/{rid}/confirm').status_code==200
    assert client.get('/api/dashboard?month=2026-09').json()['total']==5449
    client.post(f'/api/receipts/{rid}/reopen')
    out['items'][0]['pre_tax']+=1
    client.put(f'/api/receipts/{rid}',json=out)
    assert client.post(f'/api/receipts/{rid}/confirm').status_code==422

def test_sample_0726_unknown_prices_never_backsolved(client):
    body=sample(SECOND,{1:3,7:2},'2026-10-02',123,356,4810,4577,20)
    body['items'][12]['name']='ムラカワ スライスチーズ20マイ'
    body['items'][13]['name']='イワシタコウサン ベニショウガ'
    assert len(body['items'])==17 and sum(i['quantity'] for i in body['items'])==20
    r=client.post('/api/receipts').json();rid=r['id']
    client.put(f'/api/receipts/{rid}',json=body)
    assert client.post(f'/api/receipts/{rid}/allocate').status_code==422
    stored=client.get(f'/api/receipts/{rid}').json()
    assert stored['items'][12]['pre_tax'] is None and stored['items'][13]['pre_tax'] is None
    assert client.post(f'/api/receipts/{rid}/confirm').status_code==422

def test_unknown_quantity_is_preserved_in_draft(client):
    body=sample([100],{},'2026-10-02',0,8,108,100,1)
    body['items'][0]['quantity']=None
    rid=client.post('/api/receipts').json()['id']
    response=client.put(f'/api/receipts/{rid}',json=body)
    assert response.status_code==200
    assert response.json()['items'][0]['quantity'] is None
    assert client.post(f'/api/receipts/{rid}/allocate').status_code==422

@pytest.mark.parametrize('field,value',[('subtotal',99),('discount_total',101),('tax_total',None),('pre_discount_total',None)])
def test_inconsistent_receipt_totals_blocked(client,field,value):
    body=sample([100],{},'2026-10-02',0,8,108,100,1)
    body[field]=value
    rid=client.post('/api/receipts').json()['id']
    assert client.put(f'/api/receipts/{rid}',json=body).status_code==200
    assert client.post(f'/api/receipts/{rid}/allocate').status_code==422

@pytest.mark.parametrize('field',['pre_tax','discount_total','tax_total'])
def test_negative_allocation_inputs_rejected(client,field):
    body=sample([100],{},'2026-10-02',0,8,108,100,1)
    target=body['items'][0] if field=='pre_tax' else body
    target[field]=-1
    rid=client.post('/api/receipts').json()['id']
    assert client.put(f'/api/receipts/{rid}',json=body).status_code==422


def test_preview_does_not_apply(client):
    body=sample([100],{},'2026-10-02',3,7,104,100,1)
    rid=client.post('/api/receipts').json()['id']
    client.put(f'/api/receipts/{rid}',json=body)
    before=client.get(f'/api/receipts/{rid}').json()
    response=client.post(f'/api/receipts/{rid}/allocation-preview')
    assert response.status_code==200
    assert response.json()['items'][0]['amount']==104
    assert client.get(f'/api/receipts/{rid}').json()==before


def test_largest_remainder_ties_and_totals(client):
    body=sample([1,1,1],{},'2026-10-02',1,1,3,3,3)
    rid=client.post('/api/receipts').json()['id'];client.put(f'/api/receipts/{rid}',json=body)
    response=client.post(f'/api/receipts/{rid}/allocate');assert response.status_code==200
    out=response.json()
    assert [i['allocated_discount'] for i in out['items']]==[1,0,0]
    assert [i['allocated_tax'] for i in out['items']]==[0,1,0]
    body['quantity_total']=4;client.put(f'/api/receipts/{rid}',json=body)
    assert client.post(f'/api/receipts/{rid}/allocate').status_code==422
