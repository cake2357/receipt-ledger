"""Bounded subprocess entrypoint for PaddleOCR 3.x Japanese CPU inference."""
import json
import math
import sys


def normalize_result(result, width, height):
    """Convert Paddle's pixel quadrilaterals to the parser's normalized boxes."""
    data = result.json['res']
    lines = []
    for text, score, poly in zip(data['rec_texts'], data['rec_scores'], data['rec_polys'], strict=True):
        points = [(float(x), float(y)) for x, y in poly]
        if len(points) != 4 or not all(math.isfinite(v) for p in points for v in p):
            raise ValueError('Invalid text polygon')
        confidence = float(score)
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError('Invalid confidence')
        xs, ys = zip(*points)
        dx = points[1][0] - points[0][0]
        slope = ((points[1][1] - points[0][1]) / height) / (dx / width) if dx else 0
        lines.append(dict(text=str(text), confidence=confidence,
                          x=min(xs)/width, y=min(ys)/height,
                          width=(max(xs)-min(xs))/width, height=(max(ys)-min(ys))/height,
                          slope=slope, polygon=points))
    return lines


def main(image_path):
    from PIL import Image
    from paddleocr import PaddleOCR
    with Image.open(image_path) as image:
        width, height = image.size
    ocr = PaddleOCR(lang='japan', ocr_version='PP-OCRv5', device='cpu',
                    use_doc_orientation_classify=False, use_doc_unwarping=False,
                    use_textline_orientation=False, enable_mkldnn=False)
    lines = []
    for result in ocr.predict(image_path):
        lines.extend(normalize_result(result, width, height))
    print('LEDGER_OCR_RESULT=' + json.dumps(
        dict(engine='PaddleOCR', languages=['japan'], lines=lines), ensure_ascii=False))


if __name__ == '__main__':
    main(sys.argv[1])
