from flask import Flask, request, render_template, jsonify, Response, send_file
from flask_cors import CORS
import os
import uuid
import json
from werkzeug.utils import secure_filename
from config import Config
from ocr_processor import OCRProcessor
import logging

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)
CORS(app)

# Create upload folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "File type not allowed"}), 400

    try:
        # Generate unique file ID
        file_id = str(uuid.uuid4())
        filename = secure_filename(file.filename)
        file_extension = os.path.splitext(filename)[1]
        saved_filename = f"{file_id}{file_extension}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], saved_filename)

        # Save file
        file.save(file_path)

        return jsonify({
            "success": True,
            "file_id": file_id,
            "filename": filename,
            "file_extension": file_extension,
            "message": "File uploaded successfully"
        })

    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/process/<file_id>')
def process_file(file_id):
    """Process file and stream results page by page using Server-Sent Events"""

    # Get language parameter from query string BEFORE the generator
    language = request.args.get('lang', Config.TESSERACT_LANG)

    def generate():
        try:
            # Find the file
            file_path = None
            for filename in os.listdir(app.config['UPLOAD_FOLDER']):
                if filename.startswith(file_id):
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    break

            if not file_path or not os.path.exists(file_path):
                yield f"data: {json.dumps({'error': 'File not found'})}\n\n"
                return

            # Process file with specified language
            processor = OCRProcessor(language=language)

            for page_result in processor.process_file(file_path, file_id):
                # Send each page result as it's processed
                yield f"data: {json.dumps(page_result)}\n\n"

            # Send completion signal
            yield f"data: {json.dumps({'complete': True})}\n\n"

            processor.cleanup()

            # Optionally delete the file after processing
            # os.remove(file_path)

        except Exception as e:
            logger.error(f"Error processing file: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(generate(), mimetype='text/event-stream')


@app.route('/file/<file_id>')
def get_file(file_id):
    """Serve the uploaded file"""
    try:
        # Find the file
        for filename in os.listdir(app.config['UPLOAD_FOLDER']):
            if filename.startswith(file_id):
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                return send_file(file_path)

        return jsonify({"error": "File not found"}), 404
    except Exception as e:
        logger.error(f"Error serving file: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/page/<file_id>/<int:page_num>')
def get_page_image(file_id, page_num):
    """Get a specific page image from a PDF"""
    try:
        from pdf2image import convert_from_path
        from PIL import Image
        import io

        # Find the file
        file_path = None
        for filename in os.listdir(app.config['UPLOAD_FOLDER']):
            if filename.startswith(file_id):
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                break

        if not file_path or not os.path.exists(file_path):
            return jsonify({"error": "File not found"}), 404

        file_extension = os.path.splitext(file_path)[1].lower()

        if file_extension == '.pdf':
            # Convert specific page to image
            images = convert_from_path(file_path, first_page=page_num, last_page=page_num)
            if images:
                img_io = io.BytesIO()
                images[0].save(img_io, 'PNG')
                img_io.seek(0)
                return send_file(img_io, mimetype='image/png')
        else:
            # For images, just return the image
            return send_file(file_path)

        return jsonify({"error": "Page not found"}), 404
    except Exception as e:
        logger.error(f"Error serving page image: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/health')
def health():
    return jsonify({"status": "healthy"})


if __name__ == '__main__':
    app.run(debug=True, threaded=True, port=5000)
