# DynamoDB Setup Guide for DrishtiSandhi

## Overview

This guide provides comprehensive documentation for setting up and managing DynamoDB tables for the DrishtiSandhi sandhi marking system.

## Table: `sandhi-corrections`

### Purpose
Stores user markings of sandhi split points in Sanskrit compound words from the SandhiKosh corpus.

### Schema Design

#### Primary Key
- **Partition Key**: `correction_id` (String)
  - UUID v4 format (e.g., `550e8400-e29b-41d4-a716-446655440000`)
  - Ensures unique identification of each marking
  - Enables efficient point lookups

- **Sort Key**: `timestamp` (Number)
  - Unix timestamp in milliseconds
  - Allows chronological ordering of markings
  - Enables time-range queries

#### Attributes

| Attribute | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `correction_id` | String | Yes | UUID for marking | `550e8400-e29b-41d4-a716-446655440000` |
| `timestamp` | Number | Yes | Unix timestamp (ms) | `1704067200000` |
| `corpus_entry_id` | String | Yes | Corpus word ID | `bhagavad_gita_1.1.1` |
| `word` | String | Yes | Sanskrit compound word | `धृतराष्ट्र उवाच` |
| `sandhi_points` | List[Number] | Yes | Character split positions | `[10]` or `[7, 15]` |
| `reference_split` | String | No | Original corpus split | `धृतराष्ट्रः+उवाच` |
| `sandhi_type` | String | No | Sandhi category | `visarga`, `consonant`, `vowel` |
| `source` | String | Yes | Corpus source | `bhagavad_gita`, `astaadhyaayii`, `uoh`, `rule_based` |
| `user_session_id` | String | No | Session identifier | `session_abc123` |

#### Global Secondary Index: `corpus-entry-index`

**Purpose**: Query all markings for a specific corpus entry

- **Partition Key**: `corpus_entry_id` (String)
- **Sort Key**: `timestamp` (Number)
- **Projection**: ALL (all attributes)

**Use Cases**:
- Retrieve all markings for a word
- Compare user markings with reference splits
- Identify consensus on sandhi points
- Track marking history per word

### Capacity and Performance

#### Provisioned Throughput
- **Read Capacity Units (RCU)**: 5
  - Supports ~5 strongly consistent reads/sec
  - Or ~10 eventually consistent reads/sec
- **Write Capacity Units (WCU)**: 5
  - Supports ~5 writes/sec

#### Cost Optimization
- Use **on-demand billing** for unpredictable traffic
- Switch to **provisioned** for steady, predictable load
- Monitor CloudWatch metrics: `ConsumedReadCapacityUnits`, `ConsumedWriteCapacityUnits`

### Data Access Patterns

#### 1. Create New Marking
```python
table.put_item(
    Item={
        'correction_id': str(uuid.uuid4()),
        'timestamp': int(datetime.now().timestamp() * 1000),
        'corpus_entry_id': 'bhagavad_gita_1.1.1',
        'word': 'धृतराष्ट्र उवाच',
        'sandhi_points': [10],
        'reference_split': 'धृतराष्ट्रः+उवाच',
        'sandhi_type': 'visarga',
        'source': 'bhagavad_gita'
    }
)
```

#### 2. Query Markings by Corpus Entry
```python
response = table.query(
    IndexName='corpus-entry-index',
    KeyConditionExpression='corpus_entry_id = :id',
    ExpressionAttributeValues={':id': 'bhagavad_gita_1.1.1'}
)
```

#### 3. Get Count of Unique Marked Words
```python
# Scan with projection to reduce data transfer
response = table.scan(ProjectionExpression='corpus_entry_id')
unique_ids = set(item['corpus_entry_id'] for item in response['Items'])

# Handle pagination
while 'LastEvaluatedKey' in response:
    response = table.scan(
        ProjectionExpression='corpus_entry_id',
        ExclusiveStartKey=response['LastEvaluatedKey']
    )
    unique_ids.update(item['corpus_entry_id'] for item in response['Items'])

marked_count = len(unique_ids)
```

#### 4. Get Recent Markings
```python
# Scan and sort by timestamp (inefficient for large datasets)
response = table.scan()
items = sorted(response['Items'], key=lambda x: x['timestamp'], reverse=True)
recent = items[:100]
```

## Setup Instructions

### Option 1: Using Python Script (Recommended)

```bash
# From project root
python scripts/create_sandhi_table.py
```

**Script Features**:
- Checks if table already exists
- Creates table with correct schema
- Sets up GSI automatically
- Waits for table to be active
- Displays table details

### Option 2: AWS CLI

```bash
aws dynamodb create-table \
    --table-name sandhi-corrections \
    --attribute-definitions \
        AttributeName=correction_id,AttributeType=S \
        AttributeName=timestamp,AttributeType=N \
        AttributeName=corpus_entry_id,AttributeType=S \
    --key-schema \
        AttributeName=correction_id,KeyType=HASH \
        AttributeName=timestamp,KeyType=RANGE \
    --global-secondary-indexes \
        '[
            {
                "IndexName": "corpus-entry-index",
                "KeySchema": [
                    {"AttributeName":"corpus_entry_id","KeyType":"HASH"},
                    {"AttributeName":"timestamp","KeyType":"RANGE"}
                ],
                "Projection": {"ProjectionType":"ALL"},
                "ProvisionedThroughput": {
                    "ReadCapacityUnits":5,
                    "WriteCapacityUnits":5
                }
            }
        ]' \
    --billing-mode PROVISIONED \
    --provisioned-throughput \
        ReadCapacityUnits=5,WriteCapacityUnits=5 \
    --region us-east-1
```

### Option 3: AWS Console

1. Go to DynamoDB Console
2. Click "Create table"
3. Configure:
   - **Table name**: `sandhi-corrections`
   - **Partition key**: `correction_id` (String)
   - **Sort key**: `timestamp` (Number)
4. Click "Create a global secondary index"
   - **Index name**: `corpus-entry-index`
   - **Partition key**: `corpus_entry_id` (String)
   - **Sort key**: `timestamp` (Number)
   - **Projected attributes**: All
5. Set capacity mode (Provisioned: 5 RCU, 5 WCU)
6. Click "Create table"

## Monitoring and Maintenance

### Key Metrics to Monitor

1. **ConsumedReadCapacityUnits**
   - Alert if > 80% of provisioned capacity
   - Action: Increase RCU or switch to on-demand

2. **ConsumedWriteCapacityUnits**
   - Alert if > 80% of provisioned capacity
   - Action: Increase WCU or switch to on-demand

3. **ThrottledRequests**
   - Alert if > 0
   - Action: Increase capacity or optimize queries

4. **UserErrors**
   - Monitor for application issues
   - Check `ValidationException`, `ConditionalCheckFailedException`

### Backup Strategy

#### Point-in-Time Recovery (PITR)
```bash
aws dynamodb update-continuous-backups \
    --table-name sandhi-corrections \
    --point-in-time-recovery-specification PointInTimeRecoveryEnabled=true
```

**Benefits**:
- Restore to any point in last 35 days
- No performance impact
- Automatic, continuous backups

#### On-Demand Backups
```bash
aws dynamodb create-backup \
    --table-name sandhi-corrections \
    --backup-name sandhi-corrections-backup-$(date +%Y%m%d)
```

### Data Export

#### Export to S3
```bash
aws dynamodb export-table-to-point-in-time \
    --table-arn arn:aws:dynamodb:us-east-1:ACCOUNT:table/sandhi-corrections \
    --s3-bucket my-export-bucket \
    --s3-prefix sandhi-exports/ \
    --export-format DYNAMODB_JSON
```

#### Export to JSON (via Python)
```python
import boto3
import json

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
table = dynamodb.Table('sandhi-corrections')

# Scan all items
response = table.scan()
items = response['Items']

while 'LastEvaluatedKey' in response:
    response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
    items.extend(response['Items'])

# Convert Decimals to floats
def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError

# Export to JSON
with open('sandhi-markings.json', 'w', encoding='utf-8') as f:
    json.dump(items, f, ensure_ascii=False, indent=2, default=decimal_default)
```

## Cost Estimation

### Provisioned Capacity (Current Settings)
- **RCU**: 5 × $0.00013/hour = $0.000650/hour
- **WCU**: 5 × $0.00065/hour = $0.003250/hour
- **GSI RCU**: 5 × $0.00013/hour = $0.000650/hour
- **GSI WCU**: 5 × $0.00065/hour = $0.003250/hour

**Monthly Cost** (730 hours): ~$5.70

### Storage
- **First 25 GB**: Free
- **Additional**: $0.25/GB/month

**Current Usage**: Minimal (~5 MB for 5 items)

### Total Monthly Cost (Estimated)
- **Provisioned capacity**: $5.70
- **Storage**: $0.00 (within free tier)
- **Total**: ~$5.70/month

## Troubleshooting

### Issue: ThrottledRequests

**Cause**: Exceeding provisioned capacity

**Solutions**:
1. Increase RCU/WCU
2. Enable auto-scaling
3. Switch to on-demand billing
4. Implement exponential backoff in application

### Issue: High Latency on GSI Queries

**Cause**: GSI not fully built or over-utilized

**Solutions**:
1. Check GSI status: `table.global_secondary_indexes[0]['IndexStatus']`
2. Ensure GSI has adequate capacity
3. Use projection to reduce data transfer
4. Consider query patterns and optimize

### Issue: Inconsistent Read Results

**Cause**: Using eventually consistent reads on GSI

**Solutions**:
1. GSIs only support eventually consistent reads
2. Design application to handle eventual consistency
3. Use main table for strongly consistent reads when needed

## Security Best Practices

### IAM Policy (Least Privilege)
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:Query",
        "dynamodb:Scan"
      ],
      "Resource": [
        "arn:aws:dynamodb:us-east-1:ACCOUNT:table/sandhi-corrections",
        "arn:aws:dynamodb:us-east-1:ACCOUNT:table/sandhi-corrections/index/*"
      ]
    }
  ]
}
```

### Encryption
- **At Rest**: Enabled by default (AWS-managed keys)
- **In Transit**: Use HTTPS endpoints
- **Option**: Use customer-managed KMS keys for enhanced control

## Future Enhancements

### Potential Optimizations

1. **Add LSI** for querying by timestamp within partition
2. **Add GSI** on `source` for source-specific queries
3. **Implement TTL** for old test/demo data
4. **Use DynamoDB Streams** for real-time processing
5. **Consider Aurora Serverless** for complex analytics

### Scaling Considerations

For **> 100K markings**:
- Switch to **on-demand billing**
- Implement **caching** (ElastiCache/Redis) for stats
- Use **DynamoDB Streams** + Lambda for aggregations
- Consider **materialized views** for common queries

## References

- [DynamoDB Developer Guide](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/)
- [DynamoDB Best Practices](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/best-practices.html)
- [DynamoDB Pricing](https://aws.amazon.com/dynamodb/pricing/)
