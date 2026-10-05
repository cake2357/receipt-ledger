from test_error_highlights_browser import ui
from playwright.sync_api import expect

def test_schema_decimal_and_category_error(ui):
    ui.get_by_label('税込円',exact=True).fill('1.5')
    ui.locator('#save').click()
    expect(ui.get_by_label('税込円',exact=True)).to_have_attribute('aria-invalid','true')
    ui.get_by_role('button',name='分類・設定').click()
    ui.locator('.category-editor input').first.fill('おやつ')
    ui.locator('.category-editor button').first.click()
    expect(ui.locator('.category-editor input').first).to_have_attribute('aria-invalid','true')
    expect(ui.locator('.field-error-summary')).to_contain_text('別の分類名')

def test_advanced_expands_and_network_stays_global(ui):
    ui.locator('#tax-exclusive').check()
    # Trigger existing API operation with advanced controls collapsed.
    ui.evaluate("document.querySelector('#allocate').click()")
    expect(ui.locator('#tax-rates')).to_be_visible()
    expect(ui.locator('#tax-rates')).to_have_attribute('aria-invalid','true')
    expect(ui.locator('#tax-rates')).to_be_focused()
    ui.route('**/api/receipts/*',lambda route: route.fulfill(status=502,json={'detail':'接続失敗'}))
    ui.locator('#save').click()
    expect(ui.locator('#review-message')).to_contain_text('接続失敗')
    expect(ui.locator('[aria-invalid]')).to_have_count(0)
    expect(ui.locator('.field-error-summary')).to_have_count(0)


def test_hidden_discount_error_reveals_and_focuses_field(ui):
    ui.locator('#tax-exclusive').check()
    expect(ui.locator('#discount-total')).to_be_hidden()
    ui.route('**/api/receipts/*', lambda route: route.fulfill(status=422, json={
        'detail': '割引額を確認してください',
        'field_errors': [{'loc': ['discount_total'], 'message': '割引額を確認してください'}],
    }))
    ui.locator('#save').click()
    expect(ui.locator('#discount-total')).to_be_visible()
    expect(ui.locator('#discount-total')).to_be_focused()
    expect(ui.locator('#discount-total')).to_have_attribute('aria-invalid', 'true')
