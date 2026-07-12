"""Pure helpers for the Streamlit UI — kept import-safe (no Streamlit calls)
so they can be unit-tested without a running app."""

from __future__ import annotations

import difflib

SIMILARITY_CUTOFF = 0.6


def normalize_column_name(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def suggest_mapping(source_cols: list[str], target_cols: list[str]) -> dict[str, str]:
    """Auto-suggest source -> target column pairs by name similarity.

    Exact matches after normalization win first (``order_id`` == ``OrderID``);
    remaining columns fall back to fuzzy matching. Each target column is
    used at most once.
    """
    suggestions: dict[str, str] = {}
    normalized_targets = {normalize_column_name(t): t for t in target_cols}
    available = set(target_cols)

    for src in source_cols:
        candidate = normalized_targets.get(normalize_column_name(src))
        if candidate and candidate in available:
            suggestions[src] = candidate
            available.discard(candidate)

    for src in source_cols:
        if src in suggestions or not available:
            continue
        matches = difflib.get_close_matches(
            normalize_column_name(src),
            [normalize_column_name(t) for t in available],
            n=1,
            cutoff=SIMILARITY_CUTOFF,
        )
        if matches:
            candidate = next(t for t in available if normalize_column_name(t) == matches[0])
            suggestions[src] = candidate
            available.discard(candidate)

    return suggestions
