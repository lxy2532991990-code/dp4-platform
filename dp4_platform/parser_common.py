"""Shared helpers for program-specific quantum chemistry parsers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import DP4Config


_ATOMIC_SYMBOLS: dict[int, str] = {
    1: "H",
    2: "He",
    3: "Li",
    4: "Be",
    5: "B",
    6: "C",
    7: "N",
    8: "O",
    9: "F",
    10: "Ne",
    11: "Na",
    12: "Mg",
    13: "Al",
    14: "Si",
    15: "P",
    16: "S",
    17: "Cl",
    18: "Ar",
    19: "K",
    20: "Ca",
    35: "Br",
    53: "I",
}

_STEM_SUFFIX_CONF_PATTERN = re.compile(r"(?:^|[_\-.])(\d+)$")


def read_text(path: str) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gbk", "latin-1", "utf-16"):
        try:
            with open(path, "r", encoding=encoding, errors="ignore") as fh:
                return fh.read()
        except OSError:
            raise
        except Exception:
            continue
    raise ValueError(f"Unable to read file: {path}")


def _match_conf_id(candidate: str, pattern: str) -> int | None:
    match = re.search(pattern, candidate, re.IGNORECASE)
    if not match:
        return None
    for group in match.groups():
        if group is None:
            continue
        try:
            return int(group)
        except ValueError:
            return None
    return None


def infer_conf_id(path: str, config: "DP4Config", fallback_index: int | None = None) -> int | None:
    path_obj = Path(path)
    stem_match = _match_conf_id(path_obj.stem, config.filename_pattern)
    if stem_match is not None:
        return stem_match

    suffix_match = _STEM_SUFFIX_CONF_PATTERN.search(path_obj.stem)
    if suffix_match:
        return int(suffix_match.group(1))

    for parent in path_obj.parents:
        if parent == path_obj.anchor:
            continue
        parent_match = _match_conf_id(parent.name, config.filename_pattern)
        if parent_match is not None:
            return parent_match
    return fallback_index


def atomic_number_to_symbol(atomic_number: int) -> str:
    return _ATOMIC_SYMBOLS.get(atomic_number, f"Z{atomic_number}")
