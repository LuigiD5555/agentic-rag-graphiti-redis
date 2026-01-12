"""Simple language detection for intent routing."""
import re
from typing import Optional

# Unicode script ranges for common non-Latin scripts
CJK_PATTERN = re.compile(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]')
CYRILLIC_PATTERN = re.compile(r'[\u0400-\u04ff]')
ARABIC_PATTERN = re.compile(r'[\u0600-\u06ff]')


class SimpleLanguageDetector:
    """Lightweight language/script detector for routing decisions."""

    @staticmethod
    def detect_script(text: str) -> str:
        """Detect script type (latin, cjk, cyrillic, arabic, other).

        Args:
            text: Input text to analyze.

        Returns:
            Script identifier: 'cjk', 'cyrillic', 'arabic', 'latin', 'other'
        """
        # Check for CJK (Chinese, Japanese, Korean)
        if CJK_PATTERN.search(text):
            return 'cjk'

        # Check for Cyrillic (Russian, etc.)
        if CYRILLIC_PATTERN.search(text):
            return 'cyrillic'

        # Check for Arabic
        if ARABIC_PATTERN.search(text):
            return 'arabic'

        # Default to Latin (English, Spanish, French, German, etc.)
        if any(c.isalpha() for c in text):
            return 'latin'

        return 'other'

    @staticmethod
    def detect_language_hint(text: str) -> Optional[str]:
        """Provide a rough language hint based on common words.

        This is NOT a full language detector, just a hint for pattern matching.

        Args:
            text: Input text.

        Returns:
            Language code hint: 'es', 'en', 'fr', 'de', 'ja', 'ko', 'ru', 'zh', or None
        """
        text_lower = text.lower()

        # Spanish indicators
        if any(word in text_lower for word in ['¿', '¡', 'qué', 'cómo', 'dónde', 'cuándo']):
            return 'es'

        # French indicators
        if any(word in text_lower for word in ['où', 'ça', 'être', 'être', 'quoi']):
            return 'fr'

        # German indicators
        if any(word in text_lower for word in ['das', 'der', 'die', 'ich', 'wie']):
            return 'de'

        # Script-based detection
        script = SimpleLanguageDetector.detect_script(text)
        if script == 'cyrillic':
            return 'ru'
        elif script == 'cjk':
            # Simplified heuristic: check for Hiragana (Japanese) vs others
            if re.search(r'[\u3040-\u309f]', text):
                return 'ja'
            elif re.search(r'[\uac00-\ud7af]', text):
                return 'ko'
            else:
                return 'zh'

        # Default to English for Latin script
        return 'en'


__all__ = ["SimpleLanguageDetector"]
