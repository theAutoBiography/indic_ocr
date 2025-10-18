#!/bin/bash
# Add DynamoDB permissions for sandhi-corrections table to DrishtiOCRLambdaRole

ROLE_NAME="DrishtiOCRLambdaRole"
POLICY_NAME="SandhiCorrectionsAccess"
TABLE_ARN="arn:aws:dynamodb:us-east-1:344505381942:table/sandhi-corrections"
REGION="us-east-1"

echo "Adding sandhi-corrections table permissions to ${ROLE_NAME}..."

# Create policy document
POLICY_DOCUMENT=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:Query",
        "dynamodb:Scan",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:BatchGetItem",
        "dynamodb:BatchWriteItem"
      ],
      "Resource": [
        "${TABLE_ARN}",
        "${TABLE_ARN}/index/*"
      ]
    }
  ]
}
EOF
)

# Add inline policy to role
aws iam put-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-name "${POLICY_NAME}" \
  --policy-document "${POLICY_DOCUMENT}" \
  --region "${REGION}"

if [ $? -eq 0 ]; then
  echo "✓ Successfully added sandhi-corrections permissions to ${ROLE_NAME}"
  echo ""
  echo "Permissions granted:"
  echo "  - PutItem (create new sandhi markings)"
  echo "  - GetItem (retrieve specific markings)"
  echo "  - Query (query by corpus_entry_id via GSI)"
  echo "  - Scan (get all markings, stats)"
  echo "  - UpdateItem, DeleteItem (modify markings)"
  echo ""
  echo "Note: ECS tasks may need to be restarted to pick up new permissions."
else
  echo "✗ Failed to add permissions. Check AWS credentials and role name."
  exit 1
fi
