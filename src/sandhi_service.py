import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Dict, Optional
from src.config import Config
from src.aws_service import AWSService
import logging

try:
    import iithlp
except ImportError:
    iithlp = None

logger = logging.getLogger(__name__)


class SandhiService:
    def __init__(self):
        self.aws_service = AWSService()
        self.table = self.aws_service.dynamodb.Table(Config.SANDHI_TABLE)
        self.corpus_data = self._load_corpus()

    def _load_corpus(self) -> List[Dict]:
        """Load SandhiKosh corpus from JSON file"""
        try:
            with open(Config.SANDHI_DATA_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"Corpus file not found: {Config.SANDHI_DATA_PATH}")
            return []
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in corpus file: {Config.SANDHI_DATA_PATH}")
            return []

    def get_words(self, limit: int = 50, offset: int = 0) -> Dict:
        """
        Get paginated list of words from corpus

        Args:
            limit: Number of words to return
            offset: Starting position

        Returns:
            Dict with words, total count, and pagination info
        """
        total = len(self.corpus_data)
        words = self.corpus_data[offset:offset + limit]

        return {
            'words': words,
            'total': total,
            'limit': limit,
            'offset': offset,
            'has_more': offset + limit < total
        }

    def get_word_by_id(self, word_id: str) -> Optional[Dict]:
        """
        Get a specific word by its corpus ID

        Args:
            word_id: The corpus entry ID

        Returns:
            Word data or None if not found
        """
        for word in self.corpus_data:
            if word['id'] == word_id:
                # Add IITHLP transliteration
                word_copy = word.copy()
                if iithlp:
                    try:
                        word_copy['transliteration'] = iithlp.to_roman(word['word'])
                    except Exception as e:
                        logger.error(f"Error transliterating word: {e}")
                        word_copy['transliteration'] = ''
                else:
                    word_copy['transliteration'] = ''
                return word_copy
        return None

    def save_correction(self, corpus_entry_id: str, word: str, sandhi_points: List[int],
                       reference_split: str = "", sandhi_type: str = "",
                       user_session_id: Optional[str] = None) -> Dict:
        """
        Save a sandhi correction to DynamoDB

        Args:
            corpus_entry_id: ID from SandhiKosh corpus
            word: Original compound word
            sandhi_points: List of character positions where sandhi occurs
            reference_split: Original split from corpus
            sandhi_type: Type of sandhi (consonant, visarga, etc.)
            user_session_id: Optional session identifier

        Returns:
            Dict with success status and correction details
        """
        try:
            correction_id = str(uuid.uuid4())
            timestamp = int(datetime.now().timestamp() * 1000)

            # Extract source from corpus_entry_id (format: source_id)
            word_source = corpus_entry_id.split('_')[0] if '_' in corpus_entry_id else 'unknown'

            item = {
                'correction_id': correction_id,
                'timestamp': timestamp,
                'corpus_entry_id': corpus_entry_id,
                'word': word,
                'sandhi_points': sandhi_points,
                'reference_split': reference_split,
                'sandhi_type': sandhi_type,
                'source': word_source
            }

            if user_session_id:
                item['user_session_id'] = user_session_id

            self.table.put_item(Item=item)

            return {
                'success': True,
                'correction_id': correction_id,
                'timestamp': timestamp
            }

        except Exception as e:
            logger.error(f"Error saving sandhi correction: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    def get_corrections_for_word(self, corpus_entry_id: str) -> List[Dict]:
        """
        Get all corrections for a specific corpus entry

        Args:
            corpus_entry_id: The corpus entry ID

        Returns:
            List of corrections
        """
        try:
            response = self.table.query(
                IndexName='corpus-entry-index',
                KeyConditionExpression='corpus_entry_id = :id',
                ExpressionAttributeValues={
                    ':id': corpus_entry_id
                }
            )

            return response.get('Items', [])

        except Exception as e:
            logger.error(f"Error fetching corrections: {str(e)}")
            return []

    def get_random_words(self, count: int = 10) -> List[Dict]:
        """
        Get random words from the corpus

        Args:
            count: Number of random words to return

        Returns:
            List of random words with transliteration
        """
        import random

        if count >= len(self.corpus_data):
            selected_words = self.corpus_data
        else:
            selected_words = random.sample(self.corpus_data, count)

        # Add transliteration to each word
        result = []
        for word in selected_words:
            word_copy = word.copy()
            if iithlp:
                try:
                    word_copy['transliteration'] = iithlp.to_roman(word['word'])
                except Exception as e:
                    logger.error(f"Error transliterating word: {e}")
                    word_copy['transliteration'] = ''
            else:
                word_copy['transliteration'] = ''
            result.append(word_copy)

        return result
