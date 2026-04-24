"""ORCA-specific parsing helpers."""

from __future__ import annotations

import re
from pathlib import Path

from .config import DP4Config, ImagFreqPolicy
from .experimental import normalize_nucleus
from .models import ConformerRecord, ConformerStatus, FileRole, OrcaFileInfo
from .parser_common import infer_conf_id, read_text
from .solvent import normalize_reference_solvent

_ENERGY_PATTERN = re.compile(r"FINAL SINGLE POINT ENERGY\s+([-\d.]+)")
_GIBBS_PATTERN = re.compile(r"Final Gibbs free energy\s*\.+\s*([-\d.]+)\s*Eh", re.IGNORECASE)
_G_PATTERN = re.compile(r"G\s*=\s*([-\d.]+)\s*Eh")
_GIBBS_CORR_PATTERN = re.compile(r"G-E\(el\)\s*\.+\s*([-\d.]+)\s*Eh", re.IGNORECASE)
_TOTAL_CORR_PATTERN = re.compile(r"Total correction\s*\.+\s*([-\d.]+)\s*Eh", re.IGNORECASE)
_TOTAL_ENERGY_PATTERN = re.compile(r"Total Energy\s*:\s*([-\d.]+)\s*Eh", re.IGNORECASE)
_ELECTRONIC_ENERGY_PATTERN = re.compile(r"Electronic energy\s*\.+\s*([-\d.]+)\s*Eh", re.IGNORECASE)
_THERMAL_ENERGY_PATTERN = re.compile(r"Total thermal energy\s*\.+\s*([-\d.]+)\s*Eh", re.IGNORECASE)
_ENTHALPY_PATTERN = re.compile(r"Total Enthalpy\s*\.+\s*([-\d.]+)\s*Eh", re.IGNORECASE)
_FREQ_PATTERN = re.compile(r"^\s*\d+:\s+([-\d.]+)\s+cm\*\*-1", re.MULTILINE)
_SHIELDING_PATTERNS = [
    re.compile(r"^\s*(\d+)\s+([A-Z][a-z]?)\s+isotropic shielding\s*[:=]\s*([-\d.]+)", re.IGNORECASE),
    re.compile(r"^\s*Atom\s+(\d+)\s+\(([A-Z][a-z]?)\)\s+isotropic shielding\s*[:=]\s*([-\d.]+)", re.IGNORECASE),
    re.compile(r"^\s*Nucleus\s+(\d+)\s+([A-Z][a-z]?).*?isotropic(?:\s+shielding)?\s*[:=]\s*([-\d.]+)", re.IGNORECASE),
]
_FREQUENCY_HEADER_PATTERN = re.compile(r"^\s*VIBRATIONAL FREQUENCIES\b", re.IGNORECASE | re.MULTILINE)
_CARTESIAN_HEADER_PATTERN = re.compile(
    r"CARTESIAN COORDINATES \(ANGSTROEM\)\s*\n-+\s*\n", re.IGNORECASE
)
_CARTESIAN_ROW_PATTERN = re.compile(
    r"^\s*([A-Z][a-z]?)\s+"
    r"([-+]?\d+\.\d+)\s+"
    r"([-+]?\d+\.\d+)\s+"
    r"([-+]?\d+\.\d+)\s*$"
)
_SHIELDING_SUMMARY_PATTERN = re.compile(r"CHEMICAL SHIELDING SUMMARY", re.IGNORECASE)
_SHIELDING_TABLE_ROW_PATTERN = re.compile(
    r"^\s*(\d+)\s+([A-Z][a-z]?)\s+([-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?)"
    r"(?:\s+[-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?)?\s*$"
)
_METHOD_PATTERN = re.compile(r"^DFT level of theory\s*\.+\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_BASIS_PATTERN = re.compile(r"^Basis set\s*\.+\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_INPUT_METHOD_PATTERN = re.compile(r"!\s*(.+)$", re.MULTILINE)
_SOLVENT_LINE_PATTERN = re.compile(r"^Solvent:\s*\.+\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_SMD_SOLVENT_PATTERN = re.compile(r"\bSMDsolvent\s+['\"]?([^'\"\s]+)", re.IGNORECASE)
_CPCM_SOLVENT_PATTERN = re.compile(r"\bCPCM\s*\(\s*([^)]+?)\s*\)", re.IGNORECASE)

PROGRAM_MARKERS = (
    _ENERGY_PATTERN,
    _CARTESIAN_HEADER_PATTERN,
    _SHIELDING_SUMMARY_PATTERN,
)


def detect_orca_content(content: str) -> bool:
    return any(pattern.search(content) for pattern in PROGRAM_MARKERS)


def _extract_frequency_values(content: str) -> list[float]:
    if not _FREQUENCY_HEADER_PATTERN.search(content):
        return []
    return [float(match.group(1)) for match in _FREQ_PATTERN.finditer(content)]


def _has_energy_marker(content: str) -> bool:
    return any(
        pattern.search(content)
        for pattern in (
            _ENERGY_PATTERN,
            _TOTAL_ENERGY_PATTERN,
            _GIBBS_PATTERN,
            _ELECTRONIC_ENERGY_PATTERN,
            _THERMAL_ENERGY_PATTERN,
            _ENTHALPY_PATTERN,
        )
    )


def classify_orca_content(content: str, path: str, config: DP4Config) -> OrcaFileInfo:
    has_shieldings = _SHIELDING_SUMMARY_PATTERN.search(content) is not None or any(
        pattern.match(line)
        for line in content.splitlines()
        for pattern in _SHIELDING_PATTERNS
    )
    has_energy = _has_energy_marker(content)
    frequencies = _extract_frequency_values(content)
    has_frequencies = bool(frequencies)

    if has_shieldings and has_energy and has_frequencies:
        role = FileRole.COMBINED
    elif has_shieldings and not has_frequencies:
        role = FileRole.NMR
    elif has_energy:
        role = FileRole.OPT
    else:
        role = FileRole.UNKNOWN

    n_imag_freq = len([value for value in frequencies if value < 0])
    return OrcaFileInfo(
        path=str(Path(path).resolve()),
        role=role,
        program="orca",
        conf_id=infer_conf_id(path, config),
        has_energy=has_energy,
        has_frequencies=has_frequencies,
        has_shieldings=has_shieldings,
        n_imag_freq=n_imag_freq,
    )


def classify_orca_file(path: str, config: DP4Config | None = None) -> OrcaFileInfo:
    cfg = config or DP4Config()
    return classify_orca_content(read_text(path), path, cfg)


def _extract_energies(content: str, record: ConformerRecord) -> None:
    matches = _ENERGY_PATTERN.findall(content)
    if matches:
        record.scf_energy = float(matches[-1])
    else:
        total_match = _TOTAL_ENERGY_PATTERN.search(content)
        if total_match:
            record.scf_energy = float(total_match.group(1))
        else:
            electronic_match = _ELECTRONIC_ENERGY_PATTERN.search(content)
            if electronic_match:
                record.scf_energy = float(electronic_match.group(1))

    gibbs_match = _GIBBS_PATTERN.search(content) or _G_PATTERN.search(content)
    if gibbs_match:
        record.gibbs_energy = float(gibbs_match.group(1))

    corr_match = _GIBBS_CORR_PATTERN.search(content) or _TOTAL_CORR_PATTERN.search(content)
    if corr_match:
        record.gibbs_correction = float(corr_match.group(1))

    sp_match = re.search(r"E\(MP2\)\s*=\s*([-\d.]+)", content, re.IGNORECASE)
    if sp_match:
        record.sp_energy = float(sp_match.group(1))

    if record.scf_energy is None and record.gibbs_energy is None and record.sp_energy is None:
        record.status = ConformerStatus.NO_ENERGY
        record.add_error("Failed to extract any usable energy value")


def _extract_frequencies(content: str, record: ConformerRecord, config: DP4Config) -> None:
    values = _extract_frequency_values(content)
    if not values:
        record.add_warning("No vibrational frequencies found")
        return

    record.frequencies = values
    record.min_frequency = min(values)
    if config.imag_freq_policy == ImagFreqPolicy.STRICT:
        imaginary = [value for value in values if value < 0]
    elif config.imag_freq_policy == ImagFreqPolicy.TOLERANT:
        imaginary = [value for value in values if value < config.imag_freq_threshold]
    else:
        imaginary = [value for value in values if value < 0]
    record.n_imaginary = len(imaginary)

    if imaginary:
        if config.imag_freq_policy == ImagFreqPolicy.MANUAL:
            record.status = ConformerStatus.SOFT_IMAGINARY_FREQ
            record.add_warning(f"Imaginary frequency detected: min={min(imaginary):.2f} cm-1")
        else:
            record.status = ConformerStatus.IMAGINARY_FREQ
            record.add_error(f"Imaginary frequency detected: min={min(imaginary):.2f} cm-1")


def _extract_coordinates(content: str, record: ConformerRecord) -> None:
    matches = list(_CARTESIAN_HEADER_PATTERN.finditer(content))
    if not matches:
        return
    start = matches[-1].end()
    coords: dict[int, tuple[float, float, float]] = {}
    atom_id = 0
    for line in content[start:].splitlines():
        stripped = line.strip()
        if not stripped:
            if coords:
                break
            continue
        match = _CARTESIAN_ROW_PATTERN.match(line)
        if not match:
            if coords:
                break
            continue
        element = match.group(1)
        x = float(match.group(2))
        y = float(match.group(3))
        z = float(match.group(4))
        coords[atom_id] = (x, y, z)
        record.atom_elements.setdefault(atom_id, element)
        atom_id += 1
    if coords:
        record.coordinates = coords


def _extract_shieldings(content: str, record: ConformerRecord) -> None:
    parsed: dict[str, dict[int, float]] = {}
    elements: dict[int, str] = {}
    for line in content.splitlines():
        for pattern in _SHIELDING_PATTERNS:
            match = pattern.match(line)
            if not match:
                continue
            atom_id = int(match.group(1))
            element = match.group(2)
            shielding = float(match.group(3))
            nucleus = normalize_nucleus(element)
            if nucleus not in {"1H", "13C"}:
                continue
            parsed.setdefault(nucleus, {})[atom_id] = shielding
            elements[atom_id] = element
            break

    if not parsed:
        summary_block = _SHIELDING_SUMMARY_PATTERN.search(content)
        if summary_block:
            started = False
            tail = content[summary_block.end() :]
            for line in tail.splitlines():
                stripped = line.strip()
                if not stripped:
                    if started:
                        break
                    continue
                if set(stripped) == {"-"}:
                    continue
                if stripped.lower().startswith("nucleus") or stripped.lower().startswith("-------"):
                    continue

                match = _SHIELDING_TABLE_ROW_PATTERN.match(line)
                if not match:
                    if started:
                        break
                    continue

                started = True
                atom_id = int(match.group(1))
                element = match.group(2)
                shielding = float(match.group(3))
                nucleus = normalize_nucleus(element)
                if nucleus not in {"1H", "13C"}:
                    continue
                parsed.setdefault(nucleus, {})[atom_id] = shielding
                elements[atom_id] = element

    if not parsed:
        record.status = ConformerStatus.NO_NMR_DATA
        record.add_error("No NMR shielding data found")
        return

    record.shieldings_by_nucleus = parsed
    record.atom_elements.update(elements)


def _make_record(
    conf_id: int,
    opt_file: str | None = None,
    nmr_file: str | None = None,
    combined_file: str | None = None,
) -> ConformerRecord:
    return ConformerRecord(
        conf_id=conf_id,
        label=f"Conf-{conf_id}",
        opt_file=opt_file,
        nmr_file=nmr_file,
        combined_file=combined_file,
        source_file=combined_file or opt_file or nmr_file,
    )


def _extract_theory_level(content: str) -> str:
    """Extract method/basis from ORCA output."""
    method = ""
    basis = ""
    m_match = _METHOD_PATTERN.search(content)
    if m_match:
        method = m_match.group(1).strip()
    else:
        input_match = _INPUT_METHOD_PATTERN.search(content)
        if input_match:
            method = input_match.group(1).strip()
    b_match = _BASIS_PATTERN.search(content)
    if b_match:
        basis = b_match.group(1).strip()
    if method and basis:
        return f"{method}/{basis}"
    if method:
        return method
    return ""


def _extract_reference_solvent(content: str) -> str | None:
    """Extract the requested solvent from ORCA output or echoed input."""
    matches = _SOLVENT_LINE_PATTERN.findall(content)
    if matches:
        solvent = normalize_reference_solvent(matches[-1])
        if solvent:
            return solvent
    match = _SMD_SOLVENT_PATTERN.search(content)
    if match:
        solvent = normalize_reference_solvent(match.group(1))
        if solvent:
            return solvent
    match = _CPCM_SOLVENT_PATTERN.search(content)
    if match:
        solvent = normalize_reference_solvent(match.group(1))
        if solvent:
            return solvent
    return None


def _apply_input_metadata(content: str, record: ConformerRecord) -> None:
    record.theory_level = _extract_theory_level(content)
    record.reference_solvent = _extract_reference_solvent(content)


def parse_orca_record_from_files(
    conf_id: int,
    config: DP4Config,
    opt_path: str | None = None,
    nmr_path: str | None = None,
    combined_path: str | None = None,
) -> ConformerRecord:
    record = _make_record(conf_id=conf_id, opt_file=opt_path, nmr_file=nmr_path, combined_file=combined_path)
    try:
        if combined_path:
            content = read_text(combined_path)
            _apply_input_metadata(content, record)
            _extract_energies(content, record)
            _extract_frequencies(content, record, config)
            _extract_coordinates(content, record)
            _extract_shieldings(content, record)
            return record
        if opt_path:
            opt_content = read_text(opt_path)
            _apply_input_metadata(opt_content, record)
            _extract_energies(opt_content, record)
            _extract_frequencies(opt_content, record, config)
            _extract_coordinates(opt_content, record)
        if nmr_path:
            nmr_content = read_text(nmr_path)
            if not record.theory_level:
                record.theory_level = _extract_theory_level(nmr_content)
            if not record.reference_solvent:
                record.reference_solvent = _extract_reference_solvent(nmr_content)
            if not record.coordinates:
                _extract_coordinates(nmr_content, record)
            _extract_shieldings(nmr_content, record)
    except Exception as exc:
        record.status = ConformerStatus.PARSE_FAILED
        record.add_error(str(exc))
    return record
