"""
构象级状态机 —— 创新点2：per-conformer fault isolation。
每个构象独立标记状态，坏构象自动隔离，好构象继续参与加权谱计算。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any
import numpy as np


class ConformerStatus(Enum):
    """构象状态枚举"""
    OK = "ok"
    NO_OPT_FILE = "no_opt_file"
    NO_ECD_FILE = "no_ecd_file"
    NO_ENERGY = "no_energy"
    NO_FREQ = "no_freq"
    IMAGINARY_FREQ = "imaginary_freq"        # 严格模式下被剔除
    SOFT_IMAGINARY_FREQ = "soft_imag_freq"   # 容差模式下保留但标记
    NO_CD_DATA = "no_cd_data"
    PARSE_FAILED = "parse_failed"
    DUPLICATE = "duplicate"
    MANUAL_EXCLUDED = "manual_excluded"
    WEIGHT_ZERO = "weight_zero"


@dataclass
class ConformerRecord:
    """
    单个构象的完整记录。
    包含原始数据、处理状态、权重和异常信息。
    """
    conf_id: int
    label: str = ""

    # ── 文件路径 ──
    opt_file: Optional[str] = None
    ecd_file: Optional[str] = None

    # ── 状态 ──
    status: ConformerStatus = ConformerStatus.OK
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    # ── 能量 ──
    scf_energy: Optional[float] = None           # Hartree
    gibbs_correction: Optional[float] = None     # Hartree
    gibbs_energy: Optional[float] = None         # Hartree
    sp_energy: Optional[float] = None            # 高层级单点能
    relative_energy_kcal: Optional[float] = None # 相对能量 kcal/mol

    # ── 权重 ──
    boltzmann_weight: float = 0.0
    manual_weight: Optional[float] = None

    # ── 频率 ──
    frequencies: Optional[np.ndarray] = None
    min_frequency: Optional[float] = None
    n_imaginary: int = 0

    # ── CD 数据 ──
    transition_energies: Optional[np.ndarray] = None   # eV
    rotatory_strengths: Optional[np.ndarray] = None    # R (length or velocity)
    n_transitions: int = 0

    # ── 构象指纹（用于去重）──
    coords_hash: Optional[str] = None

    @property
    def is_usable(self) -> bool:
        """该构象是否可参与最终光谱计算"""
        return self.status in (
            ConformerStatus.OK,
            ConformerStatus.SOFT_IMAGINARY_FREQ,
        )

    @property
    def effective_weight(self) -> float:
        if self.manual_weight is not None:
            return self.manual_weight
        return self.boltzmann_weight

    def add_warning(self, msg: str):
        if msg not in self.warnings:
            self.warnings.append(msg)

    def add_error(self, msg: str):
        if msg not in self.errors:
            self.errors.append(msg)

    def summary(self) -> str:
        parts = [f"Conf-{self.conf_id:>3d}  status={self.status.value:<18s}"]
        if self.relative_energy_kcal is not None:
            parts.append(f"ΔE={self.relative_energy_kcal:6.2f} kcal/mol")
        parts.append(f"weight={self.effective_weight:.4f}")
        if self.n_transitions:
            parts.append(f"transitions={self.n_transitions}")
        if self.n_imaginary:
            parts.append(f"imag_freq={self.n_imaginary}")
        if self.warnings:
            parts.append(f"warnings={len(self.warnings)}")
        return "  ".join(parts)


class ConformerCollection:
    """
    构象集合管理器。
    负责：状态统计、权重归一化、可用构象筛选。
    """

    def __init__(self):
        self._records: Dict[int, ConformerRecord] = {}

    def add(self, record: ConformerRecord):
        self._records[record.conf_id] = record

    def get(self, conf_id: int) -> Optional[ConformerRecord]:
        return self._records.get(conf_id)

    @property
    def all_records(self) -> List[ConformerRecord]:
        return sorted(self._records.values(), key=lambda r: r.conf_id)

    @property
    def usable_records(self) -> List[ConformerRecord]:
        return [r for r in self.all_records if r.is_usable]

    @property
    def failed_records(self) -> List[ConformerRecord]:
        return [r for r in self.all_records if not r.is_usable]

    def normalize_weights(self):
        """对可用构象的权重归一化（确保 sum = 1）"""
        usable = self.usable_records
        if not usable:
            return
        total = sum(r.effective_weight for r in usable)
        if total <= 0:
            # 均匀分配
            n = len(usable)
            for r in usable:
                r.boltzmann_weight = 1.0 / n
        else:
            for r in usable:
                r.boltzmann_weight = r.effective_weight / total

    def status_summary(self) -> Dict[str, int]:
        counts = {}
        for r in self.all_records:
            s = r.status.value
            counts[s] = counts.get(s, 0) + 1
        return counts

    def report_text(self) -> str:
        """生成纯文本异常报告"""
        lines = []
        lines.append("=" * 72)
        lines.append("CONFORMER STATUS REPORT")
        lines.append("=" * 72)

        summary = self.status_summary()
        lines.append(f"Total conformers: {len(self._records)}")
        lines.append(f"Usable: {len(self.usable_records)}")
        lines.append(f"Failed: {len(self.failed_records)}")
        lines.append("")
        lines.append("Status breakdown:")
        for status, count in sorted(summary.items()):
            lines.append(f"  {status:<25s} : {count}")

        lines.append("")
        lines.append("-" * 72)
        lines.append("DETAILS")
        lines.append("-" * 72)

        for r in self.all_records:
            lines.append(r.summary())
            for w in r.warnings:
                lines.append(f"    ⚠ {w}")
            for e in r.errors:
                lines.append(f"    ✗ {e}")

        lines.append("=" * 72)
        return "\n".join(lines)
