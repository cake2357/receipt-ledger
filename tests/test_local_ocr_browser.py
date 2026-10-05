"""Chromium exercises real local Vision, using a generated image only."""
import os, socket, subprocess, time
from pathlib import Path
import httpx
import pytest
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]

def test_free_local_ocr_browser(tmp_path):
    from local_ocr import availability
    if not availability()['available']: pytest.skip('Apple Vision needs macOS + CLT')
    from PIL import Image,ImageDraw,ImageFont
    image=Image.new('RGB',(1000,900),'white')
    draw=ImageDraw.Draw(image)
    font=ImageFont.truetype('/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc',40)
    for index,text in enumerate(['テスト商店','2026年04月03日','F牛肉             ¥200','割引前合計         ¥200','小計              ¥200','合計              ¥216','単品の価格は税抜です。']):
        draw.text((70,60+index*90),text,fill='black',font=font)
    fixture=tmp_path/'synthetic.png'; image.save(fixture)
    with socket.socket() as s: s.bind(('127.0.0.1',0)); port=s.getsockname()[1]
    # Empty env values prevent dotenv reintroducing production paid credentials.
    env={**os.environ,'LEDGER_DATA_DIR':str(tmp_path/'db'),'LEDGER_PORT':str(port),'OPENAI_API_KEY':'','OPENAI_MODEL':''}
    process=subprocess.Popen([str(ROOT/'.venv/bin/python'),'server.py'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    base=f'http://127.0.0.1:{port}'
    try:
        for _ in range(100):
            try:
                if httpx.get(base+'/').status_code==200: break
            except httpx.ConnectError: pass
            time.sleep(.1)
        with sync_playwright() as p:
            browser=p.chromium.launch(); page=browser.new_page();errors=[];external=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('request',lambda r:external.append(r.url) if not r.url.startswith(base) else None)
            page.goto(base)
            page.get_by_role('button',name='レシート',exact=True).click()
            # set_input_files bypasses actionability; wait for navigation's lock.
            expect(page.locator('#upload')).to_be_enabled()
            page.locator('#upload').set_input_files(str(fixture))
            button=page.get_by_role('button',name='画像から読み取る（無料）',exact=True)
            expect(button).to_be_visible(timeout=5000)
            expect(button).to_be_enabled()
            expect(page.get_by_role('button',name='AIで読み取る（有料）',exact=True)).to_be_disabled()
            page.on('dialog',lambda dialog:dialog.accept())
            button.click()
            expect(page.locator('#message')).to_contain_text('無料OCRの下書き',timeout=180000)
            expect(page.locator('#receipt-date')).to_have_value('2026-04-03')
            expect(page.locator('.receipt-card')).to_contain_text('2026-04-03')
            expect(page.locator('#store')).to_have_value('テスト商店')
            expect(page.locator('#reviewed')).not_to_be_checked()
            expect(page.locator('#receipt-status')).to_have_text('下書き')
            page.locator('#raw-text-details summary').click()
            expect(page.locator('#raw-text')).to_contain_text('2026年04月03日')
            page.screenshot(path=str(ROOT/'artifacts/local-ocr-review.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.screenshot(path=str(ROOT/'artifacts/local-ocr-mobile.png'),full_page=True)
            page.set_viewport_size({'width':1280,'height':900})
            page.locator('#store').fill('編集できる店'); page.locator('#save').click()
            expect(page.locator('#message')).to_contain_text('下書きを保存')
            page.reload();page.get_by_role('button',name='レシート',exact=True).click();page.locator('.receipt-card').click()
            expect(page.locator('#store')).to_have_value('編集できる店')
            page.get_by_role('button',name='分類・設定').click()
            expect(page.locator('#local-ocr-status')).to_contain_text('Apple Vision')
            assert httpx.get(base+'/api/settings').json()['ocr_consent'] is False
            assert httpx.get(base+'/api/settings').json()['key_present'] is False
            assert httpx.get(base+'/api/dashboard?month=2026-04').json()['total']==0
            page.screenshot(path=str(ROOT/'artifacts/local-ocr-browser.png'),full_page=True)
            assert not external and not errors
            browser.close()
    finally:
        process.terminate();process.wait(timeout=10)
