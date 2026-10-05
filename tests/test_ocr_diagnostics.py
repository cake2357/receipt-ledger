"""Synthetic images and MockTransport only; never contact a provider."""
import httpx
import pytest
import providers
from test_app import client
from test_upload import png

SECRET = 'sk-test-secret-NEVER-EXPOSE'
PRIVATE = 'private receipt text NEVER EXPOSE'

@pytest.fixture
def ocr(client, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', SECRET)
    monkeypatch.setenv('OPENAI_MODEL', 'literal-test-model')
    client.put('/api/settings', json={'ocr_consent': True})
    receipt = client.post('/api/upload', files={'file': ('r.png', png(), 'image/png')}).json()
    original = providers.extract
    def run(handler):
        calls = []
        def dispatch(request):
            calls.append(request)
            return handler(request)
        with httpx.Client(transport=httpx.MockTransport(dispatch)) as transport:
            monkeypatch.setattr(providers, 'extract', lambda *args: original(*args, client=transport))
            response = client.post(f"/api/receipts/{receipt['id']}/ocr")
        assert len(calls) == 1
        assert response.status_code == 502
        detail = response.json()['detail']
        assert isinstance(detail, str)
        assert SECRET not in detail and PRIVATE not in detail
        assert '自動再試行はしません' in detail
        return detail
    return run

@pytest.mark.parametrize('status,code,category', [
    (401, 'invalid_api_key', 'authentication'),
    (403, 'permission_denied', 'permission'),
    (429, 'insufficient_quota', 'quota'),
    (429, 'project_spend_limit_exceeded', 'quota'),
    (429, 'organization_usage_limit_exceeded', 'quota'),
    (429, 'organization_spend_limit_exceeded', 'quota'),
    (429, 'credit_balance_exhausted', 'quota'),
    (429, 'rate_limit_exceeded', 'rate_limit'),
    (429, None, 'unknown_429'),
    (404, 'model_not_found', 'model'),
    (400, 'unsupported_model', 'model'),
    (400, 'unsupported_parameter', 'invalid_request'),
    (400, None, 'invalid_request'),
    (500, 'server_error', 'upstream'),
])
def test_http_diagnostics(ocr, status, code, category):
    detail = ocr(lambda req: httpx.Response(status, headers={'x-request-id': 'req_test123'},
        json={'error': {'code': code, 'message': SECRET + PRIVATE, 'param': PRIVATE}}))
    assert f'OCR[{category}]' in detail
    assert f'HTTP {status}' in detail
    assert 'request_id=req_test123' in detail
    if code:
        assert f'code={code}' in detail

@pytest.mark.parametrize('body', [{'error': {'code': SECRET, 'message': PRIVATE}}, {'error': [PRIVATE]}, [PRIVATE]])
def test_unknown_error_fields_not_exposed(ocr, body):
    detail = ocr(lambda req: httpx.Response(400, headers={'x-request-id': SECRET}, json=body))
    assert 'OCR[invalid_request]' in detail
    assert 'request_id=' not in detail

def test_non_json_http_error_is_classified(ocr):
    detail = ocr(lambda req: httpx.Response(502, text=SECRET + PRIVATE))
    assert 'OCR[upstream]' in detail and 'HTTP 502' in detail

@pytest.mark.parametrize('exception,category', [(httpx.ReadTimeout, 'timeout'), (httpx.ConnectError, 'network')])
def test_transport_diagnostics(ocr, exception, category):
    def fail(req):
        raise exception(SECRET + PRIVATE, request=req)
    assert f'OCR[{category}]' in ocr(fail)

@pytest.mark.parametrize('body,category', [
    ({'status': 'incomplete', 'incomplete_details': {'reason': 'max_output_tokens'}, 'output': []}, 'incomplete'),
    ({'status': 'completed', 'output': [{'content': [{'type': 'refusal', 'refusal': PRIVATE}]}]}, 'refusal'),
    ({'status': 'failed', 'error': {'code': 'server_error', 'message': PRIVATE}}, 'upstream'),
    ({'status': 'completed', 'output': []}, 'invalid_response'),
    ({'status': 'completed', 'output': [{'content': [{'type': 'output_text', 'text': PRIVATE}]}]}, 'invalid_response'),
    ([], 'invalid_response'),
])
def test_response_failure_diagnostics_and_history(ocr, client, body, category):
    detail = ocr(lambda req: httpx.Response(200, headers={'x-request-id': 'req_result123'}, json=body))
    assert f'OCR[{category}]' in detail
    assert 'HTTP 200' in detail and 'request_id=req_result123' in detail
    receipt = client.get('/api/receipts').json()[0]
    stored = client.get(f"/api/receipts/{receipt['id']}").json()
    assert stored['status'] == 'draft' and stored['raw']
    assert not stored['reviewed']

@pytest.mark.parametrize('request_id', ['private receipt', 'req_' + 'x' * 101, 'req_bad\tvalue'])
def test_invalid_request_id_is_omitted(ocr, request_id):
    detail = ocr(lambda req: httpx.Response(400, headers={'x-request-id': request_id}, json={}))
    assert 'request_id=' not in detail

@pytest.mark.parametrize('missing', ['OPENAI_API_KEY', 'OPENAI_MODEL', 'ocr_consent'])
def test_missing_settings_are_specific(client, monkeypatch, missing):
    monkeypatch.setenv('OPENAI_API_KEY', SECRET if missing != 'OPENAI_API_KEY' else ' ')
    monkeypatch.setenv('OPENAI_MODEL', 'literal-test-model' if missing != 'OPENAI_MODEL' else '')
    client.put('/api/settings', json={'ocr_consent': missing != 'ocr_consent'})
    settings = client.get('/api/settings').json()
    assert settings['ocr_ready'] is False
    assert settings['ocr_missing'] == [missing]
    detail = client.post('/api/receipts/1/ocr').json()['detail']
    assert missing in detail and SECRET not in detail


def test_non_json_success_is_invalid_response(ocr):
    detail = ocr(lambda req: httpx.Response(200, headers={'x-request-id': 'req_badjson'}, text=SECRET + PRIVATE))
    assert 'OCR[invalid_response]' in detail
    assert 'HTTP 200' in detail and 'request_id=req_badjson' in detail
