from src.app import app
from werkzeug.middleware.proxy_fix import ProxyFix
import base64
import sys
from io import BytesIO
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

# Apply proxy fix for proper handling behind AWS Lambda
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

def handler(event, context):
    """
    Handler that supports both buffered and streaming responses.
    For streaming endpoints (Server-Sent Events), it streams chunks.
    """
    # Convert Lambda Function URL event to WSGI environ
    headers = event.get('headers', {})

    # Get the HTTP method
    method = event.get('requestContext', {}).get('http', {}).get('method', 'GET')

    # Build WSGI environ
    environ = {
        'REQUEST_METHOD': method,
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
        'wsgi.errors': sys.stderr,
        'wsgi.multithread': False,
        'wsgi.multiprocess': False,
        'wsgi.run_once': False,
    }

    # Add headers to environ
    for key, value in headers.items():
        key = key.upper().replace('-', '_')
        if key not in ('CONTENT_TYPE', 'CONTENT_LENGTH'):
            environ[f'HTTP_{key}'] = value

    # Handle body - properly decode base64 for file uploads
    body = event.get('body', '')
    if body:
        if event.get('isBase64Encoded', False):
            # For file uploads (multipart/form-data), the body is base64 encoded
            body = base64.b64decode(body)
        elif isinstance(body, str):
            body = body.encode('utf-8')
    else:
        body = b''

    environ['wsgi.input'] = BytesIO(body)
    environ['CONTENT_LENGTH'] = str(len(body))

    # Call Flask app
    response_data = []
    status = None
    response_headers = []
    is_streaming = False

    def start_response(status_str, headers_list):
        nonlocal status, response_headers, is_streaming
        status = int(status_str.split(' ')[0])
        response_headers = headers_list

        # Check if this is a streaming response (SSE)
        for key, value in headers_list:
            if key.lower() == 'content-type' and 'text/event-stream' in value.lower():
                is_streaming = True
                break

    app_iter = app(environ, start_response)

    # Convert headers to Lambda format
    response_headers_dict = {}
    for key, value in response_headers:
        response_headers_dict[key.lower()] = value

    # If streaming, use Lambda response streaming
    if is_streaming and hasattr(context, 'awslambdaric_stream'):
        # For Lambda response streaming
        try:
            # Write headers first
            metadata = {
                'statusCode': status,
                'headers': response_headers_dict
            }

            # Stream chunks
            for chunk in app_iter:
                if chunk:
                    yield chunk
        finally:
            if hasattr(app_iter, 'close'):
                app_iter.close()
    else:
        # Buffered response for non-streaming endpoints
        try:
            for data in app_iter:
                response_data.append(data)
        finally:
            if hasattr(app_iter, 'close'):
                app_iter.close()

        # Build response
        body_bytes = b''.join(response_data)

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
