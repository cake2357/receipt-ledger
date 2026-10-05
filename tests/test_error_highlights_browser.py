"""Synthetic-only browser regression; no production server or provider calls."""
from pathlib import Path
from playwright.sync_api import expect
import os
import socket
import subprocess
import time
import httpx
import pytest
from playwright.sync_api import sync_playwright


@pytest.fixture
def ui(tmp_path):
    root = Path(__file__).resolve().parents[1]
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = {**os.environ, 'LEDGER_DATA_DIR': str(tmp_path), 'LEDGER_PORT': str(port),
           'OPENAI_API_KEY': '', 'OPENAI_MODEL': ''}
    process = subprocess.Popen([str(root / '.venv/bin/python'), 'server.py'], cwd=root,
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        url = f'http://127.0.0.1:{port}'
        for _ in range(100):
            try:
                if httpx.get(url).status_code == 200: break
            except httpx.ConnectError: pass
            time.sleep(.1)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={'width': 1280, 'height': 1000})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            # Failed HTTP resource messages are expected in validation tests;
            # script errors and all other console errors remain test failures.
            page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and not m.text.startswith('Failed to load resource:') else None)
            page.goto(url)
            page.get_by_role('button', name='レシート', exact=True).click()
            page.locator('#manual').click()
            expect(page.locator('.item')).to_have_count(1)
            yield page
            assert not errors
            browser.close()
    finally:
        process.terminate()
        process.wait(timeout=10)

ARTIFACTS = Path(__file__).resolve().parents[1] / 'artifacts/error-highlights'


def test_confirm_inline_focus_links_and_clear(ui):
    ui.locator('#receipt-date').fill('')
    ui.locator('#add-item').click()
    ui.locator('.item').nth(0).get_by_label('商品名', exact=True).fill('正常な明細')
    ui.locator('.item').nth(0).get_by_label('分類', exact=True).select_option('1')
    ui.locator('.item').nth(0).get_by_label('税込円', exact=True).fill('100')
    ui.locator('#confirm').click()
    expect(ui.locator('#receipt-date')).to_have_attribute('aria-invalid', 'true')
    expect(ui.locator('#receipt-date')).to_be_focused()
    expect(ui.locator('.item').nth(0).locator('[aria-invalid]')).to_have_count(0)
    second = ui.locator('.item').nth(1).get_by_label('商品名', exact=True)
    expect(second).to_have_attribute('aria-invalid', 'true')
    error_id = second.get_attribute('aria-describedby')
    expect(ui.locator('#' + error_id)).to_contain_text('商品名を入力')
    ui.locator('.field-error-summary a').filter(has_text='明細2・商品名').click()
    expect(second).to_be_focused()
    assert second.evaluate("el => getComputedStyle(el).borderColor") == 'rgb(180, 35, 24)'
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    ui.screenshot(path=str(ARTIFACTS / 'desktop-errors.png'), full_page=True)
    ui.set_viewport_size({'width': 390, 'height': 844})
    assert ui.evaluate('document.documentElement.scrollWidth <= innerWidth')
    ui.screenshot(path=str(ARTIFACTS / 'mobile-errors.png'), full_page=True)
    second.fill('修正済み')
    expect(second).not_to_have_attribute('aria-invalid', 'true')
    expect(ui.locator('#' + error_id)).to_have_count(0)
    expect(ui.locator('#store')).to_have_attribute('aria-invalid', 'true')
    ui.locator('#save').click()
    expect(ui.locator('[aria-invalid]')).to_have_count(0)
    expect(second).to_have_value('修正済み')
