"""Program-aware candidate discovery and parsing for the standalone DP4 project."""

from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from pathlib import Path

from .config import DP4Config
from .models import CandidateIsomer, ConformerStatus, FileRole, OrcaFileInfo, OrcaFilePair
from .parser_common import infer_conf_id, read_text
from .parser_gaussian import (
    PROGRAM_MARKERS as GAUSSIAN_PROGRAM_MARKERS,
    classify_gaussian_content,
    classify_gaussian_file,
    detect_gaussian_content,
    parse_gaussian_record_from_files,
)
from .parser_orca import (
    PROGRAM_MARKERS as ORCA_PROGRAM_MARKERS,
    classify_orca_content,
    classify_orca_file,
    detect_orca_content,
    parse_orca_record_from_files,
)


def discover_candidate_directories(root: str) -> list[tuple[str, str]]:
    base = Path(root)
    if not base.exists():
        raise ValueError(f"Candidates root does not exist: {root}")
    directories = [(item.name, str(item)) for item in sorted(base.iterdir()) if item.is_dir()]
    if not directories:
        raise ValueError(f"No candidate directories found under: {root}")
    return directories


def _list_output_files(directory: str, config: DP4Config) -> list[str]:
    base = Path(directory)
    if not base.exists():
        raise ValueError(f"Candidate directory does not exist: {directory}")

    if config.recursive:
        files = [path for path in base.rglob("*") if path.is_file()]
    else:
        files = [path for path in base.iterdir() if path.is_file()]

    result = [str(path) for path in files if path.suffix.lower() in config.file_extensions]
    if not result:
        raise ValueError(f"No output files found in candidate directory: {directory}")
    return sorted(result)


def _unknown_file_info(path: str, config: DP4Config) -> OrcaFileInfo:
    return OrcaFileInfo(
        path=str(Path(path).resolve()),
        role=FileRole.UNKNOWN,
        program="unknown",
        conf_id=infer_conf_id(path, config),
        has_energy=False,
        has_frequencies=False,
        has_shieldings=False,
        n_imag_freq=0,
    )


def _marker_score(content: str, patterns: tuple[re.Pattern[str], ...]) -> int:
    return sum(1 for pattern in patterns if pattern.search(content))


def _classify_file(path: str, config: DP4Config) -> OrcaFileInfo:
    if config.program_mode == "orca":
        return classify_orca_file(path, config)
    if config.program_mode == "gaussian":
        return classify_gaussian_file(path, config)

    content = read_text(path)
    orca_detected = detect_orca_content(content)
    gaussian_detected = detect_gaussian_content(content)

    if orca_detected and not gaussian_detected:
        return classify_orca_content(content, path, config)
    if gaussian_detected and not orca_detected:
        return classify_gaussian_content(content, path, config)
    if orca_detected and gaussian_detected:
        orca_score = _marker_score(content, ORCA_PROGRAM_MARKERS)
        gaussian_score = _marker_score(content, GAUSSIAN_PROGRAM_MARKERS)
        if gaussian_score >= orca_score:
            return classify_gaussian_content(content, path, config)
        return classify_orca_content(content, path, config)

    orca_info = classify_orca_content(content, path, config)
    gaussian_info = classify_gaussian_content(content, path, config)
    if orca_info.role != FileRole.UNKNOWN and gaussian_info.role == FileRole.UNKNOWN:
        return orca_info
    if gaussian_info.role != FileRole.UNKNOWN and orca_info.role == FileRole.UNKNOWN:
        return gaussian_info
    if gaussian_info.role != FileRole.UNKNOWN and orca_info.role != FileRole.UNKNOWN:
        if gaussian_info.has_shieldings and gaussian_info.has_frequencies:
            return gaussian_info
        if orca_info.has_shieldings and orca_info.has_frequencies:
            return orca_info
    return _unknown_file_info(path, config)


def discover_candidate_files(directory: str, config: DP4Config) -> list[OrcaFileInfo]:
    files = [_classify_file(path, config) for path in _list_output_files(directory, config)]
    programs = {info.program for info in files if info.program != "unknown" and info.role != FileRole.UNKNOWN}
    if len(programs) > 1:
        joined = ", ".join(sorted(programs))
        raise ValueError(f"Mixed quantum chemistry programs detected in one candidate directory: {joined}")
    return files


def _group_by_conf_id(files: list[OrcaFileInfo]) -> dict[int, list[OrcaFileInfo]]:
    grouped: dict[int, list[OrcaFileInfo]] = {}
    for info in files:
        if info.conf_id is None:
            continue
        grouped.setdefault(info.conf_id, []).append(info)
    return grouped


def _normalized_filename(path: str) -> str:
    stem = Path(path).stem.lower()
    stem = re.sub(r"(?:^|[_\-.])(opt|nmr|orca|gau|gaussian|freq|sp|shield(?:ing)?)(?:[_\-.]|$)", "_", stem)
    stem = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    return stem or Path(path).stem.lower()


def _filename_score(opt_info: OrcaFileInfo, nmr_info: OrcaFileInfo) -> float:
    opt_name = _normalized_filename(opt_info.path)
    nmr_name = _normalized_filename(nmr_info.path)
    ratio = SequenceMatcher(None, opt_name, nmr_name).ratio()
    prefix = len(os.path.commonprefix([Path(opt_info.path).stem.lower(), Path(nmr_info.path).stem.lower()]))
    return max(ratio, prefix / max(len(opt_name), len(nmr_name), 1))


def _pair_by_filename(
    opt_files: list[OrcaFileInfo],
    nmr_files: list[OrcaFileInfo],
) -> tuple[list[OrcaFilePair], list[OrcaFileInfo], list[OrcaFileInfo]]:
    remaining_opt = sorted(opt_files, key=lambda item: item.path)
    remaining_nmr = sorted(nmr_files, key=lambda item: item.path)
    pairs: list[OrcaFilePair] = []

    while remaining_opt and remaining_nmr:
        best: tuple[float, int, int] | None = None
        for opt_index, opt_info in enumerate(remaining_opt):
            for nmr_index, nmr_info in enumerate(remaining_nmr):
                if opt_info.program != nmr_info.program:
                    continue
                score = _filename_score(opt_info, nmr_info)
                if best is None or score > best[0]:
                    best = (score, opt_index, nmr_index)
        if best is None or best[0] < 0.35:
            break
        _, opt_index, nmr_index = best
        opt_info = remaining_opt.pop(opt_index)
        nmr_info = remaining_nmr.pop(nmr_index)
        pairs.append(
            OrcaFilePair(
                conf_id=opt_info.conf_id if opt_info.conf_id is not None else nmr_info.conf_id,
                opt_file=opt_info,
                nmr_file=nmr_info,
            )
        )

    return pairs, remaining_opt, remaining_nmr


def pair_discovered_files(
    files: list[OrcaFileInfo],
    config: DP4Config,
) -> tuple[list[OrcaFilePair], list[OrcaFileInfo], list[OrcaFileInfo]]:
    combined_files = sorted([info for info in files if info.role == FileRole.COMBINED], key=lambda item: item.path)
    opt_files = sorted([info for info in files if info.role == FileRole.OPT], key=lambda item: item.path)
    nmr_files = sorted([info for info in files if info.role == FileRole.NMR], key=lambda item: item.path)
    paired: list[OrcaFilePair] = [
        OrcaFilePair(conf_id=info.conf_id, combined_file=info) for info in combined_files if info.conf_id is None
    ]
    unpaired_opt: list[OrcaFileInfo] = []
    unpaired_nmr: list[OrcaFileInfo] = []

    if config.auto_pair_strategy == "manual":
        return (
            paired + [OrcaFilePair(conf_id=info.conf_id, combined_file=info) for info in combined_files if info.conf_id is not None],
            opt_files,
            nmr_files,
        )

    if config.auto_pair_strategy == "filename":
        more_pairs, unpaired_opt, unpaired_nmr = _pair_by_filename(opt_files, nmr_files)
        paired.extend(more_pairs)
        paired.extend(OrcaFilePair(conf_id=info.conf_id, combined_file=info) for info in combined_files if info.conf_id is not None)
        return (
            sorted(
                paired,
                key=lambda item: (
                    item.conf_id is None,
                    item.conf_id or 0,
                    (item.combined_file or item.opt_file or item.nmr_file).path,
                ),
            ),
            unpaired_opt,
            unpaired_nmr,
        )

    grouped_opt = _group_by_conf_id(opt_files)
    grouped_nmr = _group_by_conf_id(nmr_files)
    grouped_combined = _group_by_conf_id([info for info in combined_files if info.conf_id is not None])

    all_conf_ids = sorted(set(grouped_opt) | set(grouped_nmr) | set(grouped_combined))
    for conf_id in all_conf_ids:
        if conf_id in grouped_combined:
            selected = sorted(grouped_combined[conf_id], key=lambda item: item.path)
            primary = selected[0]
            pair = OrcaFilePair(conf_id=conf_id, combined_file=primary)
            if len(selected) > 1:
                pair.warnings.append(
                    f"Multiple combined files detected for conf {conf_id}; using {Path(primary.path).name}"
                )
            paired.append(pair)
            continue

        opt_group = sorted(grouped_opt.get(conf_id, []), key=lambda item: item.path)
        nmr_group = sorted(grouped_nmr.get(conf_id, []), key=lambda item: item.path)
        primary_opt = opt_group[0] if opt_group else None
        primary_nmr = nmr_group[0] if nmr_group else None

        if len(opt_group) > 1:
            unpaired_opt.extend(opt_group[1:])
        if len(nmr_group) > 1:
            unpaired_nmr.extend(nmr_group[1:])

        if primary_opt and primary_nmr:
            pair = OrcaFilePair(conf_id=conf_id, opt_file=primary_opt, nmr_file=primary_nmr)
            if len(opt_group) > 1:
                pair.warnings.append(
                    f"Multiple OPT files detected for conf {conf_id}; using {Path(primary_opt.path).name}"
                )
            if len(nmr_group) > 1:
                pair.warnings.append(
                    f"Multiple NMR files detected for conf {conf_id}; using {Path(primary_nmr.path).name}"
                )
            paired.append(pair)
        elif primary_opt:
            unpaired_opt.append(primary_opt)
        elif primary_nmr:
            unpaired_nmr.append(primary_nmr)

    no_id_opt = [info for info in opt_files if info.conf_id is None]
    no_id_nmr = [info for info in nmr_files if info.conf_id is None]
    fallback_pairs, leftover_opt, leftover_nmr = _pair_by_filename(no_id_opt, no_id_nmr)
    paired.extend(fallback_pairs)
    unpaired_opt.extend(leftover_opt)
    unpaired_nmr.extend(leftover_nmr)

    return (
        sorted(
            paired,
            key=lambda item: (
                item.conf_id is None,
                item.conf_id or 0,
                (item.combined_file or item.opt_file or item.nmr_file).path,
            ),
        ),
        sorted(unpaired_opt, key=lambda item: item.path),
        sorted(unpaired_nmr, key=lambda item: item.path),
    )


def discover_and_pair_files(
    folder: str,
    config: DP4Config,
) -> tuple[list[OrcaFilePair], list[OrcaFileInfo], list[OrcaFileInfo]]:
    files = discover_candidate_files(folder, config)
    return pair_discovered_files(files, config)


def apply_pairing_overrides(
    paired: list[OrcaFilePair],
    unpaired_opt: list[OrcaFileInfo],
    unpaired_nmr: list[OrcaFileInfo],
    overrides: dict[str, str],
) -> tuple[list[OrcaFilePair], list[OrcaFileInfo], list[OrcaFileInfo]]:
    if not overrides:
        return paired, unpaired_opt, unpaired_nmr

    pairs = list(paired)
    orphan_opt = list(unpaired_opt)
    orphan_nmr = list(unpaired_nmr)

    def _find_opt(path: str) -> OrcaFileInfo | None:
        for pair in pairs:
            if pair.opt_file and Path(pair.opt_file.path) == Path(path):
                return pair.opt_file
        for info in orphan_opt:
            if Path(info.path) == Path(path):
                return info
        return None

    def _find_nmr(path: str) -> OrcaFileInfo | None:
        for pair in pairs:
            if pair.nmr_file and Path(pair.nmr_file.path) == Path(path):
                return pair.nmr_file
        for info in orphan_nmr:
            if Path(info.path) == Path(path):
                return info
        return None

    def _detach_opt(path: str) -> OrcaFileInfo | None:
        for pair in list(pairs):
            if pair.opt_file and Path(pair.opt_file.path) == Path(path):
                info = pair.opt_file
                if pair.nmr_file:
                    orphan_nmr.append(pair.nmr_file)
                pairs.remove(pair)
                return info
        for info in list(orphan_opt):
            if Path(info.path) == Path(path):
                orphan_opt.remove(info)
                return info
        return None

    def _detach_nmr(path: str) -> OrcaFileInfo | None:
        for pair in list(pairs):
            if pair.nmr_file and Path(pair.nmr_file.path) == Path(path):
                info = pair.nmr_file
                if pair.opt_file:
                    orphan_opt.append(pair.opt_file)
                pairs.remove(pair)
                return info
        for info in list(orphan_nmr):
            if Path(info.path) == Path(path):
                orphan_nmr.remove(info)
                return info
        return None

    for opt_path, nmr_path in overrides.items():
        opt_info = _find_opt(opt_path)
        nmr_info = _find_nmr(nmr_path)
        if opt_info is None or nmr_info is None or opt_info.program != nmr_info.program:
            continue
        opt_info = _detach_opt(opt_path)
        nmr_info = _detach_nmr(nmr_path)
        if opt_info is None or nmr_info is None:
            continue
        pairs.append(
            OrcaFilePair(
                conf_id=opt_info.conf_id if opt_info.conf_id is not None else nmr_info.conf_id,
                opt_file=opt_info,
                nmr_file=nmr_info,
                warnings=["Pairing override applied"],
            )
        )

    return (
        sorted(
            pairs,
            key=lambda item: (
                item.conf_id is None,
                item.conf_id or 0,
                (item.combined_file or item.opt_file or item.nmr_file).path,
            ),
        ),
        sorted(orphan_opt, key=lambda item: item.path),
        sorted(orphan_nmr, key=lambda item: item.path),
    )


def _assign_conf_id(preferred_conf_id: int | None, used_ids: set[int], next_id: int) -> tuple[int, int]:
    if preferred_conf_id is not None and preferred_conf_id not in used_ids:
        used_ids.add(preferred_conf_id)
        return preferred_conf_id, next_id

    candidate = max(next_id, 1)
    while candidate in used_ids:
        candidate += 1
    used_ids.add(candidate)
    return candidate, candidate + 1


def _candidate_program(files: list[OrcaFileInfo], config: DP4Config) -> str:
    if config.program_mode in {"orca", "gaussian"}:
        return config.program_mode
    programs = {info.program for info in files if info.program != "unknown" and info.role != FileRole.UNKNOWN}
    if len(programs) == 1:
        return next(iter(programs))
    return "unknown"


def _parse_record_from_files(
    conf_id: int,
    config: DP4Config,
    program: str,
    opt_path: str | None = None,
    nmr_path: str | None = None,
    combined_path: str | None = None,
):
    if program == "gaussian":
        return parse_gaussian_record_from_files(
            conf_id=conf_id,
            config=config,
            opt_path=opt_path,
            nmr_path=nmr_path,
            combined_path=combined_path,
        )
    return parse_orca_record_from_files(
        conf_id=conf_id,
        config=config,
        opt_path=opt_path,
        nmr_path=nmr_path,
        combined_path=combined_path,
    )


def parse_orca_nmr_file(path: str, conf_id: int, config: DP4Config):
    return parse_orca_record_from_files(conf_id=conf_id, config=config, combined_path=path)


def load_candidate_from_directory(name: str, directory: str, config: DP4Config) -> CandidateIsomer:
    candidate = CandidateIsomer(
        name=name,
        directory=directory,
        pairing_overrides=dict(config.pairing_overrides.get(name, {})),
    )
    discovered_files = discover_candidate_files(directory, config)
    paired, unpaired_opt, unpaired_nmr = pair_discovered_files(discovered_files, config)
    paired, unpaired_opt, unpaired_nmr = apply_pairing_overrides(
        paired,
        unpaired_opt,
        unpaired_nmr,
        candidate.pairing_overrides,
    )

    candidate.unpaired_opt = unpaired_opt
    candidate.unpaired_nmr = unpaired_nmr

    used_ids: set[int] = set()
    next_id = 1
    default_program = _candidate_program(discovered_files, config)

    for pair in paired:
        record_conf_id, next_id = _assign_conf_id(pair.conf_id, used_ids, next_id)
        pair_program = (
            pair.combined_file.program if pair.combined_file else
            pair.opt_file.program if pair.opt_file else
            pair.nmr_file.program if pair.nmr_file else
            default_program
        )
        record = _parse_record_from_files(
            conf_id=record_conf_id,
            config=config,
            program=pair_program,
            opt_path=pair.opt_file.path if pair.opt_file else None,
            nmr_path=pair.nmr_file.path if pair.nmr_file else None,
            combined_path=pair.combined_file.path if pair.combined_file else None,
        )
        for warning in pair.warnings:
            record.add_warning(warning)
        candidate.collection.add(record)

    for info in unpaired_opt:
        record_conf_id, next_id = _assign_conf_id(info.conf_id, used_ids, next_id)
        record = _parse_record_from_files(conf_id=record_conf_id, config=config, program=info.program, opt_path=info.path)
        if record.status != ConformerStatus.PARSE_FAILED:
            record.status = ConformerStatus.UNPAIRED
            record.add_warning("OPT file has no paired NMR file")
        candidate.collection.add(record)

    for info in unpaired_nmr:
        record_conf_id, next_id = _assign_conf_id(info.conf_id, used_ids, next_id)
        record = _parse_record_from_files(conf_id=record_conf_id, config=config, program=info.program, nmr_path=info.path)
        if record.status != ConformerStatus.PARSE_FAILED:
            record.status = ConformerStatus.UNPAIRED
            record.add_warning("NMR file has no paired OPT file")
        candidate.collection.add(record)

    if not candidate.collection.all_records:
        raise ValueError(f"Candidate '{name}' contains no readable conformer files")
    return candidate
