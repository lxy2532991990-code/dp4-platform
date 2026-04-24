"""Gaussian output parser.

The public functions mirror the ORCA parser:
    parse_opt_file(filepath, record, config)
    parse_ecd_file(filepath, record, config)
    parse_single_file(filepath, record, config)
"""

from __future__ import annotations

import math
import re
from typing import Dict, List, Optional

import numpy as np

from .config import CDGauge, ECDConfig, ImagFreqPolicy
from .conformer import ConformerRecord, ConformerStatus


_FLOAT = r"[-+]?(?:(?:\d+\.\d*)|(?:\d+)|(?:\.\d+))(?:[EeDd][-+]?\d+)?"

_RE_SCF_DONE = re.compile(
    rf"SCF\s+Done:\s+E\([^)]+\)\s*=\s*({_FLOAT})",
    re.IGNORECASE,
)
_RE_GIBBS_TOTAL = re.compile(
    rf"Sum\s+of\s+electronic\s+and\s+thermal\s+Free\s+Energies\s*=\s*({_FLOAT})",
    re.IGNORECASE,
)
_RE_GIBBS_CORR = re.compile(
    rf"Thermal\s+correction\s+to\s+Gibbs\s+Free\s+Energy\s*=\s*({_FLOAT})",
    re.IGNORECASE,
)
_RE_FREQ_LINE = re.compile(r"^\s*Frequencies\s*--\s*(.+)$", re.MULTILINE)
_RE_EXCITED_STATE = re.compile(
    rf"Excited\s+State\s+(\d+):\s+\S+\s+({_FLOAT})\s*eV",
    re.IGNORECASE,
)


def _read_file(filepath: str) -> Optional[str]:
    for enc in ("utf-8", "gbk", "latin-1", "utf-16"):
        try:
            with open(filepath, "r", encoding=enc, errors="ignore") as f:
                return f.read()
        except Exception:
            continue
    return None


def _to_float(text: str) -> Optional[float]:
    try:
        value = float(text.replace("D", "E").replace("d", "e"))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _mark_status_if_clear(record: ConformerRecord, status: ConformerStatus) -> None:
    if record.status in (ConformerStatus.OK, ConformerStatus.SOFT_IMAGINARY_FREQ):
        record.status = status


def _restore_ok_if_recovered(record: ConformerRecord) -> None:
    if record.status == ConformerStatus.NO_ENERGY and record.scf_energy is not None:
        record.status = ConformerStatus.OK


def extract_energies(content: str, record: ConformerRecord) -> None:
    """Extract the last Gaussian SCF energy plus optional Gibbs data."""
    scf_matches = _RE_SCF_DONE.findall(content)
    for token in reversed(scf_matches):
        value = _to_float(token)
        if value is not None:
            record.scf_energy = value
            break

    m = _RE_GIBBS_TOTAL.search(content)
    if m:
        value = _to_float(m.group(1))
        if value is not None:
            record.gibbs_energy = value

    m = _RE_GIBBS_CORR.search(content)
    if m:
        value = _to_float(m.group(1))
        if value is not None:
            record.gibbs_correction = value

    if record.scf_energy is None:
        _mark_status_if_clear(record, ConformerStatus.NO_ENERGY)
        record.add_error("Failed to extract SCF energy from Gaussian output")
    else:
        _restore_ok_if_recovered(record)


def extract_frequencies(
    content: str,
    record: ConformerRecord,
    config: ECDConfig,
) -> None:
    """Extract Gaussian frequency lines. TD-only outputs only receive a warning."""
    freqs: List[float] = []
    for m in _RE_FREQ_LINE.finditer(content):
        for token in re.findall(_FLOAT, m.group(1)):
            value = _to_float(token)
            if value is not None:
                freqs.append(value)

    if not freqs:
        record.add_warning(
            "No vibrational frequencies found (likely TD/ECD-only Gaussian output)"
        )
        return

    record.frequencies = np.asarray(freqs, dtype=float)
    record.min_frequency = float(np.min(record.frequencies))

    if config.imag_freq_policy == ImagFreqPolicy.STRICT:
        imag = [f for f in freqs if f < 0]
    elif config.imag_freq_policy == ImagFreqPolicy.TOLERANT:
        imag = [f for f in freqs if f < config.imag_freq_threshold]
    else:
        imag = [f for f in freqs if f < 0]

    record.n_imaginary = len(imag)

    if imag:
        if config.imag_freq_policy == ImagFreqPolicy.STRICT:
            record.status = ConformerStatus.IMAGINARY_FREQ
            record.add_error(
                f"Imaginary frequency detected (strict): "
                f"min = {min(imag):.1f} cm^-1 ({len(imag)} total)"
            )
        elif config.imag_freq_policy == ImagFreqPolicy.TOLERANT:
            record.status = ConformerStatus.IMAGINARY_FREQ
            record.add_error(
                f"Imaginary frequency below threshold "
                f"({config.imag_freq_threshold} cm^-1): "
                f"min = {min(imag):.1f} cm^-1"
            )
        else:
            record.status = ConformerStatus.SOFT_IMAGINARY_FREQ
            record.add_warning(
                f"Imaginary frequency detected (manual review): "
                f"min = {min(freqs):.1f} cm^-1"
            )

    soft_imag = [f for f in freqs if f < 0 and f >= config.imag_freq_threshold]
    if soft_imag and record.status == ConformerStatus.OK:
        record.status = ConformerStatus.SOFT_IMAGINARY_FREQ
        record.add_warning(
            f"Soft imaginary frequencies (above threshold): "
            f"{[f'{v:.1f}' for v in soft_imag]} cm^-1"
        )


def _find_rotatory_header(content: str, marker: str) -> int:
    pattern = re.compile(
        r"^[^\n]*\bstate\b[^\n]*" + re.escape(marker) + r"[^\n]*$",
        re.IGNORECASE | re.MULTILINE,
    )
    m = pattern.search(content)
    return m.end() if m else -1


def _parse_rotatory_table(content: str, header_end: int) -> Dict[int, float]:
    state_to_r: Dict[int, float] = {}
    window = content[header_end:header_end + 200_000]

    for line in window.splitlines():
        stripped = line.strip()
        if not stripped:
            if state_to_r:
                break
            continue

        parts = stripped.split()
        try:
            state_id = int(parts[0])
        except (IndexError, ValueError):
            if state_to_r:
                break
            continue

        values = []
        for token in parts[1:]:
            value = _to_float(token)
            if value is None:
                values = []
                break
            values.append(value)

        if len(values) < 4:
            if state_to_r:
                break
            continue

        r_value = values[3]
        if math.isfinite(r_value):
            state_to_r[state_id] = r_value

    return state_to_r


def extract_cd_data(
    content: str,
    record: ConformerRecord,
    gauge: CDGauge = CDGauge.LENGTH,
) -> bool:
    """Extract Gaussian TD excitation energies and rotatory strengths."""
    state_energies: Dict[int, float] = {}
    for m in _RE_EXCITED_STATE.finditer(content):
        state_id = int(m.group(1))
        energy = _to_float(m.group(2))
        if energy is not None and energy > 0:
            state_energies[state_id] = energy

    if not state_energies:
        record.add_error("No 'Excited State' block found in Gaussian output")
        _mark_status_if_clear(record, ConformerStatus.NO_CD_DATA)
        return False

    primary = "R(length)" if gauge == CDGauge.LENGTH else "R(velocity)"
    fallback = "R(velocity)" if gauge == CDGauge.LENGTH else "R(length)"
    header_end = _find_rotatory_header(content, primary)
    gauge_used = gauge

    if header_end < 0:
        header_end = _find_rotatory_header(content, fallback)
        if header_end >= 0:
            gauge_used = CDGauge.VELOCITY if gauge == CDGauge.LENGTH else CDGauge.LENGTH
            record.add_warning(
                f"Requested '{gauge.value}' gauge not found; "
                f"falling back to '{gauge_used.value}' gauge"
            )

    if header_end < 0:
        record.add_error("No 'Rotatory Strengths' table found in Gaussian output")
        _mark_status_if_clear(record, ConformerStatus.NO_CD_DATA)
        return False

    state_to_r = _parse_rotatory_table(content, header_end)
    if not state_to_r:
        record.add_error("Rotatory Strengths table found but no numeric rows parsed")
        _mark_status_if_clear(record, ConformerStatus.NO_CD_DATA)
        return False

    common = sorted(set(state_energies) & set(state_to_r))
    if not common:
        record.add_error(
            "No overlap between Excited States and Rotatory Strengths tables"
        )
        _mark_status_if_clear(record, ConformerStatus.NO_CD_DATA)
        return False

    record.transition_energies = np.asarray(
        [state_energies[state_id] for state_id in common],
        dtype=float,
    )
    record.rotatory_strengths = np.asarray(
        [state_to_r[state_id] for state_id in common],
        dtype=float,
    )
    record.n_transitions = len(common)

    n_states = len(state_energies)
    n_r = len(state_to_r)
    if len(common) < min(n_states, n_r):
        record.add_warning(
            f"State/R mismatch: {n_states} excited states vs {n_r} R entries; "
            f"used {len(common)} common"
        )

    if gauge_used != gauge:
        record.add_warning(f"CD data extracted with fallback gauge '{gauge_used.value}'")

    return True


def parse_opt_file(
    filepath: str,
    record: ConformerRecord,
    config: ECDConfig,
) -> None:
    content = _read_file(filepath)
    if content is None:
        record.status = ConformerStatus.PARSE_FAILED
        record.add_error(f"Cannot read file: {filepath}")
        return

    extract_energies(content, record)
    extract_frequencies(content, record, config)


def parse_ecd_file(
    filepath: str,
    record: ConformerRecord,
    config: ECDConfig,
) -> None:
    content = _read_file(filepath)
    if content is None:
        record.status = ConformerStatus.PARSE_FAILED
        record.add_error(f"Cannot read file: {filepath}")
        return

    cd_ok = extract_cd_data(content, record, config.cd_gauge)

    if record.scf_energy is None:
        extract_energies(content, record)
        if record.scf_energy is not None:
            record.add_warning("Energy extracted from ECD file (not OPT)")

    if cd_ok and record.scf_energy is not None:
        _restore_ok_if_recovered(record)


def parse_single_file(
    filepath: str,
    record: ConformerRecord,
    config: ECDConfig,
) -> None:
    content = _read_file(filepath)
    if content is None:
        record.status = ConformerStatus.PARSE_FAILED
        record.add_error(f"Cannot read file: {filepath}")
        return

    extract_energies(content, record)
    extract_frequencies(content, record, config)
    extract_cd_data(content, record, config.cd_gauge)
