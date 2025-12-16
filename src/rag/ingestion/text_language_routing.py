import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional


class ScriptFamily(str, Enum):
    """High-level script families used to route splitting policy."""
    LATIN = "latin"
    CJK = "cjk"
    CYRILLIC = "cyrillic"
    ARABIC = "arabic"
    HANGUL = "hangul"
    OTHER = "other"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TextProfile:
    """Summary of text characteristics used for routing decisions."""
    dominant_script: ScriptFamily
    script_shares: Dict[ScriptFamily, float]
    has_cjk: bool


@dataclass(frozen=True)
class SplitPolicy:
    """Split parameters chosen based on the detected script."""
    chunk_size: int
    chunk_overlap: int
    cjk_mode: bool


class TextProfiler:
    """Detect dominant script and choose a split policy.

    This module is purely heuristic and fully offline.
    """

    def profile(self, text: str, sample_limit: int = 50000) -> TextProfile:
        """Profile text and determine dominant script.

        Args:
            text: Extracted text.
            sample_limit: Maximum number of characters used for profiling.

        Returns:
            A TextProfile describing script distribution.
        """
        normalized_text = self.normalize(text)
        sample = normalized_text[:sample_limit]

        if not sample.strip():
            return TextProfile(
                dominant_script=ScriptFamily.UNKNOWN,
                script_shares={},
                has_cjk=False,
            )

        counts: Dict[ScriptFamily, int] = {}
        non_whitespace_characters = 0

        for character in sample:
            if character.isspace():
                continue

            non_whitespace_characters += 1
            script_family = self._classify_char(character)
            counts[script_family] = counts.get(script_family, 0) + 1

        shares = self._to_shares(counts, non_whitespace_characters)
        dominant = self._dominant(shares)
        cjk_share = shares.get(ScriptFamily.CJK, 0.0) + shares.get(ScriptFamily.HANGUL, 0.0)

        return TextProfile(
            dominant_script=dominant,
            script_shares=shares,
            has_cjk=cjk_share >= 0.05,
        )

    def pick_split_policy(self, profile: TextProfile) -> SplitPolicy:
        """Choose split policy based on script.

        Args:
            profile: Output of `profile()`.

        Returns:
            SplitPolicy tuned for the script family.
        """
        if profile.has_cjk or profile.dominant_script in {ScriptFamily.CJK, ScriptFamily.HANGUL}:
            return SplitPolicy(chunk_size=700, chunk_overlap=120, cjk_mode=True)

        return SplitPolicy(chunk_size=1200, chunk_overlap=150, cjk_mode=False)

    def normalize(self, text: str) -> str:
        """Normalize unicode for consistent processing."""
        normalized = unicodedata.normalize("NFC", text)
        return normalized.replace("\r\n", "\n").replace("\r", "\n")

    def _classify_char(self, character: str) -> ScriptFamily:
        code = ord(character)

        # CJK Unified Ideographs + extensions (rough)
        if (0x4E00 <= code <= 0x9FFF) or (0x3400 <= code <= 0x4DBF) or (0x20000 <= code <= 0x2A6DF):
            return ScriptFamily.CJK
        # Hiragana / Katakana
        if (0x3040 <= code <= 0x309F) or (0x30A0 <= code <= 0x30FF):
            return ScriptFamily.CJK
        # Hangul
        if 0xAC00 <= code <= 0xD7AF:
            return ScriptFamily.HANGUL
        # Cyrillic
        if 0x0400 <= code <= 0x04FF or 0x0500 <= code <= 0x052F:
            return ScriptFamily.CYRILLIC
        # Arabic
        if 0x0600 <= code <= 0x06FF or 0x0750 <= code <= 0x077F:
            return ScriptFamily.ARABIC
        # Latin (basic + extended)
        if (0x0041 <= code <= 0x024F) or (0x1E00 <= code <= 0x1EFF):
            return ScriptFamily.LATIN

        return ScriptFamily.OTHER

    def _to_shares(self, counts: Dict[ScriptFamily, int], total: int) -> Dict[ScriptFamily, float]:
        if total <= 0:
            return {}
        return {script: (count / total) for script, count in counts.items()}

    def _dominant(self, shares: Dict[ScriptFamily, float]) -> ScriptFamily:
        if not shares:
            return ScriptFamily.UNKNOWN
        return max(shares.items(), key=lambda item: item[1])[0]


class CjkTextSplitter:
    """CJK-first splitter that prefers sentence punctuation.

    This splitter does not depend on tokenizers and works offline.
    """

    _sentence_re = re.compile(r"(?<=[。！？!?])\s*", re.UNICODE)

    def split(self, text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
        """Split text into CJK-friendly chunks.

        Args:
            text: Input text.
            chunk_size: Target chunk size (characters).
            chunk_overlap: Overlap between chunks (characters).

        Returns:
            List of chunk strings.
        """
        clean = text.strip()
        if not clean:
            return []

        sentences = [s for s in self._sentence_re.split(clean) if s.strip()]
        if not sentences:
            return []

        chunks: List[str] = []
        buffer: List[str] = []
        buffer_length = 0

        def flush() -> None:
            nonlocal buffer, buffer_length
            if not buffer:
                return
            chunk = "".join(buffer).strip()
            if chunk:
                chunks.append(chunk)
            buffer = []
            buffer_length = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            if buffer_length + len(sentence) <= chunk_size:
                buffer.append(sentence)
                buffer_length += len(sentence)
                continue

            flush()

            if len(sentence) > chunk_size:
                start = 0
                while start < len(sentence):
                    end = min(start + chunk_size, len(sentence))
                    chunks.append(sentence[start:end].strip())
                    start = max(end - chunk_overlap, end)
                continue

            buffer.append(sentence)
            buffer_length = len(sentence)

        flush()

        if chunk_overlap <= 0 or len(chunks) <= 1:
            return chunks

        overlapped: List[str] = []
        for i, chunk in enumerate(chunks):
            if i == 0:
                overlapped.append(chunk)
                continue
            previous = overlapped[-1]
            overlap_text = previous[-chunk_overlap:] if len(previous) > chunk_overlap else previous
            overlapped.append((overlap_text + chunk).strip())

        return overlapped
