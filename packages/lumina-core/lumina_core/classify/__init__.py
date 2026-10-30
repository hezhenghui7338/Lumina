"""Book classification."""

from lumina_core.classify.book import BOOK_CATEGORIES, classify_book, normalize_category
from lumina_core.classify.segment_profile import (
    SegmentProfile,
    build_segment_profile,
    build_segment_profile_local,
    suggested_chunk_target,
)

__all__ = [
    "BOOK_CATEGORIES",
    "SegmentProfile",
    "build_segment_profile",
    "build_segment_profile_local",
    "classify_book",
    "normalize_category",
    "suggested_chunk_target",
]
