from flask import Flask, request, render_template, jsonify, Response, send_file
from flask_cors import CORS
import os
import uuid
import json
import hashlib
from decimal import Decimal
from werkzeug.utils import secure_filename
from src.config import Config
from src.ocr_processor import OCRProcessor
from src.aws_service import AWSService
from src.sandhi_service import SandhiService
from datetime import datetime
import logging

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

# Get the project root directory (parent of src/)
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Initialize Flask with correct template and static paths
app = Flask(__name__,
            template_folder=os.path.join(project_root, 'templates'),
            static_folder=os.path.join(project_root, 'static'))
app.config.from_object(Config)
CORS(app)

# Create upload folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS


def convert_decimals(obj):
    """Recursively convert DynamoDB Decimal types to float for JSON serialization"""
    if isinstance(obj, list):
        return [convert_decimals(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal):
        return float(obj)
    else:
        return obj


def calculate_file_hash(file_path):
    """Calculate SHA256 hash of a file"""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


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
        # Generate unique file ID first
        file_id = str(uuid.uuid4())
        filename = secure_filename(file.filename)
        file_extension = os.path.splitext(filename)[1]
        saved_filename = f"{file_id}{file_extension}"

        # Use /tmp for production (ECS), local uploads folder for development
        upload_folder = '/tmp/uploads' if os.environ.get('AWS_EXECUTION_ENV') else app.config['UPLOAD_FOLDER']
        os.makedirs(upload_folder, exist_ok=True)

        file_path = os.path.join(upload_folder, saved_filename)
        file.save(file_path)

        # Calculate file hash
        file_hash = calculate_file_hash(file_path)

        # Check if this file has been processed before
        aws_service = AWSService()
        table = aws_service.dynamodb.Table(Config.DYNAMODB_TABLE)

        # Query using GSI to find existing file by hash
        response = table.query(
            IndexName='GSI-FileHash',
            KeyConditionExpression='file_hash = :hash',
            ExpressionAttributeValues={
                ':hash': file_hash
            },
            Limit=1
        )

        if response.get('Items'):
            # File has been processed before - get the original file_id
            existing_item = response['Items'][0]
            existing_file_id = existing_item['file_id']

            # Remove the newly uploaded file since we don't need it
            os.remove(file_path)

            return jsonify({
                "success": True,
                "file_id": existing_file_id,
                "filename": filename,
                "file_extension": file_extension,
                "cached": True,
                "message": "File already processed - retrieving cached results"
            })

        # New file - store the hash in metadata for future lookups
        # We'll add this to the first word entry
        return jsonify({
            "success": True,
            "file_id": file_id,
            "filename": filename,
            "file_extension": file_extension,
            "file_hash": file_hash,
            "cached": False,
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
            # Find the file in upload folder
            upload_folder = '/tmp/uploads' if os.environ.get('AWS_EXECUTION_ENV') else app.config['UPLOAD_FOLDER']
            file_path = None

            if os.path.exists(upload_folder):
                for filename in os.listdir(upload_folder):
                    if filename.startswith(file_id):
                        file_path = os.path.join(upload_folder, filename)
                        break

            if not file_path or not os.path.exists(file_path):
                yield f"data: {json.dumps({'error': 'File not found'})}\n\n"
                return

            # Process file with specified language
            processor = OCRProcessor(language=language)

            for page_result in processor.process_file(file_path, file_id):
                # Send each page result as it's processed (convert Decimals for JSON)
                yield f"data: {json.dumps(convert_decimals(page_result))}\n\n"

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


@app.route('/api/correction', methods=['POST'])
def submit_correction():
    """Submit a correction for a word - updates cache automatically for all future instances"""
    try:
        data = request.json

        # Validate required fields
        required_fields = ['file_id', 'page', 'word_index', 'corrected_text']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400

        file_id = data['file_id']
        page = int(data['page'])
        word_index = int(data['word_index'])
        corrected_text = data['corrected_text']
        approve_for_training = data.get('approve_for_training', False)
        has_sandhi = data.get('has_sandhi', False)

        # Initialize AWS service
        aws_service = AWSService()

        # Update DynamoDB item - this automatically updates the cache via image_hash GSI
        table = aws_service.dynamodb.Table(Config.DYNAMODB_TABLE)

        response = table.update_item(
            Key={
                'file_id': file_id,
                'page#word_index': f"{page:04d}#{word_index:04d}"
            },
            UpdateExpression="""
                SET corrected_text = :text,
                    is_corrected = :is_corrected,
                    corrected_at = :timestamp,
                    updated_at = :timestamp,
                    approved_for_training = :approved,
                    has_sandhi = :has_sandhi,
                    correction_count = correction_count + :inc
            """,
            ExpressionAttributeValues={
                ':text': corrected_text,
                ':is_corrected': 'true',
                ':timestamp': datetime.utcnow().isoformat(),
                ':approved': approve_for_training,
                ':has_sandhi': has_sandhi,
                ':inc': 1
            },
            ReturnValues="ALL_NEW"
        )

        updated_item = response.get('Attributes', {})

        return jsonify({
            "success": True,
            "message": "Correction submitted successfully. Future instances of this word will use the corrected text.",
            "updated_item": updated_item,
            "cache_note": "All words with matching image_hash will retrieve this correction automatically"
        })

    except Exception as e:
        logger.error(f"Error submitting correction: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/corrections', methods=['GET'])
def get_corrections():
    """Get all corrections, optionally filtered by language and confidence"""
    try:
        language = request.args.get('language')
        confidence_lt = request.args.get('confidence_lt', type=float)

        aws_service = AWSService()
        table = aws_service.dynamodb.Table(Config.DYNAMODB_TABLE)

        # Query GSI-Corrections to get all corrected words
        response = table.query(
            IndexName='GSI-Corrections',
            KeyConditionExpression='is_corrected = :is_corrected',
            ExpressionAttributeValues={
                ':is_corrected': 'true'
            }
        )

        items = response.get('Items', [])

        # Apply filters
        if language:
            items = [item for item in items if item.get('language') == language]

        if confidence_lt is not None:
            items = [item for item in items if item.get('confidence', 100) < confidence_lt]

        return jsonify({
            "success": True,
            "count": len(items),
            "corrections": items
        })

    except Exception as e:
        logger.error(f"Error getting corrections: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/word/<file_id>/<int:page>/<int:word_index>', methods=['GET'])
def get_word(file_id, page, word_index):
    """Get complete word data including images"""
    try:
        aws_service = AWSService()
        table = aws_service.dynamodb.Table(Config.DYNAMODB_TABLE)

        # Get word from DynamoDB
        response = table.get_item(
            Key={
                'file_id': file_id,
                'page#word_index': f"{page:04d}#{word_index:04d}"
            }
        )

        if 'Item' not in response:
            return jsonify({"error": "Word not found"}), 404

        item = response['Item']

        # Generate presigned URLs for images if they exist
        if 'word_image_s3_key' in item:
            item['word_image_url'] = aws_service.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': Config.S3_WORD_BUCKET,
                    'Key': item['word_image_s3_key']
                },
                ExpiresIn=3600
            )

        if 'char_images_s3_keys' in item:
            item['char_image_urls'] = [
                aws_service.s3_client.generate_presigned_url(
                    'get_object',
                    Params={
                        'Bucket': Config.S3_CHAR_BUCKET,
                        'Key': key
                    },
                    ExpiresIn=3600
                )
                for key in item['char_images_s3_keys']
            ]

        return jsonify({
            "success": True,
            "word": item
        })

    except Exception as e:
        logger.error(f"Error getting word: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/low-confidence-words/<file_id>', methods=['GET'])
def get_low_confidence_words(file_id):
    """Get all low-confidence words for a file"""
    try:
        aws_service = AWSService()
        table = aws_service.dynamodb.Table(Config.DYNAMODB_TABLE)

        # Query main table by file_id
        response = table.query(
            KeyConditionExpression='file_id = :file_id',
            FilterExpression='is_low_confidence = :is_low',
            ExpressionAttributeValues={
                ':file_id': file_id,
                ':is_low': 'true'
            }
        )

        items = response.get('Items', [])

        return jsonify({
            "success": True,
            "count": len(items),
            "words": items
        })

    except Exception as e:
        logger.error(f"Error getting low confidence words: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# SANDHI ROUTES
# ============================================================================

@app.route('/sandhi')
def sandhi_page():
    """Serve the DrishtiSandhi page"""
    return render_template('sandhi.html')


@app.route('/api/sandhi/words', methods=['GET'])
def get_sandhi_words():
    """
    Get paginated list of words from SandhiKosh corpus
    Query params: limit (default 50), offset (default 0)
    """
    try:
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))

        sandhi_service = SandhiService()
        result = sandhi_service.get_words(limit=limit, offset=offset)

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error getting sandhi words: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/sandhi/words/random', methods=['GET'])
def get_random_sandhi_words():
    """
    Get random words from the corpus
    Query params: count (default 10)
    """
    try:
        count = int(request.args.get('count', 10))

        sandhi_service = SandhiService()
        words = sandhi_service.get_random_words(count=count)

        return jsonify({
            'words': words,
            'count': len(words)
        })

    except Exception as e:
        logger.error(f"Error getting random sandhi words: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/sandhi/word/<word_id>', methods=['GET'])
def get_sandhi_word(word_id):
    """Get a specific word by its corpus ID"""
    try:
        sandhi_service = SandhiService()
        word = sandhi_service.get_word_by_id(word_id)

        if not word:
            return jsonify({"error": "Word not found"}), 404

        # Get previous markings for this word
        markings = sandhi_service.get_markings_for_word(word_id)

        return jsonify({
            'word': word,
            'markings': convert_decimals(markings)
        })

    except Exception as e:
        logger.error(f"Error getting sandhi word: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/sandhi/marking', methods=['POST'])
def submit_sandhi_marking():
    """
    Submit a sandhi marking
    Body: {
        corpus_entry_id: str,
        word: str,
        sandhi_points: [int],
        reference_split: str (optional),
        sandhi_type: str (optional),
        user_session_id: str (optional),
        transliteration: str (optional),
        graphemes: [str] (optional),
        transliteration_segments: [str] (optional)
    }
    """
    try:
        data = request.get_json()

        if not data or 'corpus_entry_id' not in data or 'word' not in data or 'sandhi_points' not in data:
            return jsonify({"error": "Missing required fields"}), 400

        sandhi_service = SandhiService()
        result = sandhi_service.save_correction(
            corpus_entry_id=data['corpus_entry_id'],
            word=data['word'],
            sandhi_points=data['sandhi_points'],
            reference_split=data.get('reference_split', ''),
            sandhi_type=data.get('sandhi_type', ''),
            user_session_id=data.get('user_session_id'),
            transliteration=data.get('transliteration', ''),
            graphemes=data.get('graphemes', []),
            transliteration_segments=data.get('transliteration_segments', [])
        )

        if result['success']:
            # Get updated stats
            stats = sandhi_service.get_stats()
            result['stats'] = stats
            return jsonify(result)
        else:
            return jsonify(result), 500

    except Exception as e:
        logger.error(f"Error submitting sandhi marking: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/sandhi/stats', methods=['GET'])
def get_sandhi_stats():
    """Get statistics about marked and unmarked words"""
    try:
        sandhi_service = SandhiService()
        stats = sandhi_service.get_stats()
        return jsonify(stats)

    except Exception as e:
        logger.error(f"Error getting sandhi stats: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/health')
def health():
    return jsonify({"status": "healthy"})


if __name__ == '__main__':
    app.run(debug=True, threaded=True, port=5000)
