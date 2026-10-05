from test_app import client
import sqlite3
import pytest


def draft(client, items=None, **updates):
    body=dict(date='2026-10-03',store='オーケー 梅屋敷店',total=218,tax_exclusive=True,
              items=items or [dict(name='肉',category_id=1,pre_tax=100),dict(name='洗剤',category_id=5,pre_tax=100)])
    body.update(updates)
    rid=client.post('/api/receipts').json()['id']
    assert client.put(f'/api/receipts/{rid}',json=body).status_code==200
    return f'/api/receipts/{rid}'


def test_automatic_mixed_preview_apply_preserves_printed_values(client):
    url=draft(client,tax_total=999,discount_total=7,pre_discount_total=200)
    before=client.get(url).json()
    response=client.post(url+'/tax-preview')
    assert response.status_code==200
    proposal=response.json()
    assert [i['amount'] for i in proposal['items']]==[108,110]
    assert proposal['calculation']['total']==218
    assert proposal['calculation']['tax_total']==18
    assert proposal['tax_total']==999 and proposal['discount_total']==7
    assert client.get(url).json()==before
    out=client.post(url+'/tax-apply',json={'signature':proposal['calculation']['signature']}).json()
    assert out['allocation_method']=='category-tax-v1'
    assert out['calculation']==proposal['calculation']
    assert not out['reviewed'] and not out['allocation_approved']
    out.update(reviewed=True,allocation_approved=True)
    assert client.put(url,json=out).status_code==200
    assert client.post(url+'/confirm').status_code==200



@pytest.mark.parametrize('mode,discount,tax,total',[('off',0,82,1112),('formula',30,80,1080),('printed',31,79,1078)])
def test_ok_discount_exact_rational_before_group_tax(client,mode,discount,tax,total):
    url=draft(client,items=[dict(name='食品',category_id=1,pre_tax=1030)],ok_discount_mode=mode,discount_total=31,total=total)
    response=client.post(url+'/tax-preview')
    assert response.status_code==200
    out=response.json()
    assert out['calculation']['discount_total']==discount
    assert out['calculation']['tax_total']==tax
    assert out['calculation']['total']==total
    assert out['discount_total']==31


def test_discount_only_explicit_eligible_and_mixed_rates(client):
    url=draft(client,items=[dict(name='対象食品',category_id=1,pre_tax=1030),dict(name='対象外食品',category_id=1,pre_tax=1030,ok_discount_eligible=False),dict(name='対象10',category_id=5,pre_tax=1030,ok_discount_eligible=True)],ok_discount_mode='formula')
    out=client.post(url+'/tax-preview').json()
    assert [i['allocated_discount'] for i in out['items']]==[30,0,30]
    assert [i['amount'] for i in out['items']]==[1080,1112,1100]
    assert out['calculation']['tax_total']==262


@pytest.mark.parametrize('discount',[None,101])
def test_printed_discount_cannot_exceed_eligible_base(client,discount):
    url=draft(client,items=[dict(name='対象',category_id=1,pre_tax=100),dict(name='対象外',category_id=5,pre_tax=1000)],ok_discount_mode='printed',discount_total=discount)
    assert client.post(url+'/tax-preview').status_code==422


def applied(client, **kwargs):
    url=draft(client,**kwargs)
    p=client.post(url+'/tax-preview').json()
    out=client.post(url+'/tax-apply',json={'signature':p['calculation']['signature']}).json()
    out.update(reviewed=True,allocation_approved=True)
    client.put(url,json=out)
    return url,client.get(url).json()


@pytest.mark.parametrize('change',['price','category','rate','eligibility','mode','amount','printed'])
def test_edit_invalidates_approval_and_requires_explicit_recompute(client,change):
    url,out=applied(client)
    if change=='price': out['items'][0]['pre_tax']=101
    elif change=='category': out['items'][0]['category_id']=5
    elif change=='rate': out['items'][0]['tax_rate']=10
    elif change=='eligibility': out['items'][0]['ok_discount_eligible']=False
    elif change=='mode': out['ok_discount_mode']='formula'
    elif change=='amount': out['items'][0]['amount']=109
    else: out['tax_total']=1
    saved=client.put(url,json=out).json()
    assert not saved['allocation_approved'] and not saved['reviewed']
    assert saved['calculation']==out['calculation']  # retain estimate, mark stale; never silently recompute
    assert client.post(url+'/confirm').status_code==422
    saved.update(reviewed=True,allocation_approved=True)
    client.put(url,json=saved)
    assert client.post(url+'/confirm').status_code==422


def test_category_rule_change_invalidates_drafts_not_confirmed_or_history(client):
    confirmed,body=applied(client)
    assert client.post(confirmed+'/confirm').status_code==200
    frozen=client.get(confirmed).json()
    url,out=applied(client)
    cats=client.get('/api/categories').json()
    c=cats[0];c['tax_rate']=10;c['ok_discount_eligible']=False
    assert client.put('/api/categories/1',json={**c,'ok_discount_eligible':False}).status_code==200
    saved=client.get(url).json()
    assert not saved['reviewed'] and not saved['allocation_approved']
    assert saved['items']==out['items']
    assert client.get(confirmed).json()==frozen
    assert client.get('/api/dashboard?month=2026-10').json()['total']==218
    assert client.post(url+'/tax-apply',json={'signature':out['calculation']['signature']}).status_code==409
    assert client.post(confirmed+'/tax-preview').status_code==409
    assert client.post(confirmed+'/tax-apply',json={}).status_code==409


def test_category_metadata_migration_backup_preserves_history(tmp_path):
    from ledger import Store
    db=sqlite3.connect(tmp_path/'ledger.sqlite3')
    db.execute('CREATE TABLE categories(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE,description TEXT NOT NULL)')
    db.executemany('INSERT INTO categories VALUES(?,?,?)',[(1,'食料品（魚）','独自説明'),(2,'育児','変更済み')]);db.commit();db.close()
    store=Store(tmp_path)
    with store.db() as db:
        cats=[dict(r) for r in db.execute('SELECT * FROM categories')]
    assert cats[0]['tax_rate']==8 and cats[0]['ok_discount_eligible']==1
    assert cats[1]['tax_rate']==10 and cats[1]['ok_discount_eligible']==0
    assert cats[0]['description']=='独自説明'
    backups=list(tmp_path.glob('before-tax-rules-*.sqlite3'))
    assert len(backups)==1
    with sqlite3.connect(backups[0]) as db:
        assert 'tax_rate' not in [r[1] for r in db.execute('PRAGMA table_info(categories)')]
    Store(tmp_path)
    assert len(list(tmp_path.glob('before-tax-rules-*.sqlite3')))==1


def test_category_edit_preserves_metadata(client):
    cats=client.get('/api/categories').json()
    assert [(c['tax_rate'],bool(c['ok_discount_eligible'])) for c in cats]==[(8,True),(8,True),(8,True),(10,False),(10,False)]
    response=client.put('/api/categories/1',json={'name':'好きな分類','description':'任意の説明','tax_rate':10,'ok_discount_eligible':False})
    assert response.status_code==200
    response=client.put('/api/categories/1',json={'name':'別名','description':'説明も保持'})
    assert response.json()['tax_rate']==10 and response.json()['ok_discount_eligible'] is False
    c=client.post('/api/categories',json={'name':'新しい独自分類','description':'要設定'}).json()
    assert c['tax_rate'] is None
    assert client.put('/api/categories/1',json={'name':'分類','description':'','tax_rate':7}).status_code==422


def test_manual_ok_rounding_correction_confirmed_and_recalculation_resets_it(client):
    url,out=applied(client,items=[dict(name='食品',category_id=1,pre_tax=1030)],
                    ok_discount_mode='formula',total=1079)
    assert out['items'][0]['amount']==1080
    out['items'][0].update(amount=1079,amount_source='manual')
    out.update(reviewed=False,allocation_approved=False)
    saved=client.put(url,json=out).json()
    assert client.post(url+'/confirm').status_code==422
    saved.update(reviewed=True,allocation_approved=True)
    assert client.put(url,json=saved).status_code==200
    assert client.post(url+'/confirm').status_code==200
    assert client.get('/api/dashboard?month=2026-10').json()['total']==1079
    persisted=client.get(url).json()
    assert persisted['calculation']['total']==1080
    assert persisted['items'][0]['amount_source']=='manual'
    client.post(url+'/reopen')
    proposal=client.post(url+'/tax-preview').json()
    reset=client.post(url+'/tax-apply',json={'signature':proposal['calculation']['signature']}).json()
    assert reset['items'][0]['amount']==1080
    assert reset['items'][0]['amount_source']=='calculated'
    assert not reset['reviewed'] and not reset['allocation_approved']


def test_manual_correction_can_be_reapproved_before_saving(client):
    url,out=applied(client,total=217)
    out['items'][0].update(amount=107,amount_source='manual')
    saved=client.put(url,json=out).json()
    assert saved['reviewed'] and saved['allocation_approved']
    assert client.post(url+'/confirm').status_code==200


@pytest.mark.parametrize('change',['price','rate','eligibility','mode','allocations','missing','mismatch','category_rule'])
def test_manual_override_keeps_source_and_balance_checks(client,change):
    url,out=applied(client)
    out['items'][0]['amount_source']='manual'
    if change=='price': out['items'][0]['pre_tax']=101
    elif change=='rate': out['items'][0]['tax_rate']=10
    elif change=='eligibility': out['items'][0]['ok_discount_eligible']=False
    elif change=='mode': out['ok_discount_mode']='formula'
    elif change=='allocations': out['items'][0]['allocated_tax']=9
    elif change=='missing': out['items'][0]['amount']=None
    elif change=='mismatch': out['items'][0]['amount']=107
    else:
        cat=client.get('/api/categories').json()[0]
        cat.update(tax_rate=10,ok_discount_eligible=bool(cat['ok_discount_eligible']))
        client.put('/api/categories/1',json=cat)
    saved=client.put(url,json=out).json()
    saved.update(reviewed=True,allocation_approved=True)
    client.put(url,json=saved)
    assert client.post(url+'/confirm').status_code==422
