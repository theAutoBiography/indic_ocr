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
                                if not trans:
                                    # If transliteration is empty, log and keep grapheme
                                    logger.warning(f"Empty transliteration for grapheme: '{grapheme}'")
                                trans_segments.append(trans)
                            except Exception as e:
                                logger.error(f"Error transliterating grapheme '{grapheme}': {e}")
                                trans_segments.append('')

                        word_copy['transliteration_segments'] = trans_segments
                    except Exception as e:
                        logger.error(f"Error transliterating word '{word['word']}': {e}")
                        word_copy['transliteration'] = ''
                        word_copy['transliteration_segments'] = [''] * len(graphemes)
                else:
                    word_copy['transliteration'] = ''
                    word_copy['transliteration_segments'] = [''] * len(graphemes)

                return word_copy
        return None

    def save_correction(self, corpus_entry_id: str, word: str, sandhi_points: List[int],
                       reference_split: str = "", sandhi_type: str = "",
                       user_session_id: Optional[str] = None,
                       transliteration: str = "", graphemes: List[str] = None,
                       transliteration_segments: List[str] = None) -> Dict:
        """
        Save a sandhi marking to DynamoDB

        Args:
            corpus_entry_id: ID from SandhiKosh corpus
            word: Original compound word
            sandhi_points: List of character positions where sandhi occurs
            reference_split: Original split from corpus
            sandhi_type: Type of sandhi (consonant, visarga, etc.)
            user_session_id: Optional session identifier
            transliteration: Full IITHLP transliteration
            graphemes: List of Devanagari graphemes
            transliteration_segments: List of transliterated graphemes

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

            # Add transliteration data if available
            if transliteration:
                item['transliteration'] = transliteration
            if graphemes:
                item['graphemes'] = graphemes
            if transliteration_segments:
                item['transliteration_segments'] = transliteration_segments

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

    def get_user_confirmed_sandhi_words(self, limit: int = 50) -> List[Dict]:
        """
        Get words from OCR results where users confirmed sandhi (has_sandhi = true)

        Args:
            limit: Maximum number of words to return

        Returns:
            List of user-confirmed sandhi words with transliteration and graphemes
        """
        try:
            table = self.aws_service.dynamodb.Table(Config.DYNAMODB_TABLE)

            # Scan for user-confirmed sandhi words
            response = table.scan(
                FilterExpression='has_sandhi = :true',
                ExpressionAttributeValues={
                    ':true': True
                },
                Limit=limit
            )

            ocr_words = []
            for item in response.get('Items', []):
                word_text = item.get('corrected_text') or item.get('original_text', '')

                # Skip non-Devanagari or empty words
                if not word_text or not any('\u0900' <= c <= '\u097F' for c in word_text):
                    continue

                # Segment and transliterate
                graphemes = segment_devanagari(word_text)

                word_entry = {
                    'id': f"ocr_user_{item.get('word_id', '')}",
                    'word': word_text,
                    'split': '',  # OCR words don't have reference splits
                    'type': 'user-confirmed',
                    'source': 'ocr-user',
                    'file_id': item.get('file_id'),
                    'page': item.get('page'),
                    'word_index': item.get('word_index'),
                    'ocr_confidence': float(item.get('confidence', 0)),
                    'was_corrected': item.get('is_corrected') == 'true',
                    'graphemes': graphemes
                }

                # Add sandhi detection data if available
                if item.get('sandhi_detected') is not None:
                    word_entry['sandhi_confidence'] = float(item.get('sandhi_confidence', 0))
                    word_entry['sandhi_types'] = item.get('sandhi_types', [])
                    word_entry['sandhi_indicators'] = item.get('sandhi_indicators', [])

                # Add transliteration
                if iithlp:
                    try:
                        full_transliteration = iithlp.to_roman(word_text)
                        word_entry['transliteration'] = full_transliteration

                        trans_segments = []
                        for grapheme in graphemes:
                            try:
                                trans = iithlp.to_roman(grapheme).strip()
                                trans_segments.append(trans)
                            except Exception as e:
                                logger.error(f"Error transliterating grapheme '{grapheme}': {e}")
                                trans_segments.append('')

                        word_entry['transliteration_segments'] = trans_segments
                    except Exception as e:
                        logger.error(f"Error transliterating OCR word '{word_text}': {e}")
                        word_entry['transliteration'] = ''
                        word_entry['transliteration_segments'] = [''] * len(graphemes)
                else:
                    word_entry['transliteration'] = ''
                    word_entry['transliteration_segments'] = [''] * len(graphemes)

                ocr_words.append(word_entry)

            return ocr_words

        except Exception as e:
            logger.error(f"Error fetching user-confirmed sandhi words: {e}")
            return []

    def get_ocr_sandhi_words(self, limit: int = 50, min_confidence: float = 0.5, include_user_confirmed: bool = True) -> List[Dict]:
        """
        Get words from OCR results that have sandhi (auto-detected or user-confirmed)

        Args:
            limit: Maximum number of words to return
            min_confidence: Minimum sandhi confidence threshold for auto-detected (0.0 to 1.0)
            include_user_confirmed: Include words where users confirmed sandhi

        Returns:
            List of words with sandhi detection data, transliteration, and graphemes
        """
        try:
            table = self.aws_service.dynamodb.Table(Config.DYNAMODB_TABLE)

            all_ocr_words = []

            # Get user-confirmed sandhi words first (highest priority)
            if include_user_confirmed:
                user_words = self.get_user_confirmed_sandhi_words(limit=limit)
                all_ocr_words.extend(user_words)

            # Then get auto-detected words if we haven't reached the limit
            remaining_limit = limit - len(all_ocr_words)
            if remaining_limit > 0:
                # Scan for auto-detected sandhi words
                response = table.scan(
                    FilterExpression='sandhi_detected = :true AND sandhi_confidence >= :min_conf',
                    ExpressionAttributeValues={
                        ':true': True,
                        ':min_conf': Decimal(str(min_confidence))
                    },
                    Limit=remaining_limit * 2  # Get more to filter duplicates
                )

                # Filter out duplicates (words already in user-confirmed list)
                user_word_ids = {w['id'] for w in all_ocr_words}

                for item in response.get('Items', []):
                    word_id = f"ocr_{item.get('word_id', '')}"

                    # Skip if already in user-confirmed list
                    if word_id in user_word_ids:
                        continue

                    # Create word entry similar to corpus format
                    word_text = item.get('original_text', '')

                    # Skip non-Devanagari or empty words
                    if not word_text or not any('\u0900' <= c <= '\u097F' for c in word_text):
                        continue

                    # Segment and transliterate
                    graphemes = segment_devanagari(word_text)

                    word_entry = {
                        'id': word_id,
                        'word': word_text,
                        'split': '',  # OCR words don't have reference splits
                        'type': 'ocr-detected',
                        'source': 'ocr',
                        'file_id': item.get('file_id'),
                        'page': item.get('page'),
                        'word_index': item.get('word_index'),
                        'ocr_confidence': float(item.get('confidence', 0)),
                        'sandhi_confidence': float(item.get('sandhi_confidence', 0)),
                        'sandhi_types': item.get('sandhi_types', []),
                        'sandhi_indicators': item.get('sandhi_indicators', []),
                        'graphemes': graphemes
                    }

                    # Add transliteration
                    if iithlp:
                        try:
                            full_transliteration = iithlp.to_roman(word_text)
                            word_entry['transliteration'] = full_transliteration

                            trans_segments = []
                            for grapheme in graphemes:
                                try:
                                    trans = iithlp.to_roman(grapheme).strip()
                                    trans_segments.append(trans)
                                except Exception as e:
                                    logger.error(f"Error transliterating grapheme '{grapheme}': {e}")
                                    trans_segments.append('')

                            word_entry['transliteration_segments'] = trans_segments
                        except Exception as e:
                            logger.error(f"Error transliterating OCR word '{word_text}': {e}")
                            word_entry['transliteration'] = ''
                            word_entry['transliteration_segments'] = [''] * len(graphemes)
                    else:
                        word_entry['transliteration'] = ''
                        word_entry['transliteration_segments'] = [''] * len(graphemes)

                    all_ocr_words.append(word_entry)

                    # Stop if we've reached the limit
                    if len(all_ocr_words) >= limit:
                        break

            return all_ocr_words[:limit]  # Ensure we don't exceed limit

        except Exception as e:
            logger.error(f"Error fetching OCR sandhi words: {e}")
            return []

    def get_random_words(self, count: int = 10, include_ocr: bool = False) -> List[Dict]:
        """
        Get random words from the corpus and optionally OCR results

        Args:
            count: Number of random words to return
            include_ocr: If True, mix in words from OCR with sandhi detected

        Returns:
            List of random words with transliteration and grapheme segmentation
        """
        import random

        result = []

        # Get corpus words
        corpus_count = count
        if include_ocr:
            corpus_count = int(count * 0.7)  # 70% from corpus, 30% from OCR

        if corpus_count >= len(self.corpus_data):
            selected_corpus = self.corpus_data
        else:
            selected_corpus = random.sample(self.corpus_data, corpus_count)

        # Add transliteration to each corpus word
        for word in selected_corpus:
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
                            if not trans:
                                # If transliteration is empty, log and keep grapheme
                                logger.warning(f"Empty transliteration for grapheme: '{grapheme}'")
                            trans_segments.append(trans)
                        except Exception as e:
                            logger.error(f"Error transliterating grapheme '{grapheme}': {e}")
                            trans_segments.append('')

                    word_copy['transliteration_segments'] = trans_segments
                except Exception as e:
                    logger.error(f"Error transliterating word '{word['word']}': {e}")
                    word_copy['transliteration'] = ''
                    word_copy['transliteration_segments'] = [''] * len(graphemes)
            else:
                word_copy['transliteration'] = ''
                word_copy['transliteration_segments'] = [''] * len(graphemes)

            result.append(word_copy)

        # Add OCR words if requested
        if include_ocr:
            ocr_count = count - len(result)
            if ocr_count > 0:
                ocr_words = self.get_ocr_sandhi_words(limit=ocr_count * 2, min_confidence=0.5)
                if ocr_words:
                    selected_ocr = random.sample(ocr_words, min(ocr_count, len(ocr_words)))
                    result.extend(selected_ocr)

        # Shuffle the combined list
        if include_ocr:
            random.shuffle(result)

        return result
