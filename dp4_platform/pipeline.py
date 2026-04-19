"""Pipeline entry point for the standalone DP4 workflow."""

from __future__ import annotations

from collections.abc import Callable
from collections import Counter

from .config import DP4Config
from .dp4 import load_parameter_table, score_candidates
from .energy import boltzmann_average_shieldings, compute_boltzmann_weights
from .experimental import load_experimental_assignments
from .models import CandidateIsomer, DP4Result
from .parser import discover_candidate_directories, load_candidate_from_directory
from .report import write_reports


class DP4Pipeline:
    def __init__(
        self,
        config: DP4Config,
        logger: Callable[[str], None] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ):
        self.config = config
        self.logger = logger
        self.progress_callback = progress_callback
        self.candidates = []
        self.assignments = []
        self.parameter_table = {}
        self._log: list[str] = []

    def log(self, message: str) -> None:
        self._log.append(message)
        if self.logger is not None:
            self.logger(message)
        print(message)

    def _emit_progress(self, done: int, total: int) -> None:
        if self.progress_callback is not None:
            self.progress_callback(done, total)

    @property
    def logs(self) -> list[str]:
        return list(self._log)

    def _candidate_sources(self) -> list[tuple[str, str]]:
        if self.config.candidate_paths:
            return sorted(self.config.candidate_paths.items(), key=lambda item: item[0])
        return discover_candidate_directories(self.config.candidates_root)

    def _failed_status_summary(self, candidate: CandidateIsomer) -> str:
        counts = Counter(record.status.value for record in candidate.collection.failed_records)
        if not counts:
            return "none"
        return ", ".join(f"{status}={counts[status]}" for status in sorted(counts))

    def run(self) -> DP4Result:
        self.log("Loading experimental assignments...")
        self.assignments = load_experimental_assignments(self.config.exp_nmr_file, self.config.nuclei)

        self.log("Loading parameter table...")
        self.parameter_table = load_parameter_table(self.config.parameter_table)

        self.log("Discovering candidate isomers...")
        candidate_dirs = self._candidate_sources()
        total = len(candidate_dirs) + 2
        self._emit_progress(0, total)

        self.candidates = []
        for index, (name, directory) in enumerate(candidate_dirs):
            self.log(f"Parsing candidate '{name}'...")
            candidate = load_candidate_from_directory(name=name, directory=directory, config=self.config)
            self.log(
                f"  Found {len(candidate.collection.all_records)} conformers "
                f"({len(candidate.collection.usable_records)} usable, "
                f"{len(candidate.unpaired_opt) + len(candidate.unpaired_nmr)} unpaired files)"
            )
            if candidate.collection.failed_records:
                self.log(f"  Failed status summary: {self._failed_status_summary(candidate)}")
            if not candidate.collection.usable_records:
                raise ValueError(
                    f"Candidate '{name}' has no usable conformers "
                    f"({self._failed_status_summary(candidate)})"
                )
            compute_boltzmann_weights(candidate, self.config)
            boltzmann_average_shieldings(candidate, self.config.nuclei)
            self.candidates.append(candidate)
            self._emit_progress(index + 1, total)

        self.log("Scoring candidates...")
        candidate_scores = score_candidates(
            candidates=self.candidates,
            assignments=self.assignments,
            config=self.config,
            parameter_table=self.parameter_table,
        )
        self._emit_progress(len(candidate_dirs) + 1, total)

        result = DP4Result(
            candidate_scores=candidate_scores,
            nuclei=self.config.nuclei,
            total_assignments=len(self.assignments),
            output_dir=self.config.output_dir,
        )
        self.log("Writing reports...")
        report_result = write_reports(self.config, self.candidates, result)
        self._emit_progress(total, total)
        return report_result
