import os
from pathlib import Path
from dotenv import load_dotenv
import uvicorn
from ledger import create_app

if __name__=='__main__':
    os.umask(0o077)
    root=Path(__file__).resolve().parent
    load_dotenv(root/'.env',override=False)
    app=create_app(Path(os.environ.get('LEDGER_DATA_DIR',root/'data')))
    uvicorn.run(app,host='127.0.0.1',port=int(os.environ.get('LEDGER_PORT','8765')),workers=1,proxy_headers=False)
