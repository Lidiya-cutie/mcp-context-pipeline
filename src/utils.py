"""
Utility functions for MCP Context Pipeline.
Provides PII masking, token counting, and helper functions.
"""

import os
import tiktoken
from typing import Optional

# Lazy initialization for memory efficiency
_tokenizer = None
_analyzer = None
_anonymizer = None


def get_tokenizer() -> tiktoken.Encoding:
    """Get or initialize the GPT-4o tokenizer."""
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = tiktoken.encoding_for_model("gpt-4o")
    return _tokenizer


def count_tokens(text: str) -> int:
    """
    Count tokens in text for checking triggers (AC1).

    Args:
        text: Input text to count tokens for

    Returns:
        Number of tokens in the text
    """
    try:
        return len(get_tokenizer().encode(text))
    except Exception as e:
        print(f"[WARN] Token count failed: {e}. Falling back to char/4 estimate.")
        # Fallback estimate: approximately 4 chars per token
        return len(text) // 4


def pii_mask(text: str, language: str = 'en') -> str:
    """
    Mask PII (Personally Identifiable Information) from text (Phase 3 Security).

    Args:
        text: Input text to anonymize
        language: Language code for PII detection

    Returns:
        Anonymized text with PII replaced
    """
    global _analyzer, _anonymizer

    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine

        if _analyzer is None:
            _analyzer = AnalyzerEngine()
        if _anonymizer is None:
            _anonymizer = AnonymizerEngine()

        # Analyze for PII
        results = _analyzer.analyze(text=text, language=language)

        # Anonymize
        anonymized = _anonymizer.anonymize(text=text, analyzer_results=results)

        return anonymized.text

    except ImportError:
        print("[WARN] Presidio not installed. Skipping PII masking.")
        return text
    except Exception as e:
        print(f"[WARN] PII masking failed: {e}. Returning original text.")
        return text


def truncate_text(text: str, max_chars: int = 1000, suffix: str = "...") -> str:
    """
    Truncate text to maximum characters with suffix.

    Args:
        text: Input text
        max_chars: Maximum length
        suffix: Suffix to add when truncated

    Returns:
        Truncated text
    """
    if len(text) <= max_chars:
        return text
    return text[:max_chars - len(suffix)] + suffix


def generate_session_id(prefix: str = "session") -> str:
    """
    Generate a unique session ID.

    Args:
        prefix: Prefix for the session ID

    Returns:
        Unique session identifier
    """
    import time
    import random
    import string

    timestamp = int(time.time())
    random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"{prefix}_{timestamp}_{random_str}"
