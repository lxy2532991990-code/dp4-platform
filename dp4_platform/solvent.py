"""Solvent name normalization for DP4+App reference shielding tables."""

from __future__ import annotations

import re


REFERENCE_SOLVENTS = (
    "CHCl3",
    "CH2Cl2",
    "CCl4",
    "H2O",
    "MeOH",
    "MeCN",
    "DMSO",
    "THF",
    "Pyridine",
    "Acetone",
    "Benzene",
)

_SOLVENT_ALIASES = {
    "chcl3": "CHCl3",
    "chloroform": "CHCl3",
    "cdcl3": "CHCl3",
    "ch2cl2": "CH2Cl2",
    "dichloromethane": "CH2Cl2",
    "methylenechloride": "CH2Cl2",
    "cd2cl2": "CH2Cl2",
    "ccl4": "CCl4",
    "carbontetrachloride": "CCl4",
    "h2o": "H2O",
    "water": "H2O",
    "meoh": "MeOH",
    "methanol": "MeOH",
    "cd3od": "MeOH",
    "mecn": "MeCN",
    "acetonitrile": "MeCN",
    "ch3cn": "MeCN",
    "cd3cn": "MeCN",
    "dmso": "DMSO",
    "dimethylsulfoxide": "DMSO",
    "dmso-d6": "DMSO",
    "dmso_d6": "DMSO",
    "thf": "THF",
    "tetrahydrofuran": "THF",
    "pyridine": "Pyridine",
    "acetone": "Acetone",
    "acetone-d6": "Acetone",
    "acetone_d6": "Acetone",
    "benzene": "Benzene",
    "c6h6": "Benzene",
    "c6d6": "Benzene",
}


def normalize_reference_solvent(value: str | None) -> str | None:
    """Return the DP4+App solvent key for a free-form solvent name."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    compact = re.sub(r"[\s_]+", "", raw).lower()
    compact = compact.replace(",", "").replace(";", "")
    if compact in {"auto", "automatic", "none", "default"}:
        return None
    if compact in _SOLVENT_ALIASES:
        return _SOLVENT_ALIASES[compact]
    dashed = re.sub(r"[\s_]+", "-", raw).lower()
    return _SOLVENT_ALIASES.get(dashed, raw)

