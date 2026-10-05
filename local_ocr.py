"""Japanese PaddleOCR on the local CPU; no remote OCR provider."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
OCR_TIMEOUT = 300

class LocalOCRError(Exception):
    pass


def availability():
    ready = all(importlib.util.find_spec(name) is not None for name in ('paddleocr', 'paddle'))
    return {'available': ready, 'engine': 'PaddleOCR', 'message':
            'PaddleOCR / 日本語 / CPU。画像はこの端末内で処理します。初回は認識モデルをダウンロード（ネット接続が必要）。最大300秒。'
            if ready else 'PaddleOCRが未導入です。uv sync --frozen を実行し、サーバーを再起動してください。手入力もできます。'}


def recognize(image, images_root):
    image, images_root = Path(image), Path(images_root).resolve()
    if (image.is_symlink() or image.resolve().parent != images_root
            or not re.fullmatch(r'[a-f0-9]{64}\.jpg', image.name) or not image.is_file()):
        raise LocalOCRError('アプリ内の保存済み画像だけ読み取れます。')
    if not availability()['available']:
        raise LocalOCRError(availability()['message'])
    # Isolate native inference and model initialization so timeouts stop the work.
    cache = ROOT/'artifacts'/'paddleocr-cache'
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    env = {**os.environ, 'PADDLE_PDX_CACHE_HOME': str(cache),
           'PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK': 'True',
           'HF_HOME': str(cache/'huggingface'), 'MODELSCOPE_CACHE': str(cache/'modelscope')}
    try:
        result = subprocess.run([sys.executable, str(ROOT/'paddle_ocr_worker.py'), str(image.resolve())],
                                check=True, capture_output=True, text=True,
                                timeout=OCR_TIMEOUT, env=env)
        # Paddle dependencies may log to stdout. Only accept our marked JSON line.
        output = next(line[len('LEDGER_OCR_RESULT='):] for line in reversed(result.stdout.splitlines())
                      if line.startswith('LEDGER_OCR_RESULT='))
        raw = json.loads(output)
        if not isinstance(raw, dict) or not isinstance(raw.get('lines'), list): raise ValueError()
        if len(raw['lines']) > 5000: raise ValueError()
        for line in raw['lines']:
            if not isinstance(line, dict) or not isinstance(line.get('text'), str): raise ValueError()
        return raw
    except subprocess.TimeoutExpired:
        raise LocalOCRError('PaddleOCRが300秒でタイムアウトしました。初回モデル取得のネット接続を確認するか、手入力してください。') from None
    except (OSError, subprocess.SubprocessError, ValueError, StopIteration):
        raise LocalOCRError('PaddleOCRで読み取れませんでした。依存パッケージと初回モデル取得のネット接続を確認し、手入力または画像を撮り直してください。') from None


def parse_receipt(raw, rules=None):
    """Heuristic transcription only; confidence is NOT a probability of correctness.

    Deskew text-box centres before joining columns. Never fill missing prices
    from unit prices, totals or other lines. Exact-name rules only.
    """
    import statistics
    import unicodedata
    from datetime import date
    rules = rules or {}
    lines = raw['lines']
    slopes = [l.get('slope',0) for l in lines if l.get('width',0)>.18 and .002<abs(l.get('slope',0))<.15]
    slope = statistics.median(slopes) if slopes else 0
    located = []
    for l in lines:
        text = unicodedata.normalize('NFKC',l['text']).strip()
        y = l.get('y',0)+l.get('height',.012)/2-slope*(l.get('x',0)+l.get('width',0)/2)
        located.append({**l,'text':text,'row_y':y})
    rows = []
    for l in sorted(located,key=lambda l:l['row_y']):
        # Less than half a typical line height: adjacent receipt lines must not merge.
        if rows and abs(l['row_y']-statistics.mean(x['row_y'] for x in rows[-1]))<.006:
            rows[-1].append(l)
        else: rows.append([l])
    rows = [sorted(row,key=lambda l:l.get('x',0)) for row in rows]
    texts = [' '.join(l['text'] for l in row) for row in rows]
    result = dict(date='',store='',total=None,items=[],reviewed=False,
        tax_exclusive=True,tax_rates=[],pre_discount_total=None,discount_total=None,
        tax_total=None,quantity_total=None,subtotal=None,
        warnings=['無料OCRは文字転記と簡易解析です。店名・商品名・金額・数量を画像と照合してください。低信頼の明細価格は空欄です。分類は過去の完全一致ルールだけ使用し、未知の商品は未分類です。',
                  '税込明細額と全商品共通の税率は自動確定しません。印字税抜額を確認し、手動入力または明示的な配賦が必要です。数量表記がない商品行は1として仮置きします。'])
    date_row = None
    for index,text in enumerate(texts):
        match = re.search(r'(20\d{2})[年/.-](\d{1,2})[月/.-](\d{1,2})日?',text)
        if match:
            try: result['date']=date(*map(int,match.groups())).isoformat(); date_row=index; break
            except ValueError: pass
    for text in texts[:date_row if date_row is not None else 0]:
        if re.search(r'[^\s]+店(?:\s|$)',text) and not re.search(r'事業者|番号|会員|営業時間',text):
            result['store']=text[:500]
    money = re.compile(r'^[¥￥]([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)$')
    def price(row, strict=False):
        values=[]
        for l in row:
            tokens=l['text'].split()
            token=tokens[-1] if tokens else ''
            m=money.fullmatch(token)
            if m and (not strict or l.get('confidence',0)>.5):
                value=int(m[1].replace(',',''))
                if value<=100000000: values.append(value)
        return values[0] if len(values)==1 else None
    end = len(rows)
    seen_totals = {}
    taxes = []
    for index,(row,text) in enumerate(zip(rows,texts)):
        compact=text.replace(' ','')
        field=None
        if re.match(r'割引前合計',compact): field='pre_discount_total'
        elif re.match(r'小計',compact): field='subtotal'
        elif re.match(r'合計',compact): field='total'
        if field:
            end=min(end,index)
            seen_totals.setdefault(field,[]).append(price(row))
            values=seen_totals[field]
            result[field]=values[0] if all(v==values[0] for v in values) else None
            if result[field] is None: result['warnings'].append(text+'：金額の区切りや位置が不確実なため空欄です。')
        if index >= end:
            if '割引' in text:
                negative=[re.fullmatch(r'[-−]([0-9]+)',l['text']) for l in row]
                values=[int(m[1]) for m in negative if m]
                if len(values)==1: result['discount_total']=values[0]
            for l in row:
                m=re.fullmatch(r'(?:消費税|外税|税)\s*[¥￥]?\s*([0-9,]+)',l['text'])
                if m: taxes.append(int(m[1].replace(',','')))
                m=re.fullmatch(r'(\d+)点',l['text'])
                if m: result['quantity_total']=int(m[1]) or None
    result['tax_total']=taxes[0] if len(taxes)==1 else None
    if len(taxes)>1: result['warnings'].append('複数の税額を認識しました。税総額は自動選択・合算せず空欄にします。')
    # Only store explicitly tax-exclusive prices; unknown price basis stays empty.
    exclusive = any('税抜' in t or '外税' in t for t in texts)
    if date_row is not None:
        for row,text in zip(rows[date_row+1:end],texts[date_row+1:end]):
            quantity=re.search(r'(\d+)\s*(?:コ|個|点)\s*[Xx×]\s*単',text)
            if quantity and result['items']:
                last=result['items'][-1]
                last['quantity']=int(quantity[1]) if 1<=int(quantity[1])<=10000 else None
                if last['pre_tax'] is None and exclusive: last['pre_tax']=price(row,True)
                continue
            candidates=[]
            for l in row:
                t=l['text']
                if re.search(r'[ぁ-んァ-ヶ一-龠]',t) and not re.search(r'レジ|No|番号|割引|点$|対象|単[0-9]|^[¥￥]',t,re.I):
                    candidates.append(re.sub(r'\s+[¥￥][0-9,.]+$','',t))
            if not candidates: continue
            name=' '.join(candidates)
            # A product marker permits retaining unpriced names. Unmarked names
            # require an explicit price on the same row; metadata is not an item.
            if not re.match(r'^F(?=[ァ-ヶA-Za-z0-9一-龠])',name) and price(row) is None: continue
            name=re.sub(r'^F(?=[ァ-ヶA-Za-z0-9一-龠])','',name)[:500]
            result['items'].append(dict(name=name,category_id=rules.get(name),amount=None,
                pre_tax=price(row,True) if exclusive else None,quantity=1))
    if not result['items']: result['warnings'].append('明細の位置・形式を解析できませんでした。原文を見て手入力してください。')
    for item in result['items']:
        if item['pre_tax'] is None: result['warnings'].append(item['name']+'：税抜明細額は不明（逆算しません）。')
    return result


def install_local_ocr(app, store):
    from fastapi import HTTPException
    @app.post('/api/receipts/{rid}/ocr/local')
    def local_ocr(rid: int):
        from ledger import Review
        with store.lock:
            receipt=store.receipt(rid)
            if receipt['status']!='draft' or not receipt['image']:
                raise HTTPException(409,'画像付き下書きが必要です')
            try:
                raw=recognize(store.root/'images'/receipt['image'],store.root/'images')
            except LocalOCRError as exc:
                raise HTTPException(503,str(exc)) from None
            raw={**raw,'engine':'PaddleOCR','text':'\n'.join(l['text'] for l in raw['lines'])}
            serialized=json.dumps(raw,ensure_ascii=False)
            with store.db() as db:
                db.execute('UPDATE receipts SET raw=? WHERE id=?',(serialized,rid))
                db.execute('INSERT INTO ocr_runs(receipt_id,raw) VALUES(?,?)',(rid,serialized))
                rules=dict(db.execute('SELECT name,category_id FROM rules').fetchall())
            try:
                parsed=parse_receipt(raw,rules)
                body=Review.model_validate(parsed)
            except Exception:
                raise HTTPException(422,'無料OCRの原文は保存しましたが、明細を解析できませんでした。原文を見て手入力してください。') from None
            with store.db() as db:
                db.execute('UPDATE receipts SET body=?,warnings=? WHERE id=?',
                    (body.model_dump_json(),json.dumps(parsed['warnings'],ensure_ascii=False),rid))
        return store.receipt(rid)
