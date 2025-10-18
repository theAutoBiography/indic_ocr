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

import re

logger = logging.getLogger(__name__)


def segment_devanagari(text: str) -> List[str]:
    """
    Segment Devanagari text into grapheme clusters (aksharas).
    Keeps consonants with their vowel marks and conjuncts together.

    Args:
        text: Devanagari text

    Returns:
        List of grapheme clusters
    """
    # Unicode ranges for Devanagari
    # Consonants: 0905-0939
    # Vowel signs (maatras): 093E-094C, 0962-0963
    # Virama (halant): 094D
    # Other marks: 0901-0903, 093C, 094D, 0951-0954

    graphemes = []
    i = 0

    while i < len(text):
        char = text[i]
        cluster = char

        # Skip non-Devanagari characters (spaces, punctuation)
        if ord(char) < 0x0900 or ord(char) > 0x097F:
            graphemes.append(char)
            i += 1
            continue

        # Start building cluster
        j = i + 1

        # Collect all combining marks, virama, and subsequent consonants (for conjuncts)
        while j < len(text):
            next_char = text[j]
            code = ord(next_char)

            # Vowel signs (maatras): 093E-094C, 0962-0963
            # Virama: 094D
            # Other combining marks: 0901-0903, 093C, 0951-0954
            if ((0x093E <= code <= 0x094C) or  # Vowel signs
                (0x0962 <= code <= 0x0963) or  # Vocalic L/LL
                (0x0901 <= code <= 0x0903) or  # Candrabindu, Anusvara, Visarga
                code == 0x093C or              # Nukta
                (0x0951 <= code <= 0x0954)):   # Stress marks
                cluster += next_char
                j += 1
            # Virama followed by consonant = conjunct
            elif code == 0x094D:
                cluster += next_char
                j += 1
                # Check if next is consonant
                if j < len(text) and 0x0915 <= ord(text[j]) <= 0x0939:
                    cluster += text[j]
                    j += 1
                else:
                    break
            else:
                break

        graphemes.append(cluster)
        i = j

    return graphemes


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
            Word data with transliteration and grapheme segmentation
        """
        for word in self.corpus_data:
            if word['id'] == word_id:
                # Add IITHLP transliteration
                word_copy = word.copy()

                # Segment Devanagari into grapheme clusters
                graphemes = segment_devanagari(word['word'])
                word_copy['graphemes'] = graphemes

                if iithlp:
                    try:
                        # Transliterate full word
                        full_transliteration = iithlp.to_roman(word['word'])
                        word_copy['transliteration'] = full_transliteration

                        # Transliterate each grapheme individually for 1:1 mapping
                        trans_segments = []
                        for grapheme in graphemes:
                            try:
                                trans = iithlp.to_roman(grapheme).strip()
                                trans_segments.append(trans)
                            except:
                                trans_segments.append('')

                        word_copy['transliteration_segments'] = trans_segments
                    except Exception as e:
                        logger.error(f"Error transliterating word: {e}")
                        word_copy['transliteration'] = ''
                        word_copy['transliteration_segments'] = [''] * len(graphemes)
                else:
                    word_copy['transliteration'] = ''
                    word_copy['transliteration_segments'] = [''] * len(graphemes)

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

    def get_markings_for_word(self, corpus_entry_id: str) -> List[Dict]:
        """
        Get all markings for a specific corpus entry

        Args:
            corpus_entry_id: The corpus entry ID

        Returns:
            List of markings
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
            logger.error(f"Error fetching markings: {str(e)}")
            return []

    def get_marked_words_count(self) -> int:
        """
        Get count of unique words that have been marked

        Returns:
            Number of unique corpus entries that have markings
        """
        try:
            # Scan all items and get unique corpus_entry_ids
            marked_ids = set()

            # Scan with pagination
            response = self.table.scan(
                ProjectionExpression='corpus_entry_id'
            )

            for item in response.get('Items', []):
                marked_ids.add(item['corpus_entry_id'])

            # Handle pagination
            while 'LastEvaluatedKey' in response:
                response = self.table.scan(
                    ProjectionExpression='corpus_entry_id',
                    ExclusiveStartKey=response['LastEvaluatedKey']
                )
                for item in response.get('Items', []):
                    marked_ids.add(item['corpus_entry_id'])

            return len(marked_ids)

        except Exception as e:
            logger.error(f"Error getting marked words count: {str(e)}")
            return 0

    def get_stats(self) -> Dict:
        """
        Get statistics about marked and unmarked words

        Returns:
            Dict with total_words, marked_words, unmarked_words
        """
        total_words = len(self.corpus_data)
        marked_words = self.get_marked_words_count()
        unmarked_words = total_words - marked_words

        return {
            'total_words': total_words,
            'marked_words': marked_words,
            'unmarked_words': unmarked_words
        }

    def get_random_words(self, count: int = 10) -> List[Dict]:
        """
        Get random words from the corpus

        Args:
            count: Number of random words to return

        Returns:
            List of random words with transliteration and grapheme segmentation
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

            # Segment Devanagari into grapheme clusters
            graphemes = segment_devanagari(word['word'])
            word_copy['graphemes'] = graphemes

            if iithlp:
                try:
                    # Transliterate full word
                    full_transliteration = iithlp.to_roman(word['word'])
                    word_copy['transliteration'] = full_transliteration

                    # Transliterate each grapheme individually for 1:1 mapping
                    trans_segments = []
                    for grapheme in graphemes:
                        try:
                            trans = iithlp.to_roman(grapheme).strip()
                            trans_segments.append(trans)
                        except:
                            trans_segments.append('')

                    word_copy['transliteration_segments'] = trans_segments
                except Exception as e:
                    logger.error(f"Error transliterating word: {e}")
                    word_copy['transliteration'] = ''
                    word_copy['transliteration_segments'] = [''] * len(graphemes)
            else:
                word_copy['transliteration'] = ''
                word_copy['transliteration_segments'] = [''] * len(graphemes)

            result.append(word_copy)

        return result
