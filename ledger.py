import json
import sqlite3
import threading
from pathlib import Path
from datetime import date
from contextlib import contextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, StrictInt, StrictBool
from typing import Literal
from uuid import uuid4
from validation import FieldError, field, install_validation

SEEDS=[('食料品（肉）','肉、鶏肉、豚肉、牛肉など'),('食料品（野菜）','野菜、きのこなど'),('おやつ','菓子、甘い間食'),('育児','子どもの育児用品'),('その他','他の分類に当てはまらないもの')]
class Item(BaseModel):
    name: str = Field(default='',max_length=500)
    category_id: int | None = None
    amount: StrictInt | None = Field(default=None,ge=-100000000,le=100000000)
    quantity: StrictInt | None = Field(default=1,ge=1,le=10000)
    pre_tax: StrictInt | None = Field(default=None,ge=0,le=100000000)
    allocated_discount: StrictInt | None = Field(default=None,ge=0,le=100000000)
    allocated_tax: StrictInt | None = Field(default=None,ge=0,le=100000000)
    tax_rate: Literal[8,10] | None = None
    ok_discount_eligible: StrictBool | None = None
    amount_source: str = Field(default='manual',pattern=r'^(manual|calculated)$')
class Review(BaseModel):
    date: str = ''
    store: str = Field(default='',max_length=500)
    total: StrictInt | None = Field(default=None,ge=0,le=100000000)
    items: list[Item] = Field(default_factory=list,max_length=1000)
    reviewed: bool = False
    tax_exclusive: bool = False
    tax_rates: list[StrictInt] = Field(default_factory=list,max_length=10)
    pre_discount_total: StrictInt | None = Field(default=None,ge=0,le=100000000)
    discount_total: StrictInt | None = Field(default=None,ge=0,le=100000000)
    tax_total: StrictInt | None = Field(default=None,ge=0,le=100000000)
    quantity_total: StrictInt | None = Field(default=None,ge=1,le=10000000)
    subtotal: StrictInt | None = Field(default=None,ge=0,le=100000000)
    allocation_method: str | None = Field(default=None,pattern=r'^(largest-remainder-v1|category-tax-v1)$')
    calculation: dict | None = None
    ok_discount_mode: Literal['off','formula','printed'] = 'off'
    allocation_approved: bool = False


def allocate(body):
    """Bookkeeping convention, never an assertion of observed item tax."""
    if body.tax_rates not in ([0],[8],[10]): raise FieldError('全商品の税率が同じ場合だけ使える計算方法です。税率を確認してください',[field(['tax_rates'],'単一税率を選択してください。混在ならカテゴリから税込計算を使ってください')])
    if not body.tax_exclusive: raise FieldError('「商品の金額が税抜で書かれている」を選択してください',[field(['tax_exclusive'],'税別レシートを選択してください')])
    if not body.items or any(i.pre_tax is None for i in body.items): raise FieldError('不明な税抜明細額があります。差額から補完しません',[field(['items',n,'pre_tax'],'税抜明細額を入力してください') for n,i in enumerate(body.items) if i.pre_tax is None] or [field(['items'],'明細を追加してください')])
    if any(i.quantity is None for i in body.items): raise FieldError('数量が不明です。印字の数量を確認してください',[field(['items',n,'quantity'],'数量を入力してください') for n,i in enumerate(body.items) if i.quantity is None])
    weights=[i.pre_tax for i in body.items]; base=sum(weights)
    if body.pre_discount_total!=base: raise FieldError('税抜明細額と印字の割引前合計が一致しません',[field(['pre_discount_total'],'印字の割引前合計と税抜明細額を照合してください',True)])
    if body.quantity_total is not None and sum(i.quantity for i in body.items)!=body.quantity_total: raise FieldError('数量合計と印字点数が一致しません（明細行数とは異なります）',[field(['quantity_total'],'印字点数と明細数量の合計を照合してください',True)])
    discount=body.discount_total; tax=body.tax_total
    if discount is None or tax is None or discount>base or body.total!=base-discount+tax: raise FieldError('印字の割引額・税額・合計を確認してください',[field([key],'印字の割引額・税額・合計を照合してください',True) for key in ('discount_total','tax_total','total')])
    if body.subtotal is not None and body.subtotal!=base-discount: raise FieldError('印字の割引後小計が一致しません',[field(['subtotal'],'割引後小計を照合してください',True)])
    def distribute(total,values):
        denominator=sum(values)
        if not denominator:
            if total: raise HTTPException(422,'商品の税抜金額が0円のため、割引・税金を分けて計算できません')
            return [0]*len(values)
        result=[total*v//denominator for v in values]
        order=sorted(range(len(values)),key=lambda i:(-(total*values[i]%denominator),i))
        for i in order[:total-sum(result)]: result[i]+=1
        return result
    discounts=distribute(discount,weights)
    taxes=distribute(tax,[v-d for v,d in zip(weights,discounts)])
    output=body.model_copy(deep=True)
    for i,item in enumerate(output.items):
        item.allocated_discount=discounts[i]; item.allocated_tax=taxes[i]
        item.amount=weights[i]-discounts[i]+taxes[i]; item.amount_source='calculated'
    output.reviewed=False; output.allocation_approved=False
    output.allocation_method='largest-remainder-v1'
    return output

class Store:
    def __init__(self,root):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        # Back up the untouched old schema with SQLite's consistent snapshot API.
        path=self.root/'ledger.sqlite3'
        if path.exists():
            with sqlite3.connect(path) as source:
                cols={r[1] for r in source.execute('PRAGMA table_info(categories)')}
                if cols and not {'tax_rate','ok_discount_eligible'} <= cols:
                    backup=self.root/f'before-tax-rules-{uuid4().hex}.sqlite3'
                    backup.touch(mode=0o600)
                    with sqlite3.connect(backup) as dest: source.backup(dest)
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE,description TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS receipts(id INTEGER PRIMARY KEY,status TEXT NOT NULL DEFAULT 'draft',body TEXT NOT NULL,image TEXT,hash TEXT UNIQUE,raw TEXT,warnings TEXT NOT NULL DEFAULT '[]');
            CREATE TABLE IF NOT EXISTS entries(receipt_id INTEGER NOT NULL,line INTEGER NOT NULL,category_id INTEGER NOT NULL,amount INTEGER NOT NULL CHECK(typeof(amount)='integer'),PRIMARY KEY(receipt_id,line));
            CREATE TABLE IF NOT EXISTS rules(name TEXT PRIMARY KEY,category_id INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS ocr_runs(id INTEGER PRIMARY KEY,receipt_id INTEGER NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,raw TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS drive_files(file_id TEXT PRIMARY KEY,receipt_id INTEGER NOT NULL);''')
            if not db.execute('SELECT 1 FROM categories').fetchone():
                db.executemany('INSERT INTO categories(name,description) VALUES(?,?)',SEEDS)
            cols={r[1] for r in db.execute('PRAGMA table_info(categories)')}
            food="(name LIKE '食料品%' OR name='おやつ')"
            if 'tax_rate' not in cols:
                db.execute('ALTER TABLE categories ADD COLUMN tax_rate INTEGER CHECK(tax_rate IN (8,10))')
                db.execute(f'UPDATE categories SET tax_rate=CASE WHEN {food} THEN 8 ELSE 10 END')
            if 'ok_discount_eligible' not in cols:
                db.execute('ALTER TABLE categories ADD COLUMN ok_discount_eligible INTEGER NOT NULL DEFAULT 0 CHECK(ok_discount_eligible IN (0,1))')
                db.execute(f'UPDATE categories SET ok_discount_eligible=CASE WHEN {food} THEN 1 ELSE 0 END')
    @contextmanager
    def db(self):
        with self.lock:
            db=sqlite3.connect(self.root/'ledger.sqlite3'); db.row_factory=sqlite3.Row
            try:
                with db: yield db
            finally: db.close()
    def receipt(self,rid):
        with self.db() as db: row=db.execute('SELECT * FROM receipts WHERE id=?',(rid,)).fetchone()
        if not row: raise HTTPException(404,'レシートがありません')
        r=dict(row); r.update(json.loads(r.pop('body'))); r['warnings']=json.loads(r['warnings']); return r

def create_app(root=None):
    app=FastAPI(); store=Store(root or Path(__file__).parent/'data'); app.state.store=store
    install_validation(app)
    @app.get('/api/categories')
    def categories():
        with store.db() as db: return [dict(r) for r in db.execute('SELECT * FROM categories ORDER BY id')]
    @app.get('/api/receipts')
    def receipts():
        with store.db() as db: ids=[r[0] for r in db.execute('SELECT id FROM receipts ORDER BY id DESC')]
        return [store.receipt(i) for i in ids]
    @app.get('/api/input-suggestions')
    def input_suggestions():
        with store.db() as db:
            items = [dict(r) for r in db.execute('SELECT name,category_id FROM rules ORDER BY name')]
            stores = list(dict.fromkeys(
                json.loads(r['body']).get('store', '').strip()
                for r in db.execute("SELECT body FROM receipts WHERE status='confirmed' ORDER BY id DESC")
            ))
        return {'items': items, 'stores': [name for name in stores if name][:100]}
    @app.post('/api/receipts')
    def create():
        with store.db() as db: rid=db.execute('INSERT INTO receipts(body) VALUES(?)',(Review().model_dump_json(),)).lastrowid
        return store.receipt(rid)
    @app.get('/api/receipts/{rid}')
    def get(rid:int): return store.receipt(rid)
    @app.put('/api/receipts/{rid}')
    def save(rid:int,body:Review):
        with store.db() as db:
            if store.receipt(rid)['status']!='draft': raise HTTPException(409,'再編集を押してください')
            old=Review.model_validate(store.receipt(rid))
            if old.allocation_method=='category-tax-v1':
                before=old.model_dump(exclude={'reviewed','allocation_approved'})
                after=body.model_dump(exclude={'reviewed','allocation_approved'})
                # The UI clears both checks when editing. Explicitly checking
                # them again may approve a manual amount in the same save.
                # Changes to calculation inputs still force reapproval.
                if len(before['items'])==len(after['items']):
                    for previous,updated in zip(before['items'],after['items']):
                        if updated['amount_source']=='manual':
                            for key in ('amount','amount_source'): updated[key]=previous[key]
                if before!=after:
                    body.reviewed=False; body.allocation_approved=False
            db.execute('UPDATE receipts SET body=? WHERE id=?',(body.model_dump_json(),rid))
        return store.receipt(rid)
    from tax_rules import calculate
    @app.post('/api/receipts/{rid}/tax-preview')
    def tax_preview(rid:int):
        r=store.receipt(rid)
        if r['status']!='draft': raise HTTPException(409,'再編集を押してください')
        return calculate(Review.model_validate(r),categories())
    @app.post('/api/receipts/{rid}/tax-apply')
    def tax_apply(rid:int,request:dict):
        with store.db() as db:
            body=tax_preview(rid)
            if request.get('signature')!=body.calculation['signature']: raise HTTPException(409,'入力・分類設定が変わりました。案を再表示してください')
            db.execute('UPDATE receipts SET body=? WHERE id=?',(body.model_dump_json(),rid))
        return store.receipt(rid)
    @app.post('/api/receipts/{rid}/allocation-preview')
    def allocation_preview(rid:int):
        r=store.receipt(rid)
        if r['status']!='draft': raise HTTPException(409,'再編集を押してください')
        return allocate(Review.model_validate(r))
    @app.post('/api/receipts/{rid}/allocate')
    def allocation(rid:int):
        with store.db() as db:
            r=store.receipt(rid)
            if r['status']!='draft': raise HTTPException(409,'再編集を押してください')
            body=allocate(Review.model_validate(r))
            warnings=r['warnings']
            note='割引・税金は、レシートに書かれた総額を商品金額に応じて分けて計算しています。お店の計算とは端数がずれる場合があります。レシートと比べて確認してください。'
            if note not in warnings: warnings.append(note)
            db.execute('UPDATE receipts SET body=?,warnings=? WHERE id=?',(body.model_dump_json(),json.dumps(warnings,ensure_ascii=False),rid))
        return store.receipt(rid)
    @app.post('/api/receipts/{rid}/confirm')
    def confirm(rid:int):
        with store.db() as db:
            r=store.receipt(rid)
            errors=[]; fields=[]
            def issue(detail, loc, guidance=None, derived=False):
                errors.append(detail); fields.append(field(loc,guidance or detail,derived))
            try:
                if date.fromisoformat(r['date']).isoformat()!=r['date']: raise ValueError()
            except ValueError: issue('日付を YYYY-MM-DD で入力してください',['date'])
            if not r['store'].strip(): issue('店名を入力してください',['store'])
            if not r['reviewed']: issue('画像・税込金額・不確実箇所の確認が必要です',['reviewed'])
            ids={c['id'] for c in categories()}
            if not r['items'] or any(not i['name'].strip() or i['amount'] is None or i['category_id'] not in ids for i in r['items']):
                errors.append('全明細に商品名・分類・整数円が必要です')
                if not r['items']: fields.append(field(['items'],'明細を追加してください'))
                for n,i in enumerate(r['items']):
                    for key,invalid,text in [('name',not i['name'].strip(),'商品名を入力してください'),('category_id',i['category_id'] not in ids,'分類を選択してください'),('amount',i['amount'] is None,'税込明細額を整数円で入力してください。不明なら下書き保存してください')]:
                        if invalid: fields.append(field(['items',n,key],text))
            if r['total'] is None or sum(i['amount'] or 0 for i in r['items'])!=r['total']: issue('明細合計とレシート合計が一致しません',['total'],'印字合計と明細・税率・割引を照合してください。不明価格を差額で埋めないでください',True)
            if r.get('tax_exclusive') or any(i.get('amount_source')=='calculated' for i in r['items']):
                expected=calculate(Review.model_validate(r),categories()) if r.get('allocation_method')=='category-tax-v1' else allocate(Review.model_validate(r))
                if r.get('allocation_method')=='category-tax-v1' and r.get('calculation')!=expected.calculation: issue('分類設定や計算元が変わっています。再計算してください',['calculation'],derived=True)
                if not r.get('allocation_approved'): issue('割引・税金の計算結果を確認して、確認チェックを付けてください',['allocation_approved'])
                for actual,calculated in zip(r['items'],expected.items):
                    # A reviewed manual amount overrides the estimate, while the
                    # source signature and original allocations must remain valid.
                    keys=('allocated_discount','allocated_tax') if actual.get('amount_source')=='manual' else ('amount','allocated_discount','allocated_tax','amount_source')
                    if any(actual.get(key)!=getattr(calculated,key) for key in keys): issue('計算に使う金額や結果が変わっています。もう一度計算してください',['calculation' if r.get('allocation_method')=='category-tax-v1' else 'allocation_method'],derived=True); break
            if errors: raise FieldError(' / '.join(errors),fields)
            db.execute("UPDATE receipts SET status='confirmed' WHERE id=?",(rid,))
            db.execute('DELETE FROM entries WHERE receipt_id=?',(rid,))
            db.executemany('INSERT INTO entries VALUES(?,?,?,?)',[(rid,n,i['category_id'],i['amount']) for n,i in enumerate(r['items'])])
            for item in r['items']: db.execute('INSERT OR REPLACE INTO rules VALUES(?,?)',(item['name'],item['category_id']))
        return store.receipt(rid)
    @app.post('/api/receipts/{rid}/reopen')
    def reopen(rid:int):
        with store.db() as db:
            r=store.receipt(rid); r['reviewed']=False
            db.execute('DELETE FROM entries WHERE receipt_id=?',(rid,))
            db.execute("UPDATE receipts SET status='draft',body=? WHERE id=?",(Review.model_validate(r).model_dump_json(),rid))
        return store.receipt(rid)
    install_reports(app,store)
    from media import install_media
    install_media(app,store)
    import local_ocr
    local_ocr.install_local_ocr(app,store)
    from providers import install_providers
    install_providers(app,store)
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
    static=Path(__file__).parent/'static'
    app.mount('/static',StaticFiles(directory=static),name='static')
    @app.get('/')
    def index(): return FileResponse(static/'index.html')
    return app

class Category(BaseModel):
    name: str = Field(min_length=1,max_length=100)
    description: str = Field(max_length=2000)
    tax_rate: Literal[8,10] | None = None
    ok_discount_eligible: StrictBool = False

def install_reports(app,store):
    import calendar, re, io, csv, zipfile, tempfile
    from fastapi.responses import Response
    @app.post('/api/categories')
    def add_category(body:Category):
        return category_write(body)
    @app.put('/api/categories/{cid}')
    def edit_category(cid:int,body:Category):
        return category_write(body,cid)
    def category_write(body,cid=None):
        if not body.name.strip(): raise FieldError('分類名が空です',[field(['name'],'分類名を入力してください')])
        try:
            with store.db() as db:
                if cid is None:
                    cid=db.execute('INSERT INTO categories(name,description,tax_rate,ok_discount_eligible) VALUES(?,?,?,?)',(body.name,body.description,body.tax_rate,body.ok_discount_eligible)).lastrowid
                else:
                    old=db.execute('SELECT * FROM categories WHERE id=?',(cid,)).fetchone()
                    if not old: raise HTTPException(404,'分類なし')
                    if 'tax_rate' not in body.model_fields_set: body.tax_rate=old['tax_rate']
                    if 'ok_discount_eligible' not in body.model_fields_set: body.ok_discount_eligible=bool(old['ok_discount_eligible'])
                    db.execute('UPDATE categories SET name=?,description=?,tax_rate=?,ok_discount_eligible=? WHERE id=?',(body.name,body.description,body.tax_rate,body.ok_discount_eligible,cid))
                    if old['tax_rate']!=body.tax_rate or bool(old['ok_discount_eligible'])!=body.ok_discount_eligible:
                        for row in db.execute("SELECT id,body FROM receipts WHERE status='draft'").fetchall():
                            receipt=Review.model_validate_json(row['body'])
                            if receipt.allocation_method=='category-tax-v1' and any(i.category_id==cid for i in receipt.items):
                                receipt.reviewed=False; receipt.allocation_approved=False
                                db.execute('UPDATE receipts SET body=? WHERE id=?',(receipt.model_dump_json(),row['id']))
            return {'id':cid,**body.model_dump()}
        except sqlite3.IntegrityError: raise FieldError('同名の分類があります',[field(['name'],'別の分類名にしてください')],409)
    def rows(month):
        if not re.fullmatch(r'\d{4}-\d{2}',month): raise HTTPException(422,'年月は YYYY-MM')
        try: start=date.fromisoformat(month+'-01')
        except ValueError: raise HTTPException(422,'年月が不正です')
        with store.db() as db: ids=[r[0] for r in db.execute("SELECT id FROM receipts WHERE status='confirmed'")]
        return start,[r for i in ids if (r:=store.receipt(i))['date'].startswith(month+'-')]
    @app.get('/api/dashboard')
    def dashboard(month:str):
        start,receipts=rows(month)
        with store.db() as db: cats=[dict(c) for c in db.execute('SELECT * FROM categories ORDER BY id')]
        totals={str(c['id']):0 for c in cats}
        days=[{'date':f'{month}-{d:02d}','total':0,'categories':totals.copy()} for d in range(1,calendar.monthrange(start.year,start.month)[1]+1)]
        for r in receipts:
            day=days[int(r['date'][-2:])-1]
            for i in r['items']:
                key=str(i['category_id']); totals[key]+=i['amount']; day['categories'][key]+=i['amount']; day['total']+=i['amount']
        return {'total':sum(totals.values()),'categories':[{**c,'total':totals[str(c['id'])]} for c in cats],'days':days}
    @app.get('/api/export.csv')
    def export(month:str):
        _,receipts=rows(month)
        with store.db() as db: cats={c['id']:c['name'] for c in db.execute('SELECT * FROM categories')}
        def safe(v):
            s=str(v)
            return "'"+s if s.lstrip().startswith(('=','+','-','@','\t','\r','\n')) or s.startswith(('\t','\r','\n')) else s
        output=io.StringIO(); writer=csv.writer(output); writer.writerow(['日付','店名','商品名','分類','税込金額（円）'])
        for r in receipts:
            for i in r['items']: writer.writerow([safe(v) for v in (r['date'],r['store'],i['name'],cats[i['category_id']],i['amount'])])
        return Response('\ufeff'+output.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename={month}.csv'})
    @app.get('/api/backup')
    def backup():
        output=io.BytesIO()
        with store.lock, tempfile.TemporaryDirectory() as td:
            target=Path(td)/'ledger.sqlite3'
            with store.db() as source, sqlite3.connect(target) as dest: source.backup(dest)
            with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
                z.write(target,'ledger.sqlite3')
                for image in (store.root/'images').glob('*.jpg'): z.write(image,'images/'+image.name)
        return Response(output.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename=receipt-ledger-backup.zip'})
