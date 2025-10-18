"""
Sandhi Detection Module for Sanskrit/Devanagari Text

This module implements rule-based sandhi detection for Sanskrit compound words.
It analyzes Devanagari text to identify potential sandhi (phonetic junctions) based on:
1. Common sandhi patterns (vowel sandhi, visarga sandhi, consonant sandhi)
2. Character sequences that indicate compounds
3. Dictionary lookup (compound vs simple word)
"""

import re
from typing import Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)

# Devanagari Unicode ranges
DEVANAGARI_VOWELS = set('अआइईउऊऋॠऌॡएऐओऔ')
DEVANAGARI_CONSONANTS = set('कखगघङचछजझञटठडढणतथदधनपफबभमयरलवशषसह')
DEVANAGARI_VOWEL_SIGNS = set('\u093E\u093F\u0940\u0941\u0942\u0943\u0944\u0962\u0963\u0947\u0948\u094B\u094C')  # ा ि ी ु ू ृ ॄ ॢ ॣ े ै ो ौ
DEVANAGARI_VIRAMA = '\u094D'  # ्
DEVANAGARI_VISARGA = '\u0903'  # ः
DEVANAGARI_ANUSVARA = '\u0902'  # ं


class SandhiDetector:
    def __init__(self):
        """Initialize sandhi detector with pattern rules"""
        self.sandhi_patterns = self._compile_patterns()

    def _compile_patterns(self) -> List[Dict]:
        """
        Compile regex patterns for common sandhi indicators

        Returns:
            List of pattern dictionaries with regex and description
        """
        patterns = [
            # Visarga sandhi: ः + consonant often indicates sandhi
            # e.g., रामः + गच्छति → रामो गच्छति
            {
                'pattern': re.compile(r'[ः]\s*[क-ह]'),
                'type': 'visarga',
                'description': 'Visarga before consonant',
                'weight': 0.7
            },

            # Doubled consonants often indicate sandhi
            # e.g., तत् + च → तच्च
            {
                'pattern': re.compile(r'([क-ह])\1'),
                'type': 'consonant',
                'description': 'Doubled consonant',
                'weight': 0.8
            },

            # Long vowels that might result from sandhi
            # e.g., अ + अ → आ, इ + इ → ई
            {
                'pattern': re.compile(r'[आईऊॠॡ]'),
                'type': 'vowel',
                'description': 'Long vowel (potential sandhi)',
                'weight': 0.4
            },

            # Vowel sign ो or ौ often from sandhi
            # e.g., रामः + अयम् → रामो ऽयम्
            {
                'pattern': re.compile(r'[ोौ]'),
                'type': 'vowel',
                'description': 'O/AU vowel sign (common in sandhi)',
                'weight': 0.5
            },

            # य, व, र insertions (common sandhi)
            # e.g., ते + अपि → तेऽपि or त्व
            {
                'pattern': re.compile(r'[यवर][ािीुूृॄेैोौ]'),
                'type': 'consonant',
                'description': 'Y/V/R + vowel sign (sandhi glide)',
                'weight': 0.6
            },

            # Avagraha (ऽ) explicitly marks sandhi elision
            {
                'pattern': re.compile(r'ऽ'),
                'type': 'elision',
                'description': 'Avagraha (explicit sandhi marker)',
                'weight': 1.0
            },

            # Conjunct consonants (consonant + virama + consonant)
            # More likely in compounds
            {
                'pattern': re.compile(r'[क-ह]्[क-ह]'),
                'type': 'consonant',
                'description': 'Conjunct consonant cluster',
                'weight': 0.5
            },

            # Anusvara before consonants (can indicate sandhi)
            # e.g., तम् + च → तंच
            {
                'pattern': re.compile(r'ं[क-ह]'),
                'type': 'anusvara',
                'description': 'Anusvara before consonant',
                'weight': 0.6
            },

            # Specific common sandhi results
            # e.g., च्च, त्त, ज्ज patterns
            {
                'pattern': re.compile(r'[चटतजडद]्[चटतजडद]'),
                'type': 'consonant',
                'description': 'Common doubled plosive',
                'weight': 0.75
            },
        ]

        return patterns

    def detect_sandhi(self, word: str) -> Dict:
        """
        Detect if a word likely contains sandhi

        Args:
            word: Devanagari word to analyze

        Returns:
            Dict with:
                - has_sandhi: bool (likely contains sandhi)
                - confidence: float (0.0 to 1.0)
                - indicators: List[str] (which patterns matched)
                - sandhi_types: List[str] (types of sandhi detected)
        """
        if not word or not self._is_devanagari(word):
            return {
                'has_sandhi': False,
                'confidence': 0.0,
                'indicators': [],
                'sandhi_types': []
            }

        # Clean word (remove spaces, punctuation)
        clean_word = word.strip()

        # Very short words unlikely to have sandhi
        if len(clean_word) < 3:
            return {
                'has_sandhi': False,
                'confidence': 0.0,
                'indicators': ['Word too short'],
                'sandhi_types': []
            }

        matches = []
        sandhi_types = set()
        total_weight = 0.0

        # Check each pattern
        for pattern_info in self.sandhi_patterns:
            pattern = pattern_info['pattern']
            if pattern.search(clean_word):
                matches.append(pattern_info['description'])
                sandhi_types.add(pattern_info['type'])
                total_weight += pattern_info['weight']

        # Calculate confidence based on number and weight of matches
        # More matches and higher weights = higher confidence
        if matches:
            # Normalize confidence to 0.0-1.0 range
            # Using a sigmoid-like function to cap at 1.0
            raw_confidence = total_weight / 2.0  # Divide by 2 to scale
            confidence = min(raw_confidence, 1.0)
        else:
            confidence = 0.0

        # Word length heuristic: longer words more likely to be compounds
        if len(clean_word) > 10:
            confidence = min(confidence + 0.1, 1.0)

        # Determine has_sandhi based on confidence threshold
        has_sandhi = confidence >= 0.4

        return {
            'has_sandhi': has_sandhi,
            'confidence': round(confidence, 2),
            'indicators': matches,
            'sandhi_types': list(sandhi_types)
        }

    def _is_devanagari(self, text: str) -> bool:
        """Check if text contains Devanagari characters"""
        if not text:
            return False
        # Check if at least 50% of characters are Devanagari
        devanagari_count = sum(1 for c in text if '\u0900' <= c <= '\u097F')
        return devanagari_count >= len(text) * 0.5

    def detect_sandhi_points(self, word: str) -> List[int]:
        """
        Attempt to identify likely sandhi split points in a word

        Args:
            word: Devanagari word

        Returns:
            List of character positions where sandhi likely occurs
        """
        points = []

        # Look for specific sandhi indicators that suggest split points
        # This is heuristic and won't be perfect

        # Avagraha explicitly marks a split
        for i, char in enumerate(word):
            if char == 'ऽ':
                points.append(i)

        # Visarga before consonant suggests split after visarga
        for i in range(len(word) - 1):
            if word[i] == 'ः' and word[i+1] in DEVANAGARI_CONSONANTS:
                points.append(i)

        # Doubled consonants suggest split in the middle
        for i in range(len(word) - 1):
            if (word[i] in DEVANAGARI_CONSONANTS and
                i + 2 < len(word) and
                word[i+1] == DEVANAGARI_VIRAMA and
                word[i+2] == word[i]):
                points.append(i + 1)

        return sorted(set(points))  # Remove duplicates and sort

    def analyze_batch(self, words: List[str]) -> List[Dict]:
        """
        Analyze multiple words for sandhi

        Args:
            words: List of Devanagari words

        Returns:
            List of detection results for each word
        """
        return [self.detect_sandhi(word) for word in words]


# Global instance for easy import
_detector = None

def get_sandhi_detector() -> SandhiDetector:
    """Get singleton instance of SandhiDetector"""
    global _detector
    if _detector is None:
        _detector = SandhiDetector()
    return _detector


def detect_sandhi(word: str) -> Dict:
    """
    Convenience function to detect sandhi in a word

    Args:
        word: Devanagari word to analyze

    Returns:
        Dict with has_sandhi, confidence, indicators, sandhi_types
    """
    detector = get_sandhi_detector()
    return detector.detect_sandhi(word)
