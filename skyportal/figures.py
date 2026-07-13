"""All-generation Skylander identification metadata."""

from __future__ import annotations

import json
from pathlib import Path


ELEMENT_COLORS = {
    "default": "#182B39",
    "air": "#D9F7FF",
    "earth": "#C58A3A",
    "fire": "#FF3B18",
    "life": "#35D04F",
    "magic": "#8E44FF",
    "tech": "#FFB000",
    "undead": "#7B5AA6",
    "water": "#168CFF",
    "dark": "#402060",
    "light": "#FFF2A8",
    "unknown": "#708090",
}

ELEMENT_NAMES = {
    0: "unknown",
    1: "magic",
    2: "water",
    3: "earth",
    4: "fire",
    5: "air",
    6: "undead",
    7: "life",
    8: "tech",
    9: "dark",
    10: "light",
}

DATABASE_SOURCE = "https://github.com/ssnofall/skylandex"
DATABASE_REVISION = "f24e06b3d67c1e6130845e233fb2fcc3e6744a6f"


def _parse_id(value) -> int:
    return int(value, 0) if isinstance(value, str) else int(value)


def _load_database() -> list[dict]:
    path = Path(__file__).with_name("data") / "skylander_db.json"
    records = json.loads(path.read_text(encoding="utf-8"))
    return [
        {
            "id": _parse_id(record["char_id"]),
            "variant_id": _parse_id(record["variant_id"]),
            "name": record["name"],
            "element": ELEMENT_NAMES.get(int(record["element"]), "unknown"),
            "kind": "power_up" if 200 <= _parse_id(record["char_id"]) <= 311 else "figure",
        }
        for record in records
    ]


DATABASE_RECORDS = _load_database()
FIGURE_VARIANTS = {}
for record in DATABASE_RECORDS:
    key = (record["id"], record["variant_id"])
    if key in FIGURE_VARIANTS:
        # Some retail molds intentionally share the same on-tag IDs and cannot
        # be distinguished electronically. Preserve all possible names.
        existing = FIGURE_VARIANTS[key]
        existing.setdefault("aliases", [existing["name"]]).append(record["name"])
        existing["name"] = " / ".join(existing["aliases"])
    else:
        FIGURE_VARIANTS[key] = dict(record)

# The setup UI configures overrides by character rather than by retail variant.
# Keep one canonical entry per character ID for that dropdown.
FIGURES = {}
for record in FIGURE_VARIANTS.values():
    FIGURES.setdefault(record["id"], record)

POWER_UPS = {character_id: figure for character_id, figure in FIGURES.items() if figure["kind"] == "power_up"}
CHARACTERS = {character_id: figure for character_id, figure in FIGURES.items() if figure["kind"] == "figure"}


def identify(character_id: int, variant_id: int = 0) -> dict:
    exact = FIGURE_VARIANTS.get((character_id, variant_id))
    canonical = FIGURES.get(character_id)
    result = dict(exact or canonical or {
        "id": character_id,
        "name": f"Unknown figure #{character_id}",
        "element": "unknown",
        "kind": "figure",
    })
    result["variant_id"] = variant_id
    result["variant_known"] = exact is not None
    return result


# A SWAP Force character is exposed as two tags. IDs 2000..2015 contain the
# first name/top half and IDs 1000..1015 contain the second name/bottom half.
# Treat the halves as separate characters so a mixed SWAP activates the same
# two-element behavior as two conventional figures. The source database's
# element values for individual halves sometimes describe movement metadata,
# so resolve both halves through the element of their original character.
_SWAP_ELEMENTS = (
    "air", "air", "earth", "earth", "fire", "fire", "life", "life",
    "magic", "magic", "tech", "tech", "undead", "undead", "water", "water",
)


def _swap_name(figure: dict) -> str:
    return figure["name"].replace(" (SWAP)", "")


def _normalize_swap_half(figure: dict) -> dict:
    character_id = figure["id"]
    if 2000 <= character_id <= 2015:
        index = character_id - 2000
        half = "top"
    elif 1000 <= character_id <= 1015:
        index = character_id - 1000
        half = "bottom"
    else:
        return figure
    result = dict(figure)
    result.update({
        "name": _swap_name(figure),
        "element": _SWAP_ELEMENTS[index],
        "swap_half": half,
    })
    return result


def identify_present(identities: list[tuple[int, int]]) -> dict | None:
    """Identify the first displayed character."""
    figures = identify_all_present(identities)
    return figures[0] if figures else None


def identify_all_present(identities: list[tuple[int, int]]) -> list[dict]:
    """Identify every figure, treating each SWAP Force half as a character."""
    if not identities:
        return []
    return [
        _normalize_swap_half(identify(character_id, variant_id))
        for character_id, variant_id in identities
    ]
