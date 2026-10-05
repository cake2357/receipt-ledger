"""Synthetic browser checks; isolated SQLite, no OCR/provider requests."""
import os
import socket
import subprocess
import time

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright
from test_browser import ROOT

ARTIFACTS = ROOT / 'artifacts/ui-clarity'


@pytest.fixture
def ui(tmp_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = {**os.environ, 'LEDGER_DATA_DIR': str(tmp_path),
           'LEDGER_PORT': str(port), 'OPENAI_API_KEY': '', 'OPENAI_MODEL': ''}
    process = subprocess.Popen([str(ROOT / '.venv/bin/python'), 'server.py'],
                               cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    try:
        url = f'http://127.0.0.1:{port}'
        for _ in range(100):
            try:
                if httpx.get(url).status_code == 200:
                    break
            except httpx.ConnectError:
                pass
            time.sleep(.1)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={'width': 1280, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' else None)
            page.goto(url)
            page.get_by_role('button', name='レシート', exact=True).click()
            page.locator('#manual').click()
            expect(page.locator('.item')).to_have_count(1)
            ARTIFACTS.mkdir(parents=True, exist_ok=True)
            yield page
            assert not errors
            browser.close()
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_edit_marks_previous_calculation_stale_and_save_is_honest(ui):
    ui.locator('#receipt-date').fill('2026-10-03')
    ui.locator('#store').fill('架空店')
    ui.get_by_label('商品名', exact=True).fill('テスト肉')
    ui.get_by_label('分類', exact=True).select_option('1')
    ui.locator('#tax-exclusive').check()
    ui.get_by_label('税抜明細額', exact=True).fill('100')
    ui.locator('#total').fill('108')
    ui.locator('#tax-exclusive').check()
    ui.locator('#tax-calculate').click()
    expect(ui.locator('#review-message')).to_contain_text('下書き保存済み')
    ui.locator('#tax-apply').click()
    expect(ui.get_by_label('税込円', exact=True)).to_have_value('108')
    ui.locator('#allocation-approved').check()
    ui.locator('#reviewed').check()
    ui.get_by_label('税抜明細額', exact=True).fill('200')
    expect(ui.locator('#tax-summary')).to_contain_text('再計算')
    expect(ui.locator('.allocation-detail')).to_be_hidden()
    expect(ui.locator('#allocation-approved')).not_to_be_checked()
    expect(ui.locator('#reviewed')).not_to_be_checked()
    ui.locator('#save').click()
    expect(ui.locator('#review-message')).to_contain_text('下書きを保存')
    ui.get_by_label('税抜明細額', exact=True).fill('300')
    expect(ui.locator('#review-message')).to_contain_text('未保存')
    ui.screenshot(path=str(ARTIFACTS / 'stale-calculation.png'), full_page=True)


def test_busy_save_blocks_double_submit_and_acknowledges_locally(ui):
    ui.locator('#store').fill('保存確認用・架空店')
    ui.evaluate('''() => {
      const realFetch = window.fetch;
      window.saveCalls = 0;
      window.fetch = async (url, options) => {
        if (options?.method === 'PUT' && url.startsWith('/api/receipts/')) {
          window.saveCalls++;
          await new Promise(resolve => window.releaseSave = resolve);
        }
        return realFetch(url, options);
      };
    }''')
    ui.locator('#save').click()
    expect(ui.locator('#save')).to_be_disabled()
    expect(ui.locator('#save')).to_have_text('保存中…')
    expect(ui.locator('#store')).to_be_disabled()
    ui.locator('#save').dispatch_event('click')
    ui.evaluate('window.releaseSave()')
    expect(ui.locator('#save')).to_be_enabled()
    expect(ui.locator('#review-message')).to_contain_text('下書きを保存')
    assert ui.evaluate('window.saveCalls') == 1
    ui.reload()
    ui.get_by_role('button', name='レシート', exact=True).click()
    ui.locator('.receipt-card').click()
    expect(ui.locator('#store')).to_have_value('保存確認用・架空店')


def test_simple_steps_keep_advanced_allocation_optional(ui):
    for title in ['1. レシートを入力', '2. 合計を確認して保存']:
        expect(ui.get_by_role('heading', name=title, exact=True)).to_be_visible()
    expect(ui.locator('#allocation-panel')).to_be_hidden()
    expect(ui.locator('#allocation-approved')).to_be_hidden()
    expect(ui.locator('#bulk-category')).to_be_hidden()
    assert '配賦' not in ui.locator('#review').inner_text()
    ui.locator('#tax-exclusive').check()
    expect(ui.locator('#tax-calculate')).to_be_visible()
    expect(ui.locator('#allocation-approved')).to_be_visible()
    expect(ui.locator('#discount-total')).to_be_hidden()
    ui.locator('#ok-discount-mode').select_option('printed')
    expect(ui.locator('#discount-total')).to_be_visible()
    ui.locator('#ok-discount-mode').select_option('off')
    expect(ui.locator('#discount-total')).to_be_hidden()
    expect(ui.locator('#allocate')).to_be_hidden()
    ui.locator('#manual-allocation > summary').click()
    expect(ui.locator('#allocate')).to_be_visible()
    expect(ui.locator('#manual-allocation')).to_contain_text('全商品の税率が同じ')
    expect(ui.locator('#discount-total')).to_be_visible()
    assert ui.locator('#items').evaluate('el => !!(el.compareDocumentPosition(document.querySelector("#tax-calculate")) & Node.DOCUMENT_POSITION_FOLLOWING)')
    ui.set_viewport_size({'width': 390, 'height': 844})
    assert ui.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    ui.screenshot(path=str(ARTIFACTS / 'mobile-advanced.png'), full_page=True)


def test_item_fields_have_persistent_visible_labels(ui):
    ui.screenshot(path=str(ARTIFACTS / 'item-labels.png'), full_page=True)
    expect(ui.get_by_label('数量', exact=True)).to_be_hidden()
    ui.locator('.item-details > summary').click()
    fields = ui.locator('.item input, .item select')
    assert fields.count() == 7
    for field in fields.all():
        assert field.evaluate('el => [...el.labels].some(label => label.innerText.trim() && label.getBoundingClientRect().height > 0)'), field.get_attribute('aria-label')
    assert ui.locator('.item [data-field]').count() == 7
    ui.set_viewport_size({'width': 390, 'height': 844})
    assert ui.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    ui.screenshot(path=str(ARTIFACTS / 'mobile-items.png'), full_page=True)


def test_fast_entry_and_bulk_category_preserve_explicit_values(ui):
    from datetime import date
    expect(ui.locator('#receipt-date')).to_have_value(date.today().isoformat())
    expect(ui.locator('#store')).to_be_focused()
    expect(ui.get_by_label('税抜明細額', exact=True)).to_be_hidden()
    expect(ui.locator('#use-item-total')).to_be_disabled()
    ui.get_by_label('商品名', exact=True).fill('手入力商品')
    ui.get_by_label('分類', exact=True).select_option('1')
    ui.get_by_label('税込円', exact=True).fill('100')
    ui.get_by_label('税込円', exact=True).press('Enter')
    expect(ui.locator('.item')).to_have_count(2)
    expect(ui.locator('.item').nth(1).get_by_label('商品名', exact=True)).to_be_focused()
    ui.locator('#bulk-category-options > summary').click()
    ui.locator('#bulk-category').select_option('2')
    ui.locator('#apply-category').click()
    expect(ui.locator('.item').nth(0).get_by_label('分類', exact=True)).to_have_value('1')
    expect(ui.locator('.item').nth(1).get_by_label('分類', exact=True)).to_have_value('2')
    expect(ui.locator('#use-item-total')).to_be_disabled()
    ui.locator('.item').nth(1).get_by_label('商品名', exact=True).fill('野菜')
    ui.locator('.item').nth(1).get_by_label('税込円', exact=True).fill('200')
    ui.locator('#use-item-total').click()
    expect(ui.locator('#total')).to_have_value('300')
    expect(ui.locator('#reviewed')).not_to_be_checked()
    ui.locator('#store').fill('入力テスト店')
    ui.locator('#save').click()
    ui.reload()
    ui.get_by_role('button', name='レシート', exact=True).click()
    ui.locator('.receipt-card').click()
    expect(ui.locator('#total')).to_have_value('300')
    expect(ui.locator('.item')).to_have_count(2)
    ui.set_viewport_size({'width': 390, 'height': 844})
    assert ui.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    ui.screenshot(path=str(ARTIFACTS / 'easy-entry-mobile.png'), full_page=True)


def test_confirmed_name_suggestions_only_fill_blank_categories(ui):
    import httpx
    url = ui.url.rstrip('/')
    with httpx.Client(base_url=url, headers={'Origin': url}) as client:
        receipt = client.post('/api/receipts').json()
        body = {'date': '2026-10-04', 'store': '候補の店', 'total': 100,
                'items': [{'name': '候補商品', 'category_id': 1, 'amount': 100}],
                'reviewed': True}
        assert client.put(f"/api/receipts/{receipt['id']}", json=body).status_code == 200
        assert client.post(f"/api/receipts/{receipt['id']}/confirm").status_code == 200
    ui.locator('#manual').click()
    expect(ui.locator('#store-suggestions option')).to_have_count(1)
    ui.get_by_label('商品名', exact=True).fill('候補商品')
    expect(ui.get_by_label('分類', exact=True)).to_have_value('1')
    ui.get_by_label('商品名', exact=True).fill('未知の商品')
    expect(ui.get_by_label('分類', exact=True)).to_have_value('')
    ui.get_by_label('分類', exact=True).select_option('2')
    ui.get_by_label('商品名', exact=True).fill('候補商品')
    expect(ui.get_by_label('分類', exact=True)).to_have_value('2')
    expect(ui.get_by_label('税込円', exact=True)).to_have_value('')


def test_manual_ok_rounding_correction_survives_reload_and_confirms(ui):
    ui.locator('#receipt-date').fill('2026-10-04')
    ui.locator('#store').fill('オーケー 手修正テスト店')
    ui.get_by_label('商品名', exact=True).fill('食品')
    ui.get_by_label('分類', exact=True).select_option('1')
    ui.locator('#tax-exclusive').check()
    ui.get_by_label('税抜明細額', exact=True).fill('1030')
    ui.locator('#total').fill('1079')
    ui.locator('#ok-discount-mode').select_option('formula')
    ui.locator('#tax-calculate').click()
    ui.locator('#tax-apply').click()
    expect(ui.get_by_label('税込円', exact=True)).to_have_value('1080')
    ui.locator('#allocation-approved').check()
    ui.locator('#reviewed').check()
    ui.get_by_label('税込円', exact=True).fill('1079')
    expect(ui.locator('.manual-amount-detail')).to_be_visible()
    expect(ui.locator('#tax-summary')).to_contain_text('手修正')
    expect(ui.locator('#allocation-approved')).not_to_be_checked()
    expect(ui.locator('#reviewed')).not_to_be_checked()
    ui.locator('#save').click()
    expect(ui.locator('#review-message')).to_contain_text('下書きを保存')
    ui.reload()
    ui.get_by_role('button', name='レシート', exact=True).click()
    ui.locator('.receipt-card').click()
    expect(ui.get_by_label('税込円', exact=True)).to_have_value('1079')
    expect(ui.locator('.manual-amount-detail')).to_be_visible()
    ui.locator('#allocation-approved').check()
    ui.locator('#reviewed').check()
    ui.locator('#confirm').click()
    expect(ui.locator('#receipt-status')).to_have_text('確定済み')


def test_legacy_saved_manual_amount_can_be_adopted_without_retyping(ui):
    from test_auto_tax import applied
    url=ui.url.rstrip('/')
    with httpx.Client(base_url=url,headers={'Origin':url}) as client:
        path,out=applied(client,items=[dict(name='食品',category_id=1,pre_tax=1030)],
                         total=1079,ok_discount_mode='formula',store='旧版手修正テスト店')
        out['items'][0]['amount']=1079  # Old UI retained calculated source.
        assert client.put(path,json=out).status_code==200
    ui.reload()
    ui.get_by_role('button',name='レシート',exact=True).click()
    ui.locator('.receipt-card').filter(has_text='旧版手修正テスト店').click()
    expect(ui.locator('#adopt-manual-amounts')).to_have_text('保存済みの手修正額を採用（1件）')
    expect(ui.get_by_label('税込円',exact=True)).to_have_value('1079')
    ui.locator('#adopt-manual-amounts').click()
    expect(ui.locator('#adopt-manual-amounts')).to_be_hidden()
    expect(ui.locator('.manual-amount-detail')).to_be_visible()
    expect(ui.get_by_label('税込円',exact=True)).to_have_value('1079')
    ui.locator('#allocation-approved').check()
    ui.locator('#reviewed').check()
    ui.locator('#confirm').click()
    expect(ui.locator('#receipt-status')).to_have_text('確定済み')
