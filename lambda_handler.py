from app import app
from werkzeug.middleware.proxy_fix import ProxyFix
import base64

# Apply proxy fix for proper handling behind AWS Lambda
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

def handler(event, context):
    # Convert Lambda Function URL event to WSGI environ
    headers = event.get('headers', {})

    # Build WSGI environ
    environ = {
        'REQUEST_METHOD': event.get('requestContext', {}).get('http', {}).get('method', 'GET'),
        'SCRIPT_NAME': '',
        'PATH_INFO': event.get('rawPath', '/'),
        'QUERY_STRING': event.get('rawQueryString', ''),
        'CONTENT_TYPE': headers.get('content-type', ''),
        'CONTENT_LENGTH': headers.get('content-length', '0'),
        'SERVER_NAME': headers.get('host', 'localhost'),
        'SERVER_PORT': headers.get('x-forwarded-port', '443'),
        'SERVER_PROTOCOL': 'HTTP/1.1',
        'wsgi.version': (1, 0),
        'wsgi.url_scheme': headers.get('x-forwarded-proto', 'https'),
        'wsgi.input': None,
        'wsgi.errors': None,
        'wsgi.multithread': False,
        'wsgi.multiprocess': False,
        'wsgi.run_once': False,
    }

    # Add headers to environ
    for key, value in headers.items():
        key = key.upper().replace('-', '_')
        if key not in ('CONTENT_TYPE', 'CONTENT_LENGTH'):
            environ[f'HTTP_{key}'] = value

    # Handle body
    body = event.get('body', '')
    if event.get('isBase64Encoded', False):
        body = base64.b64decode(body)
    elif isinstance(body, str):
        body = body.encode('utf-8')

    from io import BytesIO
    environ['wsgi.input'] = BytesIO(body)
    environ['CONTENT_LENGTH'] = str(len(body))

    # Call Flask app
    response_data = []
    status = None
    response_headers = []

    def start_response(status_str, headers):
        nonlocal status, response_headers
        status = int(status_str.split(' ')[0])
        response_headers = headers

    app_iter = app(environ, start_response)
    try:
        for data in app_iter:
            response_data.append(data)
    finally:
        if hasattr(app_iter, 'close'):
            app_iter.close()

    # Build response
    body_bytes = b''.join(response_data)

    # Convert headers to Lambda format
    response_headers_dict = {}
    for key, value in response_headers:
        response_headers_dict[key.lower()] = value

    # Check if binary content
    is_binary = False
    content_type = response_headers_dict.get('content-type', '')
    if 'image' in content_type or 'application/octet-stream' in content_type:
        is_binary = True

    return {
        'statusCode': status,
        'headers': response_headers_dict,
        'body': base64.b64encode(body_bytes).decode('utf-8') if is_binary else body_bytes.decode('utf-8', errors='replace'),
        'isBase64Encoded': is_binary
    }
