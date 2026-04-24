"""
实验谱处理模块 —— 支持多种格式读取、平滑、归一化。
"""

import os
import re
import numpy as np
from typing import Optional, Tuple


def read_experimental_data(
    filepath: str
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """
    读取实验 ECD 数据。
    支持格式：
      - 简单 CSV (wavelength, intensity)
      - 带 XYDATA 标记的仪器导出格式
      - Tab 分隔的 txt 文件
      - JCAMP-DX 格式（基础支持）
    
    Returns:
        (wavelengths_nm, intensities) 或 (None, None)
    """
    if not os.path.exists(filepath):
        return None, None

    content = _read_with_fallback(filepath)
    if content is None:
        return None, None

    # 根据内容特征选择解析策略
    if 'XYDATA' in content:
        return _parse_xydata(content)
    elif '##XYDATA' in content or '##TITLE' in content:
        return _parse_jcamp(content)
    else:
        return _parse_csv_or_tsv(content)


def _read_with_fallback(filepath: str) -> Optional[str]:
    for enc in ['utf-8', 'gbk', 'latin-1', 'utf-16']:
        try:
            with open(filepath, 'r', encoding=enc, errors='ignore') as f:
                return f.read()
        except Exception:
            continue
    return None


def _parse_csv_or_tsv(content: str) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """解析简单的 CSV 或 TSV 格式"""
    wavelengths, intensities = [], []

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('Wavelength'):
            continue

        # 尝试逗号分隔
        sep = ',' if ',' in line else '\t' if '\t' in line else None
        if sep:
            parts = line.split(sep)
        else:
            parts = line.split()

        if len(parts) >= 2:
            try:
                wl = float(parts[0].strip())
                inten = float(parts[1].strip())
                wavelengths.append(wl)
                intensities.append(inten)
            except ValueError:
                continue

    if not wavelengths:
        return None, None

    wl = np.array(wavelengths)
    it = np.array(intensities)

    # 确保升序
    if len(wl) > 1 and wl[0] > wl[-1]:
        wl = wl[::-1]
        it = it[::-1]

    return wl, it


def _parse_xydata(content: str) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """解析带 XYDATA 标记的格式"""
    wavelengths, intensities = [], []
    in_data = False

    for line in content.splitlines():
        if 'XYDATA' in line:
            in_data = True
            continue
        if not in_data:
            continue
        if '##### Extended' in line or '[Comments]' in line:
            break

        line = line.strip()
        if not line:
            continue
        parts = line.split(',')
        if len(parts) >= 2:
            try:
                wavelengths.append(float(parts[0]))
                intensities.append(float(parts[1]))
            except ValueError:
                continue

    if not wavelengths:
        return None, None

    wl = np.array(wavelengths)
    it = np.array(intensities)
    if len(wl) > 1 and wl[0] > wl[-1]:
        wl = wl[::-1]
        it = it[::-1]
    return wl, it


def _parse_jcamp(content: str) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """基础 JCAMP-DX 解析"""
    wavelengths, intensities = [], []
    in_data = False

    for line in content.splitlines():
        if '##XYDATA' in line or '##XYPOINTS' in line:
            in_data = True
            continue
        if line.startswith('##END'):
            break
        if not in_data:
            continue

        parts = re.split(r'[,\s]+', line.strip())
        if len(parts) >= 2:
            try:
                wavelengths.append(float(parts[0]))
                intensities.append(float(parts[1]))
            except ValueError:
                continue

    if not wavelengths:
        return None, None
    return np.array(wavelengths), np.array(intensities)


# ── 平滑 ──

def fft_smooth(y: np.ndarray, cutoff_ratio: float = 0.1) -> np.ndarray:
    """
    FFT 低通滤波平滑。
    cutoff_ratio: 保留的频率比例 (0-1)，越小越平滑。
    """
    n = len(y)
    Y = np.fft.rfft(y)
    cutoff = max(1, int(len(Y) * cutoff_ratio))
    Y[cutoff:] = 0
    return np.fft.irfft(Y, n=n)


def savgol_smooth(y: np.ndarray, window: int = 15, order: int = 3) -> np.ndarray:
    """
    Savitzky-Golay 平滑（纯 numpy 实现，不依赖 scipy）。
    """
    if window % 2 == 0:
        window += 1
    if window > len(y):
        window = len(y) if len(y) % 2 == 1 else len(y) - 1
    if order >= window:
        order = window - 1

    half = window // 2
    # 构造 Vandermonde 矩阵
    x = np.arange(-half, half + 1, dtype=float)
    A = np.vander(x, N=order + 1, increasing=True)
    # 最小二乘拟合系数
    coeffs = np.linalg.pinv(A)
    # 取零阶导数系数（平滑）
    conv = coeffs[0]

    # 边界扩展
    y_ext = np.concatenate([y[half:0:-1], y, y[-2:-half - 2:-1]])
    result = np.convolve(y_ext, conv, mode='valid')

    # 长度修正
    if len(result) > len(y):
        result = result[:len(y)]
    elif len(result) < len(y):
        result = np.concatenate([result, y[len(result):]])

    return result


def smooth_spectrum(
    y: np.ndarray,
    method: str = "fft",
    fft_cutoff: float = 0.1,
    sg_window: int = 15,
    sg_order: int = 3
) -> np.ndarray:
    """统一平滑接口"""
    if method == "fft":
        return fft_smooth(y, fft_cutoff)
    elif method == "savgol":
        return savgol_smooth(y, sg_window, sg_order)
    else:
        return y
