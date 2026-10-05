from test_app import client


def test_confirm_fields_are_indexed_and_detail_unchanged(client):
    rid = client.post('/api/receipts').json()['id']
    client.put(f'/api/receipts/{rid}', json={'items': [
        {'name': '正常', 'category_id': 1, 'amount': 100}, {}]})
    result = client.post(f'/api/receipts/{rid}/confirm').json()
    assert result['detail'] == '日付を YYYY-MM-DD で入力してください / 店名を入力してください / 画像・税込金額・不確実箇所の確認が必要です / 全明細に商品名・分類・整数円が必要です / 明細合計とレシート合計が一致しません'
    paths = [e['loc'] for e in result['field_errors']]
    assert paths == [['date'], ['store'], ['reviewed'], ['items', 1, 'name'], ['items', 1, 'category_id'], ['items', 1, 'amount'], ['total']]
    assert all(e['message'] for e in result['field_errors'])
