"""Mixed-script reading length.

WordPress ``wordcount`` and Microsoft Word count each CJK ideograph, kana, or
Hangul syllable as one word, and each whitespace-delimited run of other letters
or digits as one word. Punctuation and spaces add nothing. Thai, Lao, and Khmer
have no spaces, so each code point in those blocks counts as one (same idea as
``@xsynaptic/word-count``), which keeps an unspaced sentence from becoming a
single huge segment.

Offsets into ``str`` stay Unicode code points. This module only answers "how
many 字" and "where does the Nth 字 end".
"""

from __future__ import annotations

import bisect
import unicodedata
from typing import Protocol

from lumina_core.chunker.coop import GilYielder

# Ideographs, kana, and Hangul syllables: one code point, one unit.
_PER_CHAR: tuple[tuple[int, int], ...] = (
    (0x1100, 0x11FF),  # Hangul jamo
    (0x2E80, 0x2EFF),  # CJK radicals
    (0x2F00, 0x2FDF),  # Kangxi radicals
    (0x3005, 0x3005),  # ideographic iteration mark
    (0x3007, 0x3007),  # ideographic number zero
    (0x303B, 0x303B),
    (0x3040, 0x30FF),  # hiragana + katakana
    (0x3130, 0x318F),  # Hangul compatibility jamo
    (0x31F0, 0x31FF),  # katakana phonetic extensions
    (0x3400, 0x4DBF),  # CJK extension A
    (0x4E00, 0x9FFF),  # CJK unified
    (0xAC00, 0xD7AF),  # Hangul syllables
    (0xF900, 0xFAFF),  # CJK compatibility ideographs
    (0xFF66, 0xFF9D),  # halfwidth katakana
    (0x20000, 0x2A6DF),
    (0x2A700, 0x2B73F),
    (0x2B740, 0x2B81F),
    (0x2B820, 0x2CEAF),
    (0x2CEB0, 0x2EBEF),
    (0x30000, 0x3134F),
    (0x31350, 0x323AF),
)
# Scriptio continua: count per code point so a sentence is not one unit.
_CONTINUA: tuple[tuple[int, int], ...] = (
    (0x0E00, 0x0E7F),  # Thai
    (0x0E80, 0x0EFF),  # Lao
    (0x1780, 0x17FF),  # Khmer
    (0x19E0, 0x19FF),  # Khmer symbols
)
_PER_CHAR = tuple(sorted((*_PER_CHAR, *_CONTINUA)))
_APOSTROPHE = frozenset({0x27, 0x2019})
_YIELD_EVERY = 32_000


class _AtomLike(Protocol):
    start: int
    end: int
    text: str
    units: int


def _per_char(cp: int) -> bool:
    spans = _PER_CHAR
    lo = 0
    hi = len(spans)
    while lo < hi:
        mid = (lo + hi) // 2
        start, end = spans[mid]
        if cp < start:
            hi = mid
        elif cp > end:
            lo = mid + 1
        else:
            return True
    return False


def _word_char(cp: int) -> bool:
    cat = unicodedata.category(chr(cp))
    return cat[0] in "LN"


def _extends_word(cp: int) -> bool:
    return unicodedata.category(chr(cp))[0] == "M"


def count_units(
    text: str,
    *,
    yielder: GilYielder | None = None,
) -> int:
    """Return the mixed-script word count of ``text``."""
    count, _ = _scan(text, 0, len(text), stop_at=None, yielder=yielder)
    return count


def unit_count_exceeds(
    text: str,
    start: int,
    end: int,
    limit: int,
    *,
    yielder: GilYielder | None = None,
) -> bool:
    """True when ``text[start:end]`` has more than ``limit`` units.

    Each unit consumes at least one code point, so a short slice cannot exceed
    ``limit`` and is not scanned.
    """
    if end - start <= limit:
        return False
    count, _ = _scan(text, start, end, stop_at=limit + 1, yielder=yielder)
    return count > limit


def advance_units(
    text: str,
    start: int,
    units: int,
    end: int | None = None,
    *,
    yielder: GilYielder | None = None,
) -> int:
    """Code-point index where ``units`` have been consumed, not mid-word.

    The index is capped at ``end``. A word that crosses the count is included
    whole, so the cut stays on a unit boundary.
    """
    limit = len(text) if end is None else end
    if units <= 0 or start >= limit:
        return start
    if limit - start <= units:
        return limit
    _, index = _scan(text, start, limit, stop_at=units, yielder=yielder)
    return index


def _consume_word(text: str, index: int, end: int) -> int:
    """Move ``index`` from the first letter of a word to just after that word."""
    index += 1
    while index < end:
        cp = ord(text[index])
        if _word_char(cp) or _extends_word(cp):
            index += 1
            continue
        if cp in _APOSTROPHE and index + 1 < end and _word_char(ord(text[index + 1])):
            index += 1
            continue
        break
    return index


def _scan(
    text: str,
    start: int,
    end: int,
    *,
    stop_at: int | None,
    yielder: GilYielder | None,
) -> tuple[int, int]:
    count = 0
    in_word = False
    index = start
    since_yield = 0
    while index < end:
        cp = ord(text[index])
        if _per_char(cp):
            count += 1
            in_word = False
            index += 1
            if stop_at is not None and count >= stop_at:
                return count, index
        elif _word_char(cp):
            if not in_word:
                count += 1
                in_word = True
                if stop_at is not None and count >= stop_at:
                    return count, _consume_word(text, index, end)
            index += 1
        elif in_word and cp in _APOSTROPHE and index + 1 < end and _word_char(ord(text[index + 1])):
            index += 1
        elif in_word and _extends_word(cp):
            index += 1
        else:
            in_word = False
            index += 1
        since_yield += 1
        if yielder is not None and since_yield >= _YIELD_EVERY:
            yielder.bump(since_yield)
            since_yield = 0
    if yielder is not None and since_yield:
        yielder.bump(since_yield)
    return count, end


class UnitScale:
    """O(1) unit length for spans that sit on atom boundaries."""

    def __init__(self, atoms: list[_AtomLike], text: str = "") -> None:
        self.text = text
        self.atoms = atoms
        self.starts = [atom.start for atom in atoms]
        prefix = [0]
        for atom in atoms:
            stored = atom.units
            prefix.append(prefix[-1] + (stored if stored >= 0 else count_units(atom.text)))
        self.prefix = prefix

    def units(self, start: int, end: int) -> int:
        if end <= start or not self.atoms:
            if end <= start:
                return 0
            return count_units(self.text[start:end]) if self.text else 0
        i = bisect.bisect_right(self.starts, start) - 1
        j = bisect.bisect_right(self.starts, end - 1) - 1
        if i < 0 or j < 0:
            return count_units(self.text[start:end]) if self.text else 0
        if i == j:
            atom = self.atoms[i]
            if atom.start == start and atom.end == end:
                return self.prefix[i + 1] - self.prefix[i]
            return self._slice_units(atom, start, end)
        left = self.atoms[i]
        right = self.atoms[j]
        if left.start == start and right.end == end:
            return self.prefix[j + 1] - self.prefix[i]
        left_units = (
            self.prefix[i + 1] - self.prefix[i]
            if left.start == start
            else self._slice_units(left, start, left.end)
        )
        right_units = (
            self.prefix[j + 1] - self.prefix[j]
            if right.end == end
            else self._slice_units(right, right.start, end)
        )
        middle = self.prefix[j] - self.prefix[i + 1]
        return left_units + middle + right_units

    def advance(self, start: int, units: int, end: int) -> int:
        if self.text:
            return advance_units(self.text, start, units, end)
        piece = _concat(self.atoms, start, end)
        return start + advance_units(piece, 0, units, len(piece))

    def before_tail(self, start: int, end: int, tail_units: int) -> int:
        """Index that leaves ``tail_units`` on the right of ``[start, end]``."""
        if tail_units <= 0:
            return end
        total = self.units(start, end)
        if total <= tail_units:
            return start
        return self.advance(start, total - tail_units, end)

    def _slice_units(self, atom: _AtomLike, start: int, end: int) -> int:
        if self.text:
            return count_units(self.text[start:end])
        return count_units(atom.text[start - atom.start : end - atom.start])


def _concat(atoms: list[_AtomLike], start: int, end: int) -> str:
    parts: list[str] = []
    for atom in atoms:
        if atom.end <= start or atom.start >= end:
            continue
        lo = max(atom.start, start)
        hi = min(atom.end, end)
        parts.append(atom.text[lo - atom.start : hi - atom.start])
    return "".join(parts)
