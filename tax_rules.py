"""User-configured bookkeeping estimates; never replace printed observations."""
import hashlib
import json
from fastapi import HTTPException
from validation import FieldError, field


def distribute(total, values):
    denominator=sum(values)
    if not denominator:
        if total: raise HTTPException(422,'対象額が0のため割引を配賦できません')
        return [0]*len(values)
    result=[total*v//denominator for v in values]
    order=sorted(range(len(values)),key=lambda i:(-(total*values[i]%denominator),i))
    for i in order[:total-sum(result)]: result[i]+=1
    return result


def calculate(body, categories):
    if not body.tax_exclusive: raise FieldError('税込レシートには課税しません。税抜額を確認して税別を選択してください',[field(['tax_exclusive'],'税抜表示か確認し、税別レシートを選択してください')])
    if not body.items or any(i.pre_tax is None for i in body.items): raise FieldError('不明な税抜明細額があります。差額から補完しません',[field(['items',n,'pre_tax'],'税抜明細額を入力してください') for n,i in enumerate(body.items) if i.pre_tax is None] or [field(['items'],'明細を追加してください')])
    if any(i.quantity is None for i in body.items): raise FieldError('数量を確認してください',[field(['items',n,'quantity'],'数量を入力してください') for n,i in enumerate(body.items) if i.quantity is None])
    cats={c['id']:c for c in categories}
    rules=[]
    for n,item in enumerate(body.items):
        cat=cats.get(item.category_id,{})
        rate=item.tax_rate if item.tax_rate is not None else cat.get('tax_rate')
        eligible=item.ok_discount_eligible if item.ok_discount_eligible is not None else cat.get('ok_discount_eligible')
        if rate not in (8,10) or eligible is None: raise FieldError('分類の税率・割引対象を設定するか明細で指定してください',[field(['items',n,'category_id'],'分類の税率・割引対象を設定するか、明細で指定してください')])
        rules.append({'tax_rate':rate,'ok_discount_eligible':bool(eligible)})
    weights=[i.pre_tax for i in body.items]
    eligible_weights=[w if r['ok_discount_eligible'] else 0 for w,r in zip(weights,rules)]
    discount=0
    if body.ok_discount_mode=='formula': discount=sum(eligible_weights)*3//103
    elif body.ok_discount_mode=='printed':
        discount=body.discount_total
        if discount is None or discount>sum(eligible_weights): raise FieldError('印字割引額が不明、または指定した対象額を超えています。対象を確認してください',[field(['discount_total'],'印字割引額と対象商品の設定を確認してください',True)])
    discounts=distribute(discount,eligible_weights)
    taxes=[0]*len(weights)
    groups=[]
    for rate in (8,10):
        indices=[i for i,r in enumerate(rules) if r['tax_rate']==rate]
        values=[weights[i]-discounts[i] for i in indices]
        tax=sum(values)*rate//100
        for i,t in zip(indices,distribute(tax,values)): taxes[i]=t
        if indices: groups.append({'tax_rate':rate,'taxable':sum(values),'tax':tax})
    source=body.model_dump(exclude={'reviewed','allocation_approved','allocation_method','calculation'})
    for item in source['items']:
        for key in ('amount','allocated_discount','allocated_tax','amount_source'): item.pop(key,None)
    signature=hashlib.sha256(json.dumps({'source':source,'rules':rules},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    out=body.model_copy(deep=True)
    for n,item in enumerate(out.items):
        item.allocated_discount=discounts[n]; item.allocated_tax=taxes[n]
        item.amount=weights[n]-discounts[n]+taxes[n]; item.amount_source='calculated'
    out.reviewed=False; out.allocation_approved=False; out.allocation_method='category-tax-v1'
    out.calculation={'signature':signature,'rules':rules,'groups':groups,'discount_total':sum(discounts),'tax_total':sum(taxes),'total':sum(i.amount for i in out.items)}
    return out
