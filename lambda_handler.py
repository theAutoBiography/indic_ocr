import json
import base64
from app import app
from mangum import Mangum

# Wrap Flask app with Mangum for AWS Lambda
handler = Mangum(app, lifespan="off")
