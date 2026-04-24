"""
光谱生成模块 —— 创新点4：从 ORCA 输出直接到最终 ECD 图。
完整实现 Gaussian 展宽、Boltzmann 加权、归一化，无需 SpecDis。
"""

import numpy as np
from typing import Optional, Tuple, List, Dict
from .conformer import ConformerRecord, ConformerCollection


def generate_wavelength_grid(
    wl_min: float = 180,
    wl_max: float = 450,
    n_points: int = 2000
) -> Tuple[np.ndarray, np.ndarray]:
    """
    生成等间距波长网格及对应的能量网格。
    返回 (wavelength_nm, energy_eV)
    """
    wl = np.linspace(wl_min, wl_max, n_points)
    ev = 1239.84193 / wl  # nm → eV
    return wl, ev


def gaussian_broadening(
    energy_grid: np.ndarray,
    transition_energies: np.ndarray,
    rotatory_strengths: np.ndarray,
    sigma: float = 0.3,
    shift: float = 0.0
) -> np.ndarray:
    """
    对单个构象的跃迁数据施加 Gaussian 展宽。
    
    Parameters:
        energy_grid: 能量网格 (eV)
        transition_energies: 跃迁能量 (eV)
        rotatory_strengths: 旋转强度 R
        sigma: Gaussian 宽度 (eV)
        shift: 能量平移 (eV)
    
    Returns:
        展宽后的 CD 强度数组
    """
    spectrum = np.zeros_like(energy_grid)
    shifted_grid = energy_grid - shift  # 等价于对跃迁平移 +shift

    for E_i, R_i in zip(transition_energies, rotatory_strengths):
        gauss = np.exp(-((shifted_grid - E_i) ** 2) / (2 * sigma ** 2))
        gauss /= np.sqrt(2 * np.pi) * sigma
        spectrum += R_i * gauss

    return spectrum


def compute_weighted_spectrum(
    collection: ConformerCollection,
    wavelength_grid: np.ndarray,
    energy_grid: np.ndarray,
    sigma: float = 0.3,
    shift: float = 0.0
) -> Tuple[np.ndarray, Dict[int, np.ndarray]]:
    """
    计算 Boltzmann 加权平均 ECD 谱。
    
    Returns:
        (weighted_spectrum, individual_spectra_dict)
        individual_spectra_dict: {conf_id: spectrum} 便于调试
    """
    weighted_spectrum = np.zeros_like(energy_grid)
    individual_spectra = {}

    usable = collection.usable_records
    if not usable:
        return weighted_spectrum, individual_spectra

    # 确保权重已归一化
    total_w = sum(r.effective_weight for r in usable)
    if total_w <= 0:
        return weighted_spectrum, individual_spectra

    for rec in usable:
        if rec.transition_energies is None or rec.rotatory_strengths is None:
            continue

        w = rec.effective_weight / total_w
        spec = gaussian_broadening(
            energy_grid,
            rec.transition_energies,
            rec.rotatory_strengths,
            sigma=sigma,
            shift=shift
        )
        individual_spectra[rec.conf_id] = spec
        weighted_spectrum += w * spec

    return weighted_spectrum, individual_spectra


def normalize_spectrum(
    spectrum: np.ndarray,
    scale_factor: float = 1.0
) -> np.ndarray:
    """归一化后乘以缩放因子"""
    max_abs = np.max(np.abs(spectrum))
    if max_abs == 0:
        return spectrum
    return (spectrum / max_abs) * scale_factor


def invert_spectrum(spectrum: np.ndarray) -> np.ndarray:
    """生成对映体谱（倒置）"""
    return -spectrum


def convert_ev_to_nm(energy_ev: np.ndarray) -> np.ndarray:
    """eV → nm"""
    return 1239.84193 / energy_ev


def convert_nm_to_ev(wavelength_nm: np.ndarray) -> np.ndarray:
    """nm → eV"""
    return 1239.84193 / wavelength_nm
