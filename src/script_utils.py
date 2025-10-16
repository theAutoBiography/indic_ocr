"""
Utility functions for detecting script/writing system from text
"""

import re


def detect_script(text):
    """
    Detect the script/writing system of the given text.
    Returns the most dominant script found.
    """
    if not text or not text.strip():
        return "Unknown"

    # Unicode ranges for different scripts
    scripts = {
        "Devanagari": (0x0900, 0x097F),  # Sanskrit, Hindi, Marathi
        "Tamil": (0x0B80, 0x0BFF),
        "Telugu": (0x0C00, 0x0C7F),
        "Kannada": (0x0C80, 0x0CFF),
        "Malayalam": (0x0D00, 0x0D7F),
        "Bengali": (0x0980, 0x09FF),
        "Gujarati": (0x0A80, 0x0AFF),
        "Oriya": (0x0B00, 0x0B7F),
        "Gurmukhi": (0x0A00, 0x0A7F),  # Punjabi
        "Latin": (0x0041, 0x007A),  # English, etc.
        "Arabic": (0x0600, 0x06FF),
        "Chinese": (0x4E00, 0x9FFF),
        "Japanese_Hiragana": (0x3040, 0x309F),
        "Japanese_Katakana": (0x30A0, 0x30FF),
        "Korean": (0xAC00, 0xD7AF),
        "Thai": (0x0E00, 0x0E7F),
        "Myanmar": (0x1000, 0x109F),
    }

    # Count characters in each script
    script_counts = {script: 0 for script in scripts}

    for char in text:
        char_code = ord(char)
        for script, (start, end) in scripts.items():
            if start <= char_code <= end:
                script_counts[script] += 1
                break

    # Find dominant script (excluding spaces and punctuation)
    dominant_script = max(script_counts, key=script_counts.get)
    if script_counts[dominant_script] == 0:
        return "Unknown"

    return dominant_script


def is_indic_script(text):
    """Check if text contains Indic script characters"""
    indic_scripts = [
        "Devanagari", "Tamil", "Telugu", "Kannada", "Malayalam",
        "Bengali", "Gujarati", "Oriya", "Gurmukhi"
    ]
    script = detect_script(text)
    return script in indic_scripts


def get_script_language_hint(script):
    """
    Get likely language codes for a given script.
    Returns a list of Tesseract language codes.
    """
    script_to_langs = {
        "Devanagari": ["san", "hin", "mar"],
        "Tamil": ["tam"],
        "Telugu": ["tel"],
        "Kannada": ["kan"],
        "Malayalam": ["mal"],
        "Bengali": ["ben"],
        "Gujarati": ["guj"],
        "Oriya": ["ori"],
        "Gurmukhi": ["pan"],
        "Latin": ["eng"],
        "Arabic": ["ara"],
    }
    return script_to_langs.get(script, ["eng"])


def normalize_text(text):
    """
    Normalize text for better matching and comparison.
    - Remove extra whitespace
    - Normalize Unicode
    """
    import unicodedata

    # Normalize Unicode (NFC form)
    text = unicodedata.normalize('NFC', text)

    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def contains_mixed_scripts(text):
    """
    Check if text contains multiple scripts (e.g., Sanskrit + English).
    """
    scripts = {
        "Devanagari": (0x0900, 0x097F),
        "Tamil": (0x0B80, 0x0BFF),
        "Telugu": (0x0C00, 0x0C7F),
        "Kannada": (0x0C80, 0x0CFF),
        "Latin": (0x0041, 0x007A),
    }

    found_scripts = set()

    for char in text:
        char_code = ord(char)
        for script, (start, end) in scripts.items():
            if start <= char_code <= end:
                found_scripts.add(script)
                if len(found_scripts) > 1:
                    return True

    return False
