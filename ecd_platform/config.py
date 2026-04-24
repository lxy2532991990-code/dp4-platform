"""
配置模块 —— 所有可调参数集中管理，保证可追溯性。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict
import json
import os


# ── 枚举类型 ──────────────────────────────────────────────────────

class WeightingStrategy(Enum):
    """Boltzmann 权重的能量来源"""
    ELECTRONIC = "electronic"         # 裸电子能 (SCF energy)
    GIBBS = "gibbs"                   # Gibbs 自由能 (含热校正)
    SINGLE_POINT = "single_point"     # 高层级单点能校正后
    MANUAL = "manual"                 # 用户手动指定权重


class ImagFreqPolicy(Enum):
    """虚频处理策略"""
    STRICT = "strict"         # 任何 < 0 cm⁻¹ 均剔除
    TOLERANT = "tolerant"     # 仅 < threshold 才剔除
    MANUAL = "manual"         # 标记后由用户确认


class CDGauge(Enum):
    """CD 旋转强度的规范来源"""
    LENGTH = "length"         # transition electric dipole (length gauge)
    VELOCITY = "velocity"     # transition velocity dipole (velocity gauge)


class QMProgram(Enum):
    """量化输出文件来源程序"""
    AUTO = "auto"             # 依据文件头自动识别 (默认)
    ORCA = "orca"
    GAUSSIAN = "gaussian"


# ── 主配置 ─────────────────────────────────────────────────────────

@dataclass
class ECDConfig:
    """
    ECD 工作流的全部可配置参数。
    可通过 to_json / from_json 序列化，保证结果可复现。
    """

    # ── 输入路径 ──
    opt_dir: str = "opt_conf"
    ecd_dir: str = "ecd_conf"
    exp_file: Optional[str] = None
    weights_file: Optional[str] = None  # 若为 None 则自动查找

    # ── 量化程序 ──
    program: QMProgram = QMProgram.AUTO    # 计算输出文件来源程序

    # ── 构象匹配 ──
    filename_pattern: str = r"(?:conf|conformer|M)[-_]?(\d+)"
    auto_match: bool = True       # 是否自动匹配 opt ↔ ecd 文件

    # ── 虚频策略 ──
    imag_freq_policy: ImagFreqPolicy = ImagFreqPolicy.TOLERANT
    imag_freq_threshold: float = -10.0   # cm⁻¹，仅 TOLERANT 模式生效

    # ── 权重策略 ──
    weighting: WeightingStrategy = WeightingStrategy.GIBBS
    temperature: float = 298.15          # K，用于 Boltzmann 分布

    # ── CD 规范 ──
    cd_gauge: CDGauge = CDGauge.LENGTH

    # ── 光谱参数 ──
    sigma: float = 0.3           # Gaussian 展宽 / eV
    shift: float = 0.0           # 能量平移 / eV
    scale_factor: float = 1.0    # 计算谱缩放因子
    wavelength_range: tuple = (180, 450)   # nm
    n_points: int = 2000         # 波长网格点数

    # ── 实验谱处理 ──
    smooth_method: str = "fft"   # fft / savgol / none
    smooth_factor: float = 0.1   # FFT 截止比例 (0-1)
    savgol_window: int = 15      # Savitzky-Golay 窗口
    savgol_order: int = 3

    # ── 比较与评分 ──
    shift_scan_range: tuple = (-0.5, 0.5)  # eV
    shift_scan_step: float = 0.02          # eV
    similarity_metric: str = "cosine"      # cosine / pearson / tanimoto
    auto_invert: bool = True               # 自动测试对映体

    # ── 输出 ──
    output_dir: str = "ecd_results"
    save_csv: bool = True
    save_png: bool = True
    save_report: bool = True
    dpi: int = 300

    # ── 图例标签 ──
    plot_exp_label: str = "Experimental ECD"
    plot_calc_label: str = "Calculated ECD"
    plot_ent_label: str = "Calculated ECD (ent)"

    # ── 序列化 ──
    def to_dict(self) -> dict:
        d = {}
        for k, v in self.__dict__.items():
            if isinstance(v, Enum):
                d[k] = v.value
            elif isinstance(v, tuple):
                d[k] = list(v)
            else:
                d[k] = v
        return d

    def to_json(self, path: str):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, path: str) -> "ECDConfig":
        with open(path, 'r', encoding='utf-8') as f:
            d = json.load(f)
        # 恢复枚举
        enum_map = {
            'imag_freq_policy': ImagFreqPolicy,
            'weighting': WeightingStrategy,
            'cd_gauge': CDGauge,
            'program': QMProgram,
        }
        for k, enum_cls in enum_map.items():
            if k in d and isinstance(d[k], str):
                d[k] = enum_cls(d[k])
        # 恢复元组
        for k in ['wavelength_range', 'shift_scan_range']:
            if k in d and isinstance(d[k], list):
                d[k] = tuple(d[k])
        return cls(**d)

    def __repr__(self):
        lines = [f"ECDConfig("]
        for k, v in self.__dict__.items():
            lines.append(f"  {k} = {v!r},")
        lines.append(")")
        return "\n".join(lines)
