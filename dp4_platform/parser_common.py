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


def infer_conf_id(path: str, config: "DP4Config", fallback_index: int | None = None) -> int | None:
    path_obj = Path(path)
    candidates = [path_obj.stem, *(parent.name for parent in path_obj.parents if parent != path_obj.anchor)]
    for candidate in candidates:
        match = re.search(config.filename_pattern, candidate, re.IGNORECASE)
        if not match:
            continue
        try:
            return int(match.group(1))
        except ValueError:
            break
    return fallback_index


def atomic_number_to_symbol(atomic_number: int) -> str:
    return _ATOMIC_SYMBOLS.get(atomic_number, f"Z{atomic_number}")
