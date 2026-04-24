"""Gaussian-specific parsing helpers."""

from __future__ import annotations

import re
from pathlib import Path

from .config import DP4Config, ImagFreqPolicy
from .experimental import normalize_nucleus
from .models import ConformerRecord, ConformerStatus, FileRole, OrcaFileInfo
from .parser_common import atomic_number_to_symbol, infer_conf_id, read_text
from .solvent import normalize_reference_solvent

_SCF_DONE_PATTERN = re.compile(r"SCF Done:\s+E\([^)]+\)\s*=\s*([-\d.]+)", re.IGNORECASE)
_FREE_ENERGY_PATTERN = re.compile(
    r"Sum of electronic and thermal Free Energies=\s*([-\d.]+)",
    re.IGNORECASE,
)
_FREQ_LINE_PATTERN = re.compile(r"Frequencies --\s+(.+)")
_ISOTROPIC_PATTERN = re.compile(
    r"^\s*(\d+)\s+([A-Z][a-z]?)\s+Isotropic\s*=\s*([-\d.]+)",
    re.IGNORECASE | re.MULTILINE,
)
_NORMAL_TERMINATION_PATTERN = re.compile(r"Normal termination", re.IGNORECASE)
_STANDARD_ORIENTATION_PATTERN = re.compile(r"^\s*Standard orientation:\s*$", re.MULTILINE)
_INPUT_ORIENTATION_PATTERN = re.compile(r"^\s*Input orientation:\s*$", re.MULTILINE)
_DASH_PATTERN = re.compile(r"^\s*-{5,}\s*$")
_ROUTE_START_PATTERN = re.compile(r"^\s*#[pnt]?\s*(.*)$", re.IGNORECASE)

PROGRAM_MARKERS = (
    re.compile(r"Entering Gaussian System", re.IGNORECASE),
    _SCF_DONE_PATTERN,
    _STANDARD_ORIENTATION_PATTERN,
    _ISOTROPIC_PATTERN,
)


def detect_gaussian_content(content: str) -> bool:
    return any(pattern.search(content) for pattern in PROGRAM_MARKERS)


def _extract_frequency_values(content: str) -> list[float]:
    values: list[float] = []
    for match in _FREQ_LINE_PATTERN.finditer(content):
        values.extend(float(token) for token in match.group(1).split())
    return values


def _has_coordinates(content: str) -> bool:
    return bool(_STANDARD_ORIENTATION_PATTERN.search(content) or _INPUT_ORIENTATION_PATTERN.search(content))


def classify_gaussian_content(content: str, path: str, config: DP4Config) -> OrcaFileInfo:
    has_shieldings = _ISOTROPIC_PATTERN.search(content) is not None
    has_energy = _SCF_DONE_PATTERN.search(content) is not None or _FREE_ENERGY_PATTERN.search(content) is not None
    frequencies = _extract_frequency_values(content)
    has_frequencies = bool(frequencies)
    has_coordinates = _has_coordinates(content)

    if has_shieldings and (has_frequencies or has_energy):
        role = FileRole.COMBINED
    elif has_shieldings:
        role = FileRole.NMR
    elif has_energy or has_frequencies or has_coordinates:
        role = FileRole.OPT
    else:
        role = FileRole.UNKNOWN

    n_imag_freq = len([value for value in frequencies if value < 0])
    return OrcaFileInfo(
        path=str(Path(path).resolve()),
        role=role,
        program="gaussian",
        conf_id=infer_conf_id(path, config),
        has_energy=has_energy,
        has_frequencies=has_frequencies,
        has_shieldings=has_shieldings,
        n_imag_freq=n_imag_freq,
    )


def classify_gaussian_file(path: str, config: DP4Config | None = None) -> OrcaFileInfo:
    cfg = config or DP4Config()
    return classify_gaussian_content(read_text(path), path, cfg)


def _extract_energies(content: str, record: ConformerRecord) -> None:
    scf_matches = _SCF_DONE_PATTERN.findall(content)
    if scf_matches:
        record.scf_energy = float(scf_matches[-1])

    free_energy_match = _FREE_ENERGY_PATTERN.search(content)
    if free_energy_match:
        record.gibbs_energy = float(free_energy_match.group(1))
        if record.scf_energy is not None:
            record.gibbs_correction = record.gibbs_energy - record.scf_energy

    if record.scf_energy is None and record.gibbs_energy is None:
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


def _extract_orientation_block(content: str, header_pattern: re.Pattern[str]) -> list[tuple[int, str, float, float, float]]:
    lines = content.splitlines()
    last_rows: list[tuple[int, str, float, float, float]] = []
    index = 0
    while index < len(lines):
        if not header_pattern.match(lines[index]):
            index += 1
            continue

        dash_count = 0
        index += 1
        while index < len(lines):
            if _DASH_PATTERN.match(lines[index]):
                dash_count += 1
                index += 1
                if dash_count == 2:
                    break
                continue
            index += 1
        if dash_count < 2:
            continue

        rows: list[tuple[int, str, float, float, float]] = []
        while index < len(lines):
            line = lines[index]
            if _DASH_PATTERN.match(line):
                break
            parts = line.split()
            if len(parts) >= 6 and parts[0].isdigit() and parts[1].isdigit():
                atom_id = int(parts[0])
                atomic_number = int(parts[1])
                x = float(parts[-3])
                y = float(parts[-2])
                z = float(parts[-1])
                rows.append((atom_id, atomic_number_to_symbol(atomic_number), x, y, z))
            index += 1
        if rows:
            last_rows = rows
        index += 1
    return last_rows


def _extract_coordinates(content: str, record: ConformerRecord) -> None:
    rows = _extract_orientation_block(content, _STANDARD_ORIENTATION_PATTERN)
    if not rows:
        rows = _extract_orientation_block(content, _INPUT_ORIENTATION_PATTERN)
    if not rows:
        return

    record.coordinates = {atom_id: (x, y, z) for atom_id, _element, x, y, z in rows}
    record.atom_elements.update({atom_id: element for atom_id, element, _x, _y, _z in rows})


def _extract_shieldings(content: str, record: ConformerRecord) -> None:
    parsed: dict[str, dict[int, float]] = {}
    elements: dict[int, str] = {}
    for match in _ISOTROPIC_PATTERN.finditer(content):
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


def _apply_termination_warning(content: str, record: ConformerRecord) -> None:
    if not _NORMAL_TERMINATION_PATTERN.search(content):
        record.add_warning("Gaussian job does not show a normal termination marker")


def _extract_route_sections(content: str) -> list[str]:
    """Collect Gaussian route sections, including wrapped continuation lines."""
    routes: list[str] = []
    lines = content.splitlines()
    index = 0
    while index < len(lines):
        match = _ROUTE_START_PATTERN.match(lines[index])
        if not match:
            index += 1
            continue

        route_lines = [match.group(1).strip()]
        index += 1
        while index < len(lines):
            line = lines[index].strip()
            if not line or _DASH_PATTERN.match(line):
                break
            route_lines.append(line)
            index += 1
        route = " ".join(part for part in route_lines if part)
        if route:
            routes.append(re.sub(r"\s+", " ", route).strip())
    return routes


def _token_looks_like_basis(token: str) -> bool:
    return bool(
        re.search(r"\d", token)
        and re.search(r"[A-Za-z]", token)
        and not re.match(r"^[A-Za-z]+=", token)
        and token.lower() not in {"nmr", "opt", "freq", "sp"}
    )


def _normalize_gaussian_method(method: str) -> str:
    for prefix in ("RO", "R", "U"):
        if method.startswith(prefix) and len(method) > len(prefix):
            stripped = method[len(prefix):]
            if re.search(r"(B3LYP|MPW|M06|WB97|PBE|HF|MP2|BLYP)", stripped, re.IGNORECASE):
                return stripped
    return method


def _extract_level_from_route(route: str) -> str:
    tokens = route.split()
    for token in tokens:
        clean = token.strip(",;")
        if "/" not in clean:
            continue
        if clean.lower().startswith(("scrf", "guess", "geom", "scf", "int", "iop")):
            continue
        method, basis = clean.split("/", 1)
        method = _normalize_gaussian_method(method.strip())
        basis = basis.strip()
        if method and basis and _token_looks_like_basis(basis):
            return _with_solvent_prefix(route, f"{method}/{basis}")

    for index, token in enumerate(tokens[:-1]):
        method = token.strip(",;")
        basis = tokens[index + 1].strip(",;")
        if "=" in method or "/" in method or "/" in basis:
            continue
        if not re.search(r"[A-Za-z]", method) or not _token_looks_like_basis(basis):
            continue
        method = _normalize_gaussian_method(method)
        return _with_solvent_prefix(route, f"{method}/{basis}")
    return ""


def _with_solvent_prefix(route: str, level: str) -> str:
    lower_route = route.lower()
    if re.search(r"\bscrf\s*=?\s*\([^)]*\bsmd\b", lower_route):
        return f"SMD/{level}"
    if re.search(r"\b(?:scrf\s*=?\s*\([^)]*\bpcm\b|pcm\b)", lower_route):
        return f"PCM/{level}"
    return level


def _extract_theory_level(content: str) -> str:
    """Extract method/basis from Gaussian route sections."""
    parsed = [(route, _extract_level_from_route(route)) for route in _extract_route_sections(content)]
    parsed = [(route, level) for route, level in parsed if level]
    if not parsed:
        return ""
    for route, level in reversed(parsed):
        if re.search(r"\bnmr\b", route, re.IGNORECASE):
            return level
    return parsed[-1][1]


def _extract_reference_solvent(content: str) -> str | None:
    """Extract the requested solvent from Gaussian route sections."""
    routes = _extract_route_sections(content)
    for route in reversed(routes):
        match = re.search(r"\bsolvent\s*=\s*([A-Za-z0-9_+\-]+)", route, re.IGNORECASE)
        if match:
            solvent = normalize_reference_solvent(match.group(1))
            if solvent:
                return solvent
    return None


def _apply_route_metadata(content: str, record: ConformerRecord) -> None:
    record.theory_level = _extract_theory_level(content)
    record.reference_solvent = _extract_reference_solvent(content)


def parse_gaussian_record_from_files(
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
            _apply_route_metadata(content, record)
            _apply_termination_warning(content, record)
            _extract_energies(content, record)
            _extract_frequencies(content, record, config)
            _extract_coordinates(content, record)
            _extract_shieldings(content, record)
            return record
        if opt_path:
            opt_content = read_text(opt_path)
            _apply_route_metadata(opt_content, record)
            _apply_termination_warning(opt_content, record)
            _extract_energies(opt_content, record)
            _extract_frequencies(opt_content, record, config)
            _extract_coordinates(opt_content, record)
        if nmr_path:
            nmr_content = read_text(nmr_path)
            if not record.theory_level:
                record.theory_level = _extract_theory_level(nmr_content)
            if not record.reference_solvent:
                record.reference_solvent = _extract_reference_solvent(nmr_content)
            _apply_termination_warning(nmr_content, record)
            if not record.coordinates:
                _extract_coordinates(nmr_content, record)
            _extract_shieldings(nmr_content, record)
    except Exception as exc:
        record.status = ConformerStatus.PARSE_FAILED
        record.add_error(str(exc))
    return record
