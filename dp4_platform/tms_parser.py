"""Parse TMS (tetramethylsilane) shielding from ORCA or Gaussian output files."""

from __future__ import annotations

from .parser_common import read_text


def _detect_program(content: str) -> str:
    """Return 'orca', 'gaussian', or 'unknown'."""
    if "CHEMICAL SHIELDING SUMMARY" in content or "FINAL SINGLE POINT ENERGY" in content:
        return "orca"
    if "Entering Gaussian System" in content or "SCF Done" in content or "Isotropic =" in content:
        return "gaussian"
    return "unknown"


def parse_tms_file(path: str) -> dict[str, float]:
    """Extract 1H and 13C TMS shielding from an ORCA or Gaussian NMR output.

    Returns ``{"1H": avg_shielding, "13C": avg_shielding}``.
    TMS has 4 equivalent methyl carbons and 12 equivalent protons; we average
    all detected atoms of each element.
    """
    content = read_text(path)
    program = _detect_program(content)

    if program == "orca":
        return _parse_tms_orca(content)
    if program == "gaussian":
        return _parse_tms_gaussian(content)

    raise ValueError(f"Could not detect ORCA or Gaussian NMR output in: {path}")


# ---------------------------------------------------------------------------
# ORCA
# ---------------------------------------------------------------------------

import re as _re  # noqa: E402

_ORCA_SHIELDING_RE = _re.compile(
    r"^\s*(\d+)\s+([A-Z][a-z]?)\s+isotropic shielding\s*[:=]\s*([-\d.]+)",
    _re.IGNORECASE | _re.MULTILINE,
)
_ORCA_TABLE_ROW_RE = _re.compile(
    r"^\s*(\d+)\s+([A-Z][a-z]?)\s+([-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?)"
    r"(?:\s+[-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?)?\s*$"
)


def _parse_tms_orca(content: str) -> dict[str, float]:
    values: dict[str, list[float]] = {"1H": [], "13C": []}

    # Try per-atom lines first
    for m in _ORCA_SHIELDING_RE.finditer(content):
        element = m.group(2)
        shielding = float(m.group(3))
        if element == "H":
            values["1H"].append(shielding)
        elif element == "C":
            values["13C"].append(shielding)

    # Fallback: summary table
    if not values["1H"] and not values["13C"]:
        summary_start = content.find("CHEMICAL SHIELDING SUMMARY")
        if summary_start >= 0:
            tail = content[summary_start:]
            started = False
            for line in tail.splitlines():
                s = line.strip()
                if not s:
                    if started:
                        break
                    continue
                if set(s) == {"-"}:
                    continue
                if s.lower().startswith("nucleus") or s.lower().startswith("-------"):
                    continue
                m = _ORCA_TABLE_ROW_RE.match(line)
                if not m:
                    if started:
                        break
                    continue
                started = True
                element = m.group(2)
                shielding = float(m.group(3))
                if element == "H":
                    values["1H"].append(shielding)
                elif element == "C":
                    values["13C"].append(shielding)

    if not values["1H"] and not values["13C"]:
        raise ValueError("No 1H or 13C shielding values found in TMS ORCA output")

    return _average(values)


# ---------------------------------------------------------------------------
# Gaussian
# ---------------------------------------------------------------------------

_GAUSS_ISOTROPIC_RE = _re.compile(
    r"^\s*(\d+)\s+([A-Z][a-z]?)\s+Isotropic\s*=\s*([-\d.]+)",
    _re.IGNORECASE | _re.MULTILINE,
)


def _parse_tms_gaussian(content: str) -> dict[str, float]:
    values: dict[str, list[float]] = {"1H": [], "13C": []}

    for m in _GAUSS_ISOTROPIC_RE.finditer(content):
        element = m.group(2)
        shielding = float(m.group(3))
        if element == "H":
            values["1H"].append(shielding)
        elif element == "C":
            values["13C"].append(shielding)

    if not values["1H"] and not values["13C"]:
        raise ValueError("No 1H or 13C shielding values found in TMS Gaussian output")

    return _average(values)


# ---------------------------------------------------------------------------
# shared
# ---------------------------------------------------------------------------

def _average(values: dict[str, list[float]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for nucleus, vals in values.items():
        if vals:
            result[nucleus] = sum(vals) / len(vals)
    return result
