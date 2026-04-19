"""CLI entry point for the standalone DP4 workflow."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    package_root = Path(__file__).resolve().parents[1]
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    from dp4_platform.config import DP4Config, ImagFreqPolicy, ScalingMode, WeightingStrategy
    from dp4_platform.pipeline import DP4Pipeline
else:
    from .config import DP4Config, ImagFreqPolicy, ScalingMode, WeightingStrategy
    from .pipeline import DP4Pipeline


def _parse_candidate_arg(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("Candidate must use name=path format")
    name, path = value.split("=", 1)
    name = name.strip()
    path = path.strip()
    if not name or not path:
        raise argparse.ArgumentTypeError("Candidate must use name=path format")
    return name, path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone ORCA/Gaussian DP4 workflow")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--candidates-root", help="Root directory containing candidate folders")
    source_group.add_argument(
        "--candidate",
        action="append",
        type=_parse_candidate_arg,
        help="Candidate mapping in name=path format; may be repeated",
    )
    source_group.add_argument("--project-file", help="Saved DP4 project JSON")
    parser.add_argument("--exp-file", help="Experimental assignment CSV")
    parser.add_argument("--output-dir", help="Output directory")
    parser.add_argument("--parameter-table", help="Custom parameter table JSON")
    parser.add_argument("--nmr-dirname", help="Deprecated optional subdirectory inside each candidate")
    parser.add_argument("--nuclei", nargs="+", help="Nuclei to score, e.g. 1H 13C")
    parser.add_argument("--filename-pattern", help="Regex for conformer id extraction")
    parser.add_argument("--weighting", choices=[item.value for item in WeightingStrategy], help="Weighting strategy")
    parser.add_argument("--temperature", type=float, help="Boltzmann temperature in K")
    parser.add_argument("--imag-freq-policy", choices=[item.value for item in ImagFreqPolicy], help="Imaginary frequency policy")
    parser.add_argument("--imag-freq-threshold", type=float, help="Imaginary frequency threshold in cm-1")
    parser.add_argument("--scaling-mode", choices=[item.value for item in ScalingMode], help="Scaling mode")
    parser.add_argument("--program-mode", choices=["auto", "orca", "gaussian"], help="Program detection mode")
    parser.add_argument("--auto-pair-strategy", choices=["conf_id", "filename", "manual"], help="Auto pairing strategy")
    parser.add_argument("--no-recursive", action="store_true", help="Disable recursive search within candidate folders")
    return parser


def _config_from_args(args: argparse.Namespace) -> DP4Config:
    if args.project_file:
        config = DP4Config.from_json(args.project_file)
    else:
        config = DP4Config()

    if args.candidates_root:
        config.candidates_root = args.candidates_root
        config.candidate_paths = {}
    if args.candidate:
        config.candidate_paths = dict(args.candidate)
    if args.exp_file:
        config.exp_nmr_file = args.exp_file
    if args.output_dir:
        config.output_dir = args.output_dir
    if args.parameter_table is not None:
        config.parameter_table = args.parameter_table
    if args.nmr_dirname is not None:
        config.nmr_dirname = args.nmr_dirname
    if args.nuclei:
        config.nuclei = tuple(args.nuclei)
        config.__post_init__()
    if args.filename_pattern:
        config.filename_pattern = args.filename_pattern
    if args.weighting:
        config.weighting = WeightingStrategy(args.weighting)
    if args.temperature is not None:
        config.temperature = args.temperature
    if args.imag_freq_policy:
        config.imag_freq_policy = ImagFreqPolicy(args.imag_freq_policy)
    if args.imag_freq_threshold is not None:
        config.imag_freq_threshold = args.imag_freq_threshold
    if args.scaling_mode:
        config.scaling_mode = ScalingMode(args.scaling_mode)
    if args.program_mode:
        config.program_mode = args.program_mode
    if args.auto_pair_strategy:
        config.auto_pair_strategy = args.auto_pair_strategy
    if args.no_recursive:
        config.recursive = False

    config.__post_init__()
    return config


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = _config_from_args(args)

    if not config.exp_nmr_file:
        parser.error("--exp-file is required unless it is already present in --project-file")
    if not config.candidate_paths and not config.candidates_root:
        parser.error("A candidate source is required")

    result = DP4Pipeline(config).run()
    print("\nFinal ranking")
    for index, score in enumerate(result.ranking, start=1):
        print(
            f"{index}. {score.candidate_name}  "
            f"joint_probability={score.joint_probability:.6f}  "
            f"joint_log_likelihood={score.joint_log_likelihood:.6f}"
        )
    print(f"\nSummary written to: {result.summary_file}")
    return 0
