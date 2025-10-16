from app import app
from werkzeug.middleware.proxy_fix import ProxyFix
import awsgi

# Apply proxy fix for proper handling behind AWS Lambda
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

def handler(event, context):
    return awsgi.response(app, event, context)
