import importlib.util, json

def test_oauth_uses_own_credentials_readonly_and_loopback(tmp_path):
    assert importlib.util.find_spec('oauth_setup') is not None, 'OAuth setup missing'
    from oauth_setup import authorize
    (tmp_path/'google-client.json').write_text('{}')
    called={}
    class Flow:
        @classmethod
        def from_client_secrets_file(cls,path,scopes,**kwargs):
            called.update(path=path,scopes=scopes,kwargs=kwargs);return cls()
        def run_local_server(self,**kwargs):
            called['server']=kwargs
            class Creds:
                def to_json(self): return '{"token":"test-only"}'
            return Creds()
    authorize(tmp_path,Flow)
    assert called['path']==str(tmp_path/'google-client.json')
    assert called['scopes']==['https://www.googleapis.com/auth/drive.readonly']
    assert called['server']['host']=='127.0.0.1' and called['server']['port']==0
    assert called['kwargs']['autogenerate_code_verifier'] is True
    assert (tmp_path/'google-token.json').stat().st_mode & 0o777 == 0o600
