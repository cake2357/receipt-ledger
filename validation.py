"""Additive, structured form errors. Legacy HTTP detail is preserved."""
from fastapi import HTTPException
from fastapi.responses import JSONResponse


def field(loc, message, derived=False):
    return {'loc': list(loc), 'message': message, 'derived': derived}


class FieldError(HTTPException):
    def __init__(self, detail, fields, status_code=422):
        super().__init__(status_code, detail)
        self.field_errors = fields


def install_validation(app):
    from fastapi.exceptions import RequestValidationError
    from fastapi.exception_handlers import request_validation_exception_handler

    @app.exception_handler(RequestValidationError)
    async def schema_handler(request, exc):
        import json
        response = await request_validation_exception_handler(request, exc)
        payload = json.loads(response.body)
        messages = {'int_type': '整数円・整数数量で入力してください',
                    'literal_error': '選択肢から有効な値を選んでください',
                    'string_too_short': '入力してください',
                    'greater_than_equal': '入力値が最小値を下回っています',
                    'less_than_equal': '入力値が上限を超えています'}
        payload['field_errors'] = [field(e['loc'][1:], messages.get(e['type'], '入力形式・文字数・選択値を確認してください'))
                                   for e in exc.errors() if e['loc'] and e['loc'][0]=='body']
        return JSONResponse(status_code=422, content=payload)

    @app.exception_handler(FieldError)
    async def field_handler(request, exc):
        return JSONResponse(status_code=exc.status_code,
                            content={'detail': exc.detail, 'field_errors': exc.field_errors})
