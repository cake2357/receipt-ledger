from test_app import client
import io
from PIL import Image

def png():
    b=io.BytesIO(); Image.new('RGB',(20,30),'white').save(b,format='PNG'); return b.getvalue()

def test_upload_dedup_and_protection(client):
    a=client.post('/api/upload',files={'file':('r.png',png(),'image/png')})
    assert a.status_code==200
    r=a.json(); assert r['status']=='draft'
    assert client.post('/api/upload',files={'file':('other.png',png(),'image/png')}).json()['id']==r['id']
    assert client.get(f"/api/receipts/{r['id']}/image").headers['content-type']=='image/jpeg'
    assert client.post('/api/upload',files={'file':('x.png',b'not image','image/png')}).status_code==415
    assert client.post('/api/upload',files={'file':('x.svg',b'<svg/>','image/svg+xml')}).status_code==415
    assert client.post('/api/upload',files={'file':('big.png',b'x'*(12*1024*1024+1),'image/png')}).status_code==413
    assert client.post('/api/receipts',headers={'Origin':'https://evil.test'}).status_code==403
    assert client.get('/api/receipts',headers={'Host':'evil.test'}).status_code==403
    assert client.post('/api/receipts',headers={'Origin':'null'}).status_code==403
    assert client.get('/api/receipts/999/image').status_code==404
