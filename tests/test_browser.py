"""Real Chromium + real uvicorn; disposable data only, no external calls."""
import os, socket, subprocess, time
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]

def test_browser_full_workflow(tmp_path):
    assert (ROOT/'server.py').exists(), 'launch entrypoint missing'
    with socket.socket() as s: s.bind(('127.0.0.1',0)); port=s.getsockname()[1]
    env={**os.environ,'LEDGER_DATA_DIR':str(tmp_path),'LEDGER_PORT':str(port)}
    env.pop('OPENAI_API_KEY',None)
    process=subprocess.Popen([str(ROOT/'.venv/bin/python'),'server.py'],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    try:
        for _ in range(100):
            try:
                if httpx.get(f'http://127.0.0.1:{port}/').status_code==200:break
            except httpx.ConnectError: pass
            time.sleep(.1)
        with sync_playwright() as p:
            browser=p.chromium.launch(); page=browser.new_page(viewport={'width':1280,'height':900}); errors=[]
            page.on('pageerror',lambda e: errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{port}/')
            assert page.evaluate('typeof trendScale')=='function', 'chart must handle negative discount totals'
            scale=page.evaluate('trendScale([-120,0,300])')
            assert scale['min']==-120 and scale['max']==300
            expect(page.locator('#monthly-total')).to_have_text('￥0')
            page.get_by_role('button',name='レシート',exact=True).click()
            page.get_by_role('button',name='手入力で追加').click()
            page.locator('#receipt-date').fill('2026-10-03');page.locator('#store').fill('テスト店')
            page.get_by_label('商品名',exact=True).fill('牛肉');page.get_by_label('分類',exact=True).select_option('1');page.get_by_label('税込円',exact=True).fill('120')
            page.locator('#total').fill('121');page.locator('#reviewed').check();page.locator('#confirm').click()
            expect(page.locator('#message')).to_contain_text('一致しません')
            expect(page.locator('#review-message')).to_contain_text('一致しません')
            expect(page.locator('#confirm')).to_be_enabled()
            page.locator('#total').fill('120');page.locator('#reviewed').check();page.locator('#save').click()
            expect(page.locator('#message')).to_contain_text('下書きを保存')
            page.reload();page.get_by_role('button',name='レシート',exact=True).click();page.locator('.receipt-card').click()
            expect(page.locator('#store')).to_have_value('テスト店');page.locator('#confirm').click()
            expect(page.locator('#receipt-status')).to_have_text('確定済み')
            page.get_by_role('button',name='家計の概要').click();page.locator('#month').fill('2026-10')
            expect(page.locator('#monthly-total')).to_have_text('￥120')
            expect(page.locator('#daily tr')).to_have_count(32)
            page.get_by_role('button',name='分類・設定').click();page.locator('.category-editor input').first.fill('精肉');page.locator('.category-editor textarea').first.fill('牛・豚・鶏');page.locator('.category-editor button').first.click()
            expect(page.locator('#message')).to_contain_text('分類を保存')
            page.get_by_role('button',name='レシート',exact=True).click();page.locator('.receipt-card').click();page.locator('#reopen').click()
            expect(page.locator('#receipt-status')).to_have_text('下書き')
            page.get_by_role('button',name='家計の概要').click();expect(page.locator('#monthly-total')).to_have_text('￥0')
            page.get_by_role('button',name='レシート',exact=True).click();page.locator('.receipt-card').click()
            expect(page.locator('#tax-exclusive')).to_be_visible()
            page.locator('#tax-exclusive').check()
            page.locator('#manual-allocation > summary').click()
            page.locator('#tax-rates').select_option('8')
            page.get_by_label('税抜明細額',exact=True).fill('100');page.get_by_label('数量',exact=True).fill('2')
            page.locator('#pre-discount-total').fill('100');page.locator('#discount-total').fill('3');page.locator('#tax-total').fill('7');page.locator('#quantity-total').fill('2');page.locator('#total').fill('104')
            page.locator('#subtotal').fill('97')
            page.locator('#allocate').click()
            expect(page.locator('#allocation-preview')).to_contain_text('104')
            expect(page.get_by_label('税込円',exact=True)).to_have_value('120')
            page.locator('#apply-allocation').click();expect(page.locator('.allocation-detail')).to_contain_text('計算値')
            expect(page.get_by_label('税込円',exact=True)).to_have_value('104')
            page.locator('#allocation-approved').check();page.locator('#reviewed').check();page.locator('#confirm').click()
            expect(page.locator('#receipt-status')).to_have_text('確定済み')
            page.get_by_role('button',name='家計の概要').click();expect(page.locator('#monthly-total')).to_have_text('￥104')
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            ROOT.joinpath('artifacts').mkdir(exist_ok=True);page.screenshot(path=str(ROOT/'artifacts/mobile.png'),full_page=True)
            page.set_viewport_size({'width':1280,'height':900});page.screenshot(path=str(ROOT/'artifacts/desktop.png'),full_page=True)
            assert not errors
            browser.close()
    finally:
        process.terminate();process.wait(timeout=10)
