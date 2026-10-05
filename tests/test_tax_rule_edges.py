import pytest
from fastapi import HTTPException
from ledger import Review
from tax_rules import calculate

CATS=[{'id':1,'tax_rate':8,'ok_discount_eligible':True}]

def test_rounding_is_deterministic_and_conserves_yen():
    b=Review(tax_exclusive=True,ok_discount_mode='formula',items=[{'name':'食品','pre_tax':17,'category_id':1} for _ in range(9)])
    a=calculate(b,CATS); other=calculate(b,CATS)
    assert a==other
    assert sum(i.allocated_discount for i in a.items)==a.calculation['discount_total']
    assert sum(i.allocated_tax for i in a.items)==a.calculation['tax_total']
    assert sum(i.amount for i in a.items)==153-a.calculation['discount_total']+a.calculation['tax_total']

def test_zero_amount_works():
    a=calculate(Review(tax_exclusive=True,ok_discount_mode='formula',items=[{'pre_tax':0,'category_id':1}]),CATS)
    assert a.calculation['total']==0

@pytest.mark.parametrize('updates',[
    {'tax_exclusive':False},
    {'items':[{'pre_tax':None,'category_id':1}]},
    {'items':[{'pre_tax':100,'category_id':None}]},
    {'items':[{'pre_tax':100,'category_id':1,'quantity':None}]},
])
def test_unsafe_auto_calculation_rejected(updates):
    b={'tax_exclusive':True,'items':[{'pre_tax':100,'category_id':1}]};b.update(updates)
    with pytest.raises(HTTPException) as e: calculate(Review.model_validate(b),CATS)
    assert e.value.status_code==422
