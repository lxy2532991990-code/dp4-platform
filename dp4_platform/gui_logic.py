"""Pure helper logic for the DP4 GUI."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace

from .config import DP4Config
from .models import OrcaFileInfo
from .parser import apply_pairing_overrides, pair_discovered_files


@dataclass
class ScanSummary:
    detected_count: int = 0
    paired_count: int = 0
    unpaired_count: int = 0


@dataclass
class PairingRow:
    conf_id: int | None
    opt_path: str | None
    nmr_path: str | None
    combined_path: str | None = None


@dataclass
class CandidateCardState:
    name: str
    directory: str = ""
    pairing_overrides: dict[str, str] = field(default_factory=dict)
    detected_program: str = "unknown"
    detected_count: int = 0
    paired_count: int = 0
    unpaired_count: int = 0
    scan_status: str = "idle"
    scan_error: str = ""
    scan_signature: tuple | None = None
    discovery_signature: tuple | None = None
    scan_summary: ScanSummary = field(default_factory=ScanSummary)
    discovered_files: list[OrcaFileInfo] = field(default_factory=list)
    pairing_rows_by_strategy: dict[str, list[PairingRow]] = field(default_factory=dict)
    scan_dirty: bool = False
    scan_request_id: int = 0


@dataclass
class CandidateScanResult:
    request_id: int
    discovery_signature: tuple
    scan_signature: tuple
    discovered_files: list[OrcaFileInfo] = field(default_factory=list)
    pairing_rows_by_strategy: dict[str, list[PairingRow]] = field(default_factory=dict)
    summary_by_strategy: dict[str, ScanSummary] = field(default_factory=dict)
    error: str | None = None


def _normalized_directory(directory: str) -> str:
    return os.path.abspath(directory) if directory else ""


def _normalized_override_items(overrides: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((os.path.abspath(opt), os.path.abspath(nmr)) for opt, nmr in overrides.items()))


def build_discovery_signature(directory: str, config: DP4Config) -> tuple:
    return (
        _normalized_directory(directory),
        config.program_mode,
        tuple(config.file_extensions),
        config.recursive,
        config.filename_pattern,
    )


def detect_program_from_files(discovered_files: list[OrcaFileInfo]) -> str:
    programs = {info.program for info in discovered_files if info.program != "unknown" and info.role.value != "unknown"}
    if len(programs) == 1:
        return next(iter(programs))
    if len(programs) > 1:
        return "mixed"
    return "unknown"


def build_scan_signature(directory: str, config: DP4Config, overrides: dict[str, str]) -> tuple:
    return (
        build_discovery_signature(directory, config),
        config.auto_pair_strategy,
        _normalized_override_items(overrides),
    )


def clone_pairing_rows(rows: list[PairingRow]) -> list[PairingRow]:
    return [PairingRow(**row.__dict__) for row in rows]


def _pairing_rows_from_parts(paired, unpaired_opt, unpaired_nmr) -> list[PairingRow]:
    rows: list[PairingRow] = []
    for pair in paired:
        if pair.combined_file:
            rows.append(
                PairingRow(
                    conf_id=pair.conf_id,
                    opt_path=None,
                    nmr_path=None,
                    combined_path=pair.combined_file.path,
                )
            )
        else:
            rows.append(
                PairingRow(
                    conf_id=pair.conf_id,
                    opt_path=pair.opt_file.path if pair.opt_file else None,
                    nmr_path=pair.nmr_file.path if pair.nmr_file else None,
                )
            )
    for info in unpaired_opt:
        rows.append(PairingRow(conf_id=info.conf_id, opt_path=info.path, nmr_path=None))
    for info in unpaired_nmr:
        rows.append(PairingRow(conf_id=info.conf_id, opt_path=None, nmr_path=info.path))
    return rows


def _summary_from_rows(rows: list[PairingRow]) -> ScanSummary:
    paired_count = sum(1 for row in rows if row.combined_path or (row.opt_path and row.nmr_path))
    return ScanSummary(
        detected_count=len(rows),
        paired_count=paired_count,
        unpaired_count=len(rows) - paired_count,
    )


def build_pairing_rows_by_strategy(
    discovered_files: list[OrcaFileInfo],
    config: DP4Config,
    overrides: dict[str, str],
    strategies: set[str] | None = None,
) -> tuple[dict[str, list[PairingRow]], dict[str, ScanSummary]]:
    target_strategies = set(strategies or {"conf_id", "filename", config.auto_pair_strategy})
    rows_by_strategy: dict[str, list[PairingRow]] = {}
    summary_by_strategy: dict[str, ScanSummary] = {}
    for strategy in target_strategies:
        cfg = replace(config, auto_pair_strategy=strategy)
        paired, unpaired_opt, unpaired_nmr = pair_discovered_files(discovered_files, cfg)
        if overrides:
            paired, unpaired_opt, unpaired_nmr = apply_pairing_overrides(
                paired,
                unpaired_opt,
                unpaired_nmr,
                overrides,
            )
        rows = _pairing_rows_from_parts(paired, unpaired_opt, unpaired_nmr)
        rows_by_strategy[strategy] = rows
        summary_by_strategy[strategy] = _summary_from_rows(rows)
    return rows_by_strategy, summary_by_strategy


def candidate_scan_is_fresh(state: CandidateCardState, config: DP4Config) -> bool:
    return bool(
        state.directory
        and state.scan_status == "ready"
        and state.scan_signature == build_scan_signature(state.directory, config, state.pairing_overrides)
        and state.pairing_rows_by_strategy
    )


def candidate_can_reuse_discovered_files(state: CandidateCardState, config: DP4Config) -> bool:
    return bool(
        state.directory
        and state.discovered_files
        and state.discovery_signature == build_discovery_signature(state.directory, config)
    )
