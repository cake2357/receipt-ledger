"""User-invoked only. Does not read any Hermes credential files."""
import os
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from providers import SCOPE

def authorize(root,flow_class=InstalledAppFlow):
    root=Path(root); root.mkdir(parents=True,exist_ok=True)
    path=root/'google-client.json'
    if not path.exists(): raise SystemExit('data/google-client.json に自分専用Desktop OAuthのJSONを置いてください。README参照。')
    flow=flow_class.from_client_secrets_file(str(path),scopes=[SCOPE],autogenerate_code_verifier=True)
    credentials=flow.run_local_server(host='127.0.0.1',port=0,open_browser=True,access_type='offline',prompt='consent',timeout_seconds=180)
    token=root/'google-token.json'
    fd=os.open(token,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as out: out.write(credentials.to_json())
    token.chmod(0o600)
    print('Google Drive 読み取り専用の認証を保存しました。')

if __name__=='__main__': authorize(Path(__file__).parent/'data')
