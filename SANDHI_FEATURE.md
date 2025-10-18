# DrishtiSandhi Feature

## Overview

DrishtiSandhi is a new feature for Sanskrit sandhi analysis and correction, integrated into the Drishti OCR application. It allows users to manually mark sandhi split points in Sanskrit compound words from the SandhiKosh corpus.

## Features Implemented (v1)

### Backend
1. **SandhiService** (`src/sandhi_service.py`)
   - Load and serve words from SandhiKosh corpus
   - Save sandhi corrections to DynamoDB
   - Support for pagination and random word selection
   - Query corrections by corpus entry ID

2. **API Endpoints** (added to `src/app.py`)
   - `GET /sandhi` - Serve the DrishtiSandhi page
   - `GET /api/sandhi/words` - Get paginated list of words (limit, offset)
   - `GET /api/sandhi/words/random` - Get random words (count)
   - `GET /api/sandhi/word/<word_id>` - Get specific word with corrections
   - `POST /api/sandhi/correction` - Submit sandhi correction

3. **DynamoDB Schema** (`sandhi-corrections` table)
   - Partition Key: `correction_id` (UUID)
   - Sort Key: `timestamp` (milliseconds)
   - Attributes: corpus_entry_id, word, sandhi_points, reference_split, sandhi_type, etc.
   - GSI: `corpus-entry-index` for querying by corpus entry

### Frontend
1. **DrishtiSandhi Page** (`templates/sandhi.html`)
   - Modern UI matching Drishti OCR design
   - Character-by-character word display in Devanagari
   - Interactive sandhi markers between characters
   - Click to toggle sandhi points
   - Visual feedback with checkmarks and highlighting
   - Reference split display from corpus
   - Statistics tracking (total words, corrections made)

### Data
1. **SandhiKosh Corpus** (`data/sandhikosh_bhagavad_gita.json`)
   - 1,430 entries from Bhagavad Gita
   - Format: {id, word, split, type}
   - Converted from Excel to JSON

## How to Use

1. **Start the application**
   ```bash
   python -m src.app
   ```

2. **Navigate to DrishtiSandhi**
   - Visit `http://localhost:5000/sandhi`

3. **Mark sandhi points**
   - Click on vertical lines between characters to mark sandhi split points
   - Multiple points can be marked in a single word
   - Click again to unmark

4. **Submit corrections**
   - Click "Submit Correction" to save your annotations
   - Data is stored in DynamoDB for future model training

5. **Navigate words**
   - Click "Next Word" to load a random word from the corpus
   - "Clear Marks" removes all current sandhi points

## Architecture

```
User → Frontend (sandhi.html)
         ↓
      Flask API (/api/sandhi/*)
         ↓
    SandhiService
         ↓
      DynamoDB (sandhi-corrections table)
```

## Future Enhancements (v2+)

1. **Model Integration**
   - Integrate sandhi detection model
   - Auto-suggest sandhi points
   - Show confidence scores

2. **Split Display**
   - Show actual split components
   - Visual comparison with reference

3. **Analytics**
   - Agreement scores between users
   - Most difficult words
   - Correction statistics

4. **Corpus Expansion**
   - Add other SandhiKosh corpora (Aṣṭādhyāyī, UoH, etc.)
   - Support custom text input

5. **Training Pipeline**
   - Export corrections for model training
   - Train custom sandhi models
   - A/B testing with models

## Files Changed/Added

### New Files
- `src/sandhi_service.py` - Sandhi service logic
- `templates/sandhi.html` - Frontend page
- `data/sandhikosh_bhagavad_gita.json` - Corpus data
- `data/sandhi_dynamodb_schema.md` - Schema documentation
- `scripts/create_sandhi_table.py` - DynamoDB table creation script
- `SANDHI_FEATURE.md` - This documentation

### Modified Files
- `src/app.py` - Added sandhi routes and import
- `src/config.py` - Added SANDHI_TABLE and SANDHI_DATA_PATH config

## DynamoDB Setup

To create the DynamoDB table:

```bash
python scripts/create_sandhi_table.py
```

Or create manually with:
- Table name: `sandhi-corrections`
- Partition key: `correction_id` (String)
- Sort key: `timestamp` (Number)
- GSI: `corpus-entry-index` (corpus_entry_id + timestamp)

## Data Source

The corpus data is sourced from [SandhiKosh](https://github.com/sanskrit-sandhi/SandhiKosh), the first Sanskrit Sandhi Benchmark created for evaluating Sanskrit Sandhi tools.

**Citation:**
> Hellwig, O., & Nehrdich, S. (2018). Sanskrit Word Segmentation Using Character-level Recurrent and Convolutional Neural Networks. In Proceedings of the 2018 Conference on Empirical Methods in Natural Language Processing (EMNLP 2018).

## License

This feature is part of the Drishti OCR project. The SandhiKosh data is used for research and educational purposes.
