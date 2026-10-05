from test_app import client

def test_frontend_is_served_and_local_only(client):
    r=client.get('/')
    assert r.status_code==200 and 'レシート家計簿' in r.text
    assert 'app.js' in r.text
    js=client.get('/static/app.js'); assert js.status_code==200 and 'innerHTML' not in js.text
    assert "frame-ancestors 'none'" in r.headers['content-security-policy']
