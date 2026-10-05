"""Optional local originals: never copy private photographs into fixtures."""
from pathlib import Path
import pytest
from test_app import client

@pytest.mark.parametrize('name',['IMG_0725.jpg','IMG_0726.jpg'])
def test_private_iphone_jpeg_upload(client,name):
    path=Path('/Users/yoshiki2357/Downloads')/name
    if not path.exists(): pytest.skip('private original not supplied on this machine')
    response=client.post('/api/upload',files={'file':(name,path.read_bytes(),'image/jpeg')})
    assert response.status_code==200, response.text
    r=response.json()
    assert r['status']=='draft' and r['items']==[] and r['raw'] is None
    assert client.get(f"/api/receipts/{r['id']}/image").status_code==200
    assert 'ocr_consent' not in client.get('/api/settings').json()
