"""All-generation Skylander identification metadata."""

from __future__ import annotations

import json
from pathlib import Path


ELEMENT_COLORS = {
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


def identify(character_id: int, variant_id: int = 0) -> dict:
    exact = FIGURE_VARIANTS.get((character_id, variant_id))
    canonical = FIGURES.get(character_id)
    result = dict(exact or canonical or {
        "id": character_id,
        "name": f"Unknown figure #{character_id}",
        "element": "unknown",
    })
    result["variant_id"] = variant_id
    result["variant_known"] = exact is not None
    return result


# A SWAP Force character is exposed as two tags. IDs 2000..2015 contain the
# first name/top half and IDs 1000..1015 contain the second name/bottom half.
# Element follows the first-name/top half, not the movement-type metadata that
# some raw ID databases assign to individual halves.
_SWAP_ELEMENTS = (
    "air", "air", "earth", "earth", "fire", "fire", "life", "life",
    "magic", "magic", "tech", "tech", "undead", "undead", "water", "water",
)


def _swap_name(figure: dict) -> str:
    return figure["name"].replace(" (SWAP)", "")


def identify_present(identities: list[tuple[int, int]]) -> dict | None:
    """Identify the displayed figure, combining a pair of SWAP Force tags."""
    if not identities:
        return None

    figures = [identify(character_id, variant_id) for character_id, variant_id in identities]
    first = next((figure for figure in figures if 2000 <= figure["id"] <= 2015), None)
    second = next((figure for figure in figures if 1000 <= figure["id"] <= 1015), None)
    if not first or not second:
        return figures[0]

    first_base = _swap_name(FIGURES[first["id"]])
    second_base = _swap_name(FIGURES[second["id"]])
    first_name = _swap_name(first)
    second_name = _swap_name(second)
    if first_name != first_base:
        name = f"{first_name} {second_base}"
    elif second_name != second_base:
        name = f"{first_base} {second_name}"
    else:
        name = f"{first_base} {second_base}"

    return {
        "id": first["id"],
        "variant_id": first["variant_id"],
        "variant_known": first["variant_known"] and second["variant_known"],
        "name": name,
        "element": _SWAP_ELEMENTS[first["id"] - 2000],
        "swap_parts": [first, second],
    }
