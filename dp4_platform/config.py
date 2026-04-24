"""Configuration types for the standalone DP4 project."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Literal

from .solvent import normalize_reference_solvent


class WeightingStrategy(Enum):
    ELECTRONIC = "electronic"
    GIBBS = "gibbs"
    SINGLE_POINT = "single_point"
    MANUAL = "manual"


class ImagFreqPolicy(Enum):
    STRICT = "strict"
    TOLERANT = "tolerant"
    MANUAL = "manual"


class ScalingMode(Enum):
    PARAMETER_TABLE = "parameter_table"
    LINEAR = "linear"
    IDENTITY = "identity"


class DataKind(Enum):
    """What kind of NMR data the user's output files contain."""
    RAW_SHIELDING = "raw_shielding"
    TMS_REFERENCED = "tms_referenced"
    CHEMICAL_SHIFT = "chemical_shift"
    AUTO = "auto"


def _normalize_nuclei(values: Iterable[str]) -> tuple[str, ...]:
    seen = []
    for raw in values:
        val = str(raw).strip().upper().replace(" ", "")
        if val in {"H", "1H"}:
            key = "1H"
        elif val in {"C", "13C"}:
            key = "13C"
        else:
            key = str(raw).strip()
        if key and key not in seen:
            seen.append(key)
    return tuple(seen)


@dataclass
class DP4Config:
    candidates_root: str = "candidates"
    candidate_paths: dict[str, str] = field(default_factory=dict)
    pairing_overrides: dict[str, dict[str, str]] = field(default_factory=dict)
    program_mode: Literal["auto", "orca", "gaussian"] = "auto"
    auto_pair_strategy: Literal["conf_id", "filename", "manual"] = "conf_id"
    exp_nmr_file: str = "experimental_assignments.csv"
    nmr_dirname: str | None = None
    parameter_table: str | None = None
    nuclei: tuple[str, ...] = field(default_factory=lambda: ("1H", "13C"))
    filename_pattern: str = r"(?:conf|conformer|M)[-_]?(\d+)"
    weighting: WeightingStrategy = WeightingStrategy.GIBBS
    temperature: float = 298.15
    imag_freq_policy: ImagFreqPolicy = ImagFreqPolicy.TOLERANT
    imag_freq_threshold: float = -10.0
    scaling_mode: ScalingMode = ScalingMode.PARAMETER_TABLE
    data_kind: DataKind = DataKind.AUTO
    tms_shielding_13c: float | None = None
    tms_shielding_1h: float | None = None
    tms_shielding_file: str | None = None
    reference_solvent: str | None = None
    recursive: bool = True
    file_extensions: tuple[str, ...] = field(default_factory=lambda: (".out", ".log", ".txt"))
    output_dir: str = "dp4_results"
    save_config: bool = True

    def __post_init__(self) -> None:
        self.nuclei = _normalize_nuclei(self.nuclei)
        self.file_extensions = tuple(ext.lower() for ext in self.file_extensions)
        self.candidate_paths = {str(name): str(path) for name, path in self.candidate_paths.items()}
        normalized_overrides: dict[str, dict[str, str]] = {}
        for candidate_name, overrides in self.pairing_overrides.items():
            normalized_overrides[str(candidate_name)] = {str(opt): str(nmr) for opt, nmr in overrides.items()}
        self.pairing_overrides = normalized_overrides
        if self.program_mode not in {"auto", "orca", "gaussian"}:
            raise ValueError(f"Unsupported program_mode: {self.program_mode}")
        if self.auto_pair_strategy not in {"conf_id", "filename", "manual"}:
            raise ValueError(f"Unsupported auto_pair_strategy: {self.auto_pair_strategy}")
        self.reference_solvent = normalize_reference_solvent(self.reference_solvent)

    def to_dict(self) -> dict:
        data = {}
        for key, value in self.__dict__.items():
            if isinstance(value, Enum):
                data[key] = value.value
            elif isinstance(value, tuple):
                data[key] = list(value)
            else:
                data[key] = value
        return data

    def to_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "DP4Config":
        data = dict(data)
        enum_map = {
            "weighting": WeightingStrategy,
            "imag_freq_policy": ImagFreqPolicy,
            "scaling_mode": ScalingMode,
            "data_kind": DataKind,
        }
        for key, enum_cls in enum_map.items():
            if key in data and isinstance(data[key], str):
                data[key] = enum_cls(data[key])
        if "nuclei" in data:
            data["nuclei"] = tuple(data["nuclei"])
        if "file_extensions" in data:
            data["file_extensions"] = tuple(data["file_extensions"])
        if "candidate_paths" not in data:
            data["candidate_paths"] = {}
        if "pairing_overrides" not in data:
            data["pairing_overrides"] = {}
        return cls(**data)

    @classmethod
    def from_json(cls, path: str) -> "DP4Config":
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return cls.from_dict(data)
