import uuid
from flask import jsonify

def api_response(data=None, status_code=200, headers=None):
    """Genera una respuesta exitosa estandarizada conforme a OpenAPI: { data: ... }"""
    payload = {}
    if data is not None:
        payload['data'] = data
    response = jsonify(payload)
    response.status_code = status_code
    if headers:
        for k, v in headers.items():
            response.headers[k] = v
    return response

def api_error(code, message, status_code=400, details=None, request_id=None):
    """Genera una respuesta de error estandarizada conforme a OpenAPI: { error: ... }"""
    if not request_id:
        request_id = f"req_{uuid.uuid4().hex[:12]}"
    
    error_body = {
        'code': code,
        'message': message,
        'request_id': request_id
    }
    if details:
        error_body['details'] = details

    response = jsonify({'error': error_body})
    response.status_code = status_code
    return response
