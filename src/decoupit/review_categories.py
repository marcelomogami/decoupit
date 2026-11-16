"""Stable human-review categories shared by exports and future adapters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReviewCategory:
    key: str
    label: str
    color: str


_CATEGORIES = {
    None: ReviewCategory("unclassified", "Sem classificação", "#8b9099"),
    "primary": ReviewCategory("primary", "Principal", "#68c98c"),
    "alternative": ReviewCategory("alternative", "Alternativa", "#68a9df"),
    "blooper": ReviewCategory("blooper", "Blooper", "#c493e8"),
    "discard": ReviewCategory("discard", "Descarte", "#e88491"),
}


def review_category(classification: str | None) -> ReviewCategory:
    """Return the stable category for a persisted manual classification."""

    return _CATEGORIES[classification]
