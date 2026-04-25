"""Core data models for the standalone DP4 workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FileRole(Enum):
    OPT = "opt"
    NMR = "nmr"
    COMBINED = "combined"
    UNKNOWN = "unknown"


class ConformerStatus(Enum):
    OK = "ok"
    NO_NMR_DATA = "no_nmr_data"
    NO_ENERGY = "no_energy"
    NO_FREQ = "no_freq"
    IMAGINARY_FREQ = "imaginary_freq"
    SOFT_IMAGINARY_FREQ = "soft_imaginary_freq"
    PARSE_FAILED = "parse_failed"
    MANUAL_EXCLUDED = "manual_excluded"
    WEIGHT_ZERO = "weight_zero"
    UNPAIRED = "unpaired"


@dataclass
class OrcaFileInfo:
    path: str
    role: FileRole
    program: str
    conf_id: int | None
    has_energy: bool
    has_frequencies: bool
    has_shieldings: bool
    n_imag_freq: int = 0


@dataclass
class OrcaFilePair:
    conf_id: int | None
    opt_file: OrcaFileInfo | None = None
    nmr_file: OrcaFileInfo | None = None
    combined_file: OrcaFileInfo | None = None
    warnings: list[str] = field(default_factory=list)

    def is_paired(self) -> bool:
        return self.combined_file is not None or (self.opt_file is not None and self.nmr_file is not None)


@dataclass
class ExperimentalAssignment:
    candidate_atom_id: int
    nucleus: str
    exp_shift_ppm: float
    label: str = ""
    exchange_group: str = ""


@dataclass
class ShiftRow:
    atom_id: int
    nucleus: str
    exp_shift_ppm: float
    predicted_shift_ppm: float
    error_ppm: float
    label: str = ""
    unscaled_shift_ppm: float | None = None
    exchange_group: str = ""
    swapped_with: int | None = None
    halogen_neighbor: str = ""


@dataclass
class ConformerRecord:
    conf_id: int
    label: str = ""
    source_file: str | None = None
    opt_file: str | None = None
    nmr_file: str | None = None
    combined_file: str | None = None
    status: ConformerStatus = ConformerStatus.OK
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    scf_energy: float | None = None
    gibbs_correction: float | None = None
    gibbs_energy: float | None = None
    sp_energy: float | None = None
    relative_energy_kcal: float | None = None
    boltzmann_weight: float = 0.0
    manual_weight: float | None = None
    frequencies: list[float] = field(default_factory=list)
    min_frequency: float | None = None
    n_imaginary: int = 0
    atom_elements: dict[int, str] = field(default_factory=dict)
    coordinates: dict[int, tuple[float, float, float]] = field(default_factory=dict)
    shieldings_by_nucleus: dict[str, dict[int, float]] = field(default_factory=dict)
    theory_level: str = ""
    reference_solvent: str | None = None

    def __post_init__(self) -> None:
        if self.combined_file:
            self.source_file = self.combined_file
        elif self.opt_file:
            self.source_file = self.opt_file
        elif self.nmr_file:
            self.source_file = self.nmr_file

    @property
    def is_usable(self) -> bool:
        return self.status in (ConformerStatus.OK, ConformerStatus.SOFT_IMAGINARY_FREQ)

    @property
    def effective_weight(self) -> float:
        if self.manual_weight is not None:
            return self.manual_weight
        return self.boltzmann_weight

    def is_paired(self) -> bool:
        return self.combined_file is not None or (self.opt_file is not None and self.nmr_file is not None)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def add_error(self, message: str) -> None:
        self.errors.append(message)


@dataclass
class ConformerCollection:
    records: list[ConformerRecord] = field(default_factory=list)

    def add(self, record: ConformerRecord) -> None:
        self.records.append(record)

    @property
    def all_records(self) -> list[ConformerRecord]:
        return sorted(self.records, key=lambda item: (item.conf_id, item.label, item.source_file or ""))

    @property
    def usable_records(self) -> list[ConformerRecord]:
        return [record for record in self.all_records if record.is_usable]

    @property
    def failed_records(self) -> list[ConformerRecord]:
        return [record for record in self.all_records if not record.is_usable]

    def normalize_weights(self) -> None:
        usable = self.usable_records
        if not usable:
            return
        total = sum(record.effective_weight for record in usable)
        if total <= 0:
            weight = 1.0 / len(usable)
            for record in usable:
                record.boltzmann_weight = weight
            return
        for record in usable:
            record.boltzmann_weight = record.effective_weight / total


@dataclass
class CandidateIsomer:
    name: str
    directory: str
    collection: ConformerCollection = field(default_factory=ConformerCollection)
    averaged_shieldings: dict[str, dict[int, float]] = field(default_factory=dict)
    tms_referenced_shifts: dict[str, dict[int, float]] = field(default_factory=dict)
    atom_hybridizations: dict[int, str] = field(default_factory=dict)
    halogen_neighbor: dict[int, str] = field(default_factory=dict)
    unpaired_opt: list[OrcaFileInfo] = field(default_factory=list)
    unpaired_nmr: list[OrcaFileInfo] = field(default_factory=list)
    pairing_overrides: dict[str, str] = field(default_factory=dict)


@dataclass
class CandidateScore:
    candidate_name: str
    probabilities: dict[str, float] = field(default_factory=dict)
    mae_by_nucleus: dict[str, float] = field(default_factory=dict)
    rmse_by_nucleus: dict[str, float] = field(default_factory=dict)
    n_assignments_by_nucleus: dict[str, int] = field(default_factory=dict)
    joint_log_likelihood: float = float("-inf")
    joint_probability: float = 0.0
    shift_rows: list[ShiftRow] = field(default_factory=list)


@dataclass
class ScoringSet:
    """One set of candidate scores for a particular data mode."""
    mode: str  # "raw", "tms", "scaled"
    label: str
    candidate_scores: list[CandidateScore] = field(default_factory=list)
    formula: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def ranking(self) -> list[CandidateScore]:
        return sorted(self.candidate_scores, key=lambda item: item.joint_probability, reverse=True)


@dataclass
class LinearFit:
    """Per-isomer linear regression parameters."""
    candidate_name: str
    nucleus: str
    intercept: float
    slope: float
    r_squared: float


@dataclass
class DP4Result:
    candidate_scores: list[CandidateScore] = field(default_factory=list)
    nuclei: tuple[str, ...] = ()
    total_assignments: int = 0
    output_dir: str = ""
    scoring_sets: list[ScoringSet] = field(default_factory=list)
    linear_fits: list[LinearFit] = field(default_factory=list)
    tms_shielding_1h: float | None = None
    tms_shielding_13c: float | None = None
    reference_solvent: str | None = None
    reference_solvent_source: str = ""
    parameter_match: dict = field(default_factory=dict)
    summary_file: str | None = None
    report_file: str | None = None
    config_file: str | None = None
    generated_files: list[str] = field(default_factory=list)

    @property
    def ranking(self) -> list[CandidateScore]:
        return sorted(self.candidate_scores, key=lambda item: item.joint_probability, reverse=True)
