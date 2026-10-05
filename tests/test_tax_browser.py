import os, socket, subprocess, time
import httpx
from playwright.sync_api import sync_playwright, expect
from test_browser import ROOT

def test_tax_rule_browser(tmp_path):
    with socket.socket() as s:
        s.bind(('127.0.0.1',0)); port=s.getsockname()[1]
    env={**os.environ,'LEDGER_DATA_DIR':str(tmp_path),'LEDGER_PORT':str(port)}
    process=subprocess.Popen([str(ROOT/'.venv/bin/python'),'server.py'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                if httpx.get(f'http://127.0.0.1:{port}/').status_code==200: break
            except httpx.ConnectError: pass
            time.sleep(.1)
        with sync_playwright() as p:
            browser=p.chromium.launch(); page=browser.new_page(); errors=[]
            page.on('pageerror',lambda e: errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{port}/')
            page.get_by_role('button',name='レシート',exact=True).click()
            page.locator('#manual').click()
            page.locator('#receipt-date').fill('2026-10-03'); page.locator('#store').fill('オーケー 梅屋敷店')
            page.locator('#tax-exclusive').check()
            assert page.locator('#tax-calculate').count()==1, 'automatic tax UI missing'
            page.get_by_label('商品名',exact=True).fill('肉')
            page.get_by_label('分類',exact=True).select_option('1')
            page.locator('#tax-exclusive').check()
            page.get_by_label('税抜明細額',exact=True).fill('1030')
            page.locator('#total').fill('1080')
            page.locator('#ok-discount-mode').select_option('formula')
            page.locator('#tax-calculate').click()
            expect(page.locator('#tax-preview')).to_contain_text('1,080')
            expect(page.get_by_label('税込円',exact=True)).to_have_value('')
            page.locator('#tax-apply').click()
            expect(page.get_by_label('税込円',exact=True)).to_have_value('1080')
            page.reload(); page.get_by_role('button',name='レシート',exact=True).click(); page.locator('.receipt-card').click()
            expect(page.locator('#ok-discount-mode')).to_have_value('formula')
            expect(page.locator('#allocate')).to_be_hidden()
            expect(page.locator('#allocation-approved')).to_be_visible()
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            (ROOT/'artifacts/ui-clarity').mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(ROOT/'artifacts/ui-clarity/mobile-auto-tax.png'),full_page=True)
            page.set_viewport_size({'width':1280,'height':1000})
            page.screenshot(path=str(ROOT/'artifacts/ui-clarity/desktop-auto-tax.png'),full_page=True)
            page.locator('#allocation-approved').check(); page.locator('#reviewed').check(); page.locator('#confirm').click()
            expect(page.locator('#receipt-status')).to_have_text('確定済み')
            page.get_by_role('button',name='分類・設定').click()
            expect(page.get_by_label('カテゴリ税率').first).to_have_value('8')
            page.get_by_label('カテゴリ税率').first.select_option('10')
            page.locator('.category-editor button').first.click()
            expect(page.locator('#message')).to_contain_text('分類を保存')
            expect(page.get_by_label('カテゴリ税率').first).to_have_value('10')
            assert not errors
            browser.close()
    finally:
        process.terminate(); process.wait(timeout=10)
