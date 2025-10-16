# DynamoDB Design for Multi-Language OCR with Corrections

## Current State Analysis

### Current Schema (Problems)
```
Primary Key: id (UUID)
Attributes:
- file_id
- page
- word_index
- text (OCR output)
- confidence
- bbox
- timestamp
- word_image_filename (optional)
```

**Issues:**
1. ❌ No GSI on `file_id` - Can't efficiently query all words for a file
2. ❌ No language tracking - Can't filter by language
3. ❌ No correction mechanism - Can't store user corrections
4. ❌ No composite key for word lookup - Hard to find specific words
5. ❌ No training data flag - Can't identify which corrections to use for retraining

## Proposed Improved Schema

### Table: `ocr-results` (Enhanced)

#### Primary Key
- **Partition Key (PK)**: `file_id` (String)
- **Sort Key (SK)**: `page#word_index` (String) - e.g., "0001#0042"

#### Attributes
```json
{
  "file_id": "uuid",
  "page#word_index": "0001#0042",
  "word_id": "unique-word-uuid",

  // OCR Data
  "original_text": "संस्कृत",
  "corrected_text": "संस्कृतम्",  // User correction (null if not corrected)
  "confidence": 75.5,
  "language": "san+eng+hin",
  "detected_script": "Devanagari",

  // Bounding Box
  "bbox": {
    "x": 100,
    "y": 200,
    "width": 50,
    "height": 20
  },

  // S3 References
  "word_image_s3_key": "file-id/page_1/word_abc.png",
  "char_images_s3_keys": ["...char1.png", "...char2.png"],

  // Metadata
  "page": 1,
  "word_index": 42,
  "is_low_confidence": true,
  "is_corrected": false,
  "correction_count": 0,

  // Training Flags
  "approved_for_training": false,
  "correction_verified": false,

  // Timestamps
  "created_at": "2025-10-17T10:00:00Z",
  "updated_at": "2025-10-17T10:00:00Z",
  "corrected_at": null,

  // User Info (optional)
  "corrected_by": "user-id or session-id"
}
```

#### Global Secondary Indexes (GSIs)

**GSI-1: Language Query Index**
- PK: `language`
- SK: `confidence` (Number)
- Purpose: Find all words in a language, sorted by confidence
- Use case: "Show me all low-confidence Sanskrit words"

**GSI-2: Correction Index**
- PK: `is_corrected` (String: "true" or "false")
- SK: `corrected_at` (String)
- Purpose: Find all corrected words, sorted by when they were corrected
- Use case: "Get all corrections for training data"

**GSI-3: Training Data Index**
- PK: `approved_for_training` (String: "true" or "false")
- SK: `language#confidence` (String: "san#75.5")
- Purpose: Get approved corrections grouped by language and confidence
- Use case: "Get training data for Sanskrit model"

**GSI-4: Low Confidence Index**
- PK: `is_low_confidence` (String: "true" or "false")
- SK: `file_id#page#word_index`
- Purpose: Find all low-confidence words across all files
- Use case: "Show me all words that need review"

## New Table: `ocr-corrections-history` (Optional)

Track correction history for analytics and reversion.

```json
{
  "word_id": "uuid",
  "version": 1,
  "correction_text": "संस्कृतम्",
  "corrected_by": "user-id",
  "corrected_at": "timestamp",
  "confidence_before": 75.5,
  "reason": "User correction"
}
```

## Data Access Patterns

### 1. Get All Words for a File
```python
response = table.query(
    KeyConditionExpression=Key('file_id').eq(file_id)
)
```

### 2. Get Specific Word
```python
response = table.get_item(
    Key={
        'file_id': file_id,
        'page#word_index': f"{page:04d}#{word_idx:04d}"
    }
)
```

### 3. Get All Low-Confidence Words for a Language
```python
response = table.query(
    IndexName='GSI-1-language-confidence',
    KeyConditionExpression=Key('language').eq('san') & Key('confidence').lt(80)
)
```

### 4. Get All Corrected Words for Training
```python
response = table.query(
    IndexName='GSI-2-corrections',
    KeyConditionExpression=Key('is_corrected').eq('true'),
    FilterExpression=Attr('approved_for_training').eq(True)
)
```

### 5. Get All Words on a Page
```python
response = table.query(
    KeyConditionExpression=Key('file_id').eq(file_id) & Key('page#word_index').begins_with(f"{page:04d}#")
)
```

## Correction Workflow

### Frontend Flow
```
1. User clicks low-confidence word
2. Modal appears with:
   - Original OCR text
   - Word image
   - Character images
   - Editable text field
   - Confidence score
   - Language
3. User corrects text
4. Clicks "Submit Correction"
5. Optional: "Approve for Training" checkbox
```

### Backend API Endpoints

#### POST /api/correction
```json
{
  "file_id": "uuid",
  "page": 1,
  "word_index": 42,
  "corrected_text": "संस्कृतम्",
  "approve_for_training": true
}
```

#### GET /api/corrections?language=san&confidence_lt=80
Returns all corrections for a language below confidence threshold.

#### GET /api/word/{file_id}/{page}/{word_index}
Returns complete word data including images.

#### PUT /api/training-approval/{word_id}
Approve/reject correction for training.

## Migration Strategy

### Step 1: Create New Table Structure
```bash
aws dynamodb create-table \
  --table-name ocr-results-v2 \
  --attribute-definitions \
    AttributeName=file_id,AttributeType=S \
    AttributeName=page#word_index,AttributeType=S \
    AttributeName=language,AttributeType=S \
    AttributeName=confidence,AttributeType=N \
    AttributeName=is_corrected,AttributeType=S \
    AttributeName=corrected_at,AttributeType=S \
  --key-schema \
    AttributeName=file_id,KeyType=HASH \
    AttributeName=page#word_index,KeyType=RANGE \
  --global-secondary-indexes \
    '[{...GSI definitions...}]' \
  --billing-mode PAY_PER_REQUEST
```

### Step 2: Update Code to Use New Schema
- Modify `ocr_processor.py` to save with new structure
- Keep backward compatibility during transition

### Step 3: Migrate Existing Data (if any)
```python
# Scan old table, transform, write to new table
```

### Step 4: Update Table Name in Config
Point to `ocr-results-v2`.

## Future Enhancements

### 1. Similarity Search
Store word embeddings to find similar corrections:
```json
{
  "word_embedding": [0.123, 0.456, ...],  // Vector for similarity
  "similar_corrections": ["word1", "word2"]
}
```

### 2. Auto-Correction Suggestions
Use ML model to suggest corrections based on:
- Historical corrections
- Language context
- Character-level patterns

### 3. Batch Correction
Allow correcting multiple instances of the same word:
```
"If you see 'संस्कृत' -> correct all to 'संस्कृतम्'"
```

### 4. Analytics Dashboard
- Confidence distribution by language
- Most commonly corrected words
- Correction accuracy over time

## Storage Cost Estimate

Assuming:
- Average word: 50 bytes base + 200 bytes attributes = 250 bytes
- 1000 pages × 500 words/page = 500,000 words
- Storage: 500,000 × 250 bytes = 125 MB
- Cost: ~$0.03/month for storage
- Writes: 500,000 × $1.25/million = $0.625 one-time
- Reads: Negligible with on-demand pricing

## Query Cost Optimization

1. **Use Projections**: Only fetch needed attributes in GSIs
2. **Batch Operations**: Use BatchGetItem for multiple words
3. **Pagination**: Implement cursor-based pagination for large results
4. **Caching**: Cache frequently accessed words (Redis/ElastiCache)
5. **DynamoDB Streams**: Use for async processing of corrections

## Implementation Priority

### Phase 1 (MVP)
1. ✅ Add GSI on language
2. ✅ Add correction fields to schema
3. ✅ Implement correction API endpoint
4. ✅ Add inline editing UI
5. ✅ Update DynamoDB save logic

### Phase 2 (Enhanced)
1. Training data approval workflow
2. Correction history tracking
3. Batch corrections
4. Analytics dashboard

### Phase 3 (Advanced)
1. ML-based auto-suggestions
2. Similarity search
3. Collaborative corrections
4. Export training datasets

## Sample Code

### Saving with New Schema
```python
# In ocr_processor.py
db_item = {
    "file_id": file_id,
    "page#word_index": f"{page_num:04d}#{word_index:04d}",
    "word_id": str(uuid.uuid4()),
    "original_text": text,
    "corrected_text": None,
    "confidence": float(conf),
    "language": self.tesseract_lang,
    "detected_script": detect_script(text),
    "bbox": word_data["bbox"],
    "word_image_s3_key": word_data.get("image_filename"),
    "page": page_num,
    "word_index": word_index,
    "is_low_confidence": "true" if conf < 80 else "false",
    "is_corrected": "false",
    "correction_count": 0,
    "approved_for_training": False,
    "created_at": datetime.utcnow().isoformat(),
    "updated_at": datetime.utcnow().isoformat()
}
```

### Correction API
```python
@app.route('/api/correction', methods=['POST'])
def submit_correction():
    data = request.json

    # Update item
    table.update_item(
        Key={
            'file_id': data['file_id'],
            'page#word_index': f"{data['page']:04d}#{data['word_index']:04d}"
        },
        UpdateExpression="SET corrected_text = :text, is_corrected = :is_corrected, corrected_at = :timestamp, approved_for_training = :approved",
        ExpressionAttributeValues={
            ':text': data['corrected_text'],
            ':is_corrected': 'true',
            ':timestamp': datetime.utcnow().isoformat(),
            ':approved': data.get('approve_for_training', False)
        }
    )

    return jsonify({"success": True})
```

Would you like me to implement this new schema and correction workflow?
