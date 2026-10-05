import httpx
import pytest
from providers import ocr_http_detail

@pytest.mark.parametrize('error,expected', [
    ({'code': None, 'type': 'insufficient_quota'}, 'quota'),
    ({'code': None, 'type': 'rate_limit_exceeded'}, 'rate_limit'),
    ({'code': 'unknown', 'type': 'unknown'}, 'unknown_429'),
    ({'code': None, 'message': 'private secret'}, 'unknown_429'),
])
def test_429_requires_explicit_cause(error, expected):
    detail = ocr_http_detail(httpx.Response(429, json={'error': error}))
    assert f'OCR[{expected}]' in detail
    assert 'private secret' not in detail
    assert 'code=unknown' not in detail

@pytest.mark.parametrize('code,action', [
    ('credit_balance_exhausted', 'クレジットを追加'),
    ('project_spend_limit_exceeded', 'プロジェクトの利用制限'),
    ('organization_spend_limit_exceeded', '組織の利用制限'),
    ('organization_usage_limit_exceeded', '引き上げを申請'),
])
def test_specific_billing_cause_overrides_broad_type(code, action):
    detail = ocr_http_detail(httpx.Response(429, json={'error': {
        'code': code, 'type': 'insufficient_quota', 'message': 'private secret',
    }}))
    assert 'OCR[quota]' in detail
    assert f'code={code}' in detail and action in detail
    assert 'private secret' not in detail
