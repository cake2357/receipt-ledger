from test_app import client

def test_schema_and_tax_locations(client):
    rid=client.post('/api/receipts').json()['id']; url=f'/api/receipts/{rid}'
    r=client.put(url,json={'items':[{'amount':1.2}]})
    assert ['items',0,'amount'] in [e['loc'] for e in r.json()['field_errors']]
    client.put(url,json={'tax_exclusive':True,'items':[{'category_id':1}]})
    r=client.post(url+'/tax-preview')
    assert ['items',0,'pre_tax'] in [e['loc'] for e in r.json()['field_errors']]
    r=client.post(url+'/allocation-preview')
    assert ['tax_rates'] in [e['loc'] for e in r.json()['field_errors']]

def test_category_duplicate_location(client):
    r=client.post('/api/categories',json={'name':'おやつ','description':''})
    assert r.status_code==409
    assert r.json()['field_errors'][0]['loc']==['name']
