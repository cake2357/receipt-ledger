from types import SimpleNamespace

import pytest

from paddle_ocr_worker import normalize_result


def result(texts, scores, polys):
    return SimpleNamespace(json={'res': dict(rec_texts=texts, rec_scores=scores, rec_polys=polys)})


def test_pixel_boxes_and_tilt_convert_to_parser_coordinates():
    raw = result(['牛肉 ¥200'], [.9], [[[100, 200], [500, 220], [500, 250], [100, 230]]])
    line = normalize_result(raw, 1000, 2000)[0]
    assert line['text'] == '牛肉 ¥200' and line['confidence'] == .9
    assert line['x'] == .1 and line['y'] == .1
    assert line['width'] == .4 and line['height'] == .025
    assert line['slope'] == pytest.approx(.025)
    assert [list(point) for point in line['polygon']] == raw.json['res']['rec_polys'][0]


def test_mismatched_outputs_and_nonfinite_confidence_rejected():
    with pytest.raises(ValueError):
        normalize_result(result(['牛肉'], [], []), 1000, 2000)
    with pytest.raises(ValueError):
        normalize_result(result(['牛肉'], [float('nan')], [[[0, 0]]*4]), 1000, 2000)
    with pytest.raises(ValueError):
        normalize_result(result(['牛肉'], [.9], [[[float('nan'), 0]]*4]), 1000, 2000)
