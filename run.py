#!/usr/bin/env python3
"""
Entrypoint for running the Drishti OCR Flask application locally.
"""
from src.app import app

if __name__ == '__main__':
    app.run(debug=True, threaded=True, port=5001)
