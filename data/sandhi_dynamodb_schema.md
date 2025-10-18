# Sandhi Corrections DynamoDB Schema

## Table Name
`sandhi-corrections`

## Schema Design

### Primary Key
- **Partition Key**: `correction_id` (String) - UUID for each correction
- **Sort Key**: `timestamp` (Number) - Unix timestamp in milliseconds

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| correction_id | String | UUID - unique identifier for each correction |
| timestamp | Number | Unix timestamp in milliseconds (sort key) |
| corpus_entry_id | String | ID from SandhiKosh corpus (e.g., "1.1.1") |
| word | String | Original compound word (e.g., "धृतराष्ट्र उवाच") |
| sandhi_points | List | Array of character positions where sandhi occurs [5, 12] |
| reference_split | String | Original split from corpus (e.g., "धृतराष्ट्रः+उवाच") |
| sandhi_type | String | Type of sandhi (consonant, visarga, etc.) |
| user_session_id | String | Optional - session identifier for tracking |
| source | String | Source corpus (e.g., "bhagavad_gita") |

### Global Secondary Index (Optional)
- **Index Name**: `corpus-entry-index`
- **Partition Key**: `corpus_entry_id`
- **Sort Key**: `timestamp`
- **Purpose**: Query all corrections for a specific corpus entry

## Example Item

```json
{
  "correction_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": 1704067200000,
  "corpus_entry_id": "1.1.1",
  "word": "धृतराष्ट्र उवाच",
  "sandhi_points": [10],
  "reference_split": "धृतराष्ट्रः+उवाच",
  "sandhi_type": "visarga",
  "user_session_id": "session_abc123",
  "source": "bhagavad_gita"
}
```

## Notes
- `sandhi_points` stores character positions (0-indexed) where sandhi splits occur
- Multiple sandhi points can exist in a single word
- Character positions refer to Unicode character positions in the Devanagari word
