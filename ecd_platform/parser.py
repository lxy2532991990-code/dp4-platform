"""
ORCA 输出文件解析器 —— 增强版。
支持能量、频率、CD 旋转强度的独立提取，
每个环节的失败不影响其他环节（创新点2的基础）。
"""

import os
import re
import math
import numpy as np
from typing import Optional, Tuple, List
from .conformer import ConformerRecord, ConformerStatus
from .config import ECDConfig, CDGauge, ImagFreqPolicy


# ── 通用工具 ──────────────────────────────────────────────────────

def _read_file(filepath: str) -> Optional[str]:
    """多编码读取文件内容"""
    for enc in ['utf-8', 'gbk', 'latin-1', 'utf-16']:
        try:
            with open(filepath, 'r', encoding=enc, errors='ignore') as f:
                return f.read()
        except Exception:
            continue
    return None


# ── 能量提取 ──────────────────────────────────────────────────────

def extract_energies(content: str, record: ConformerRecord):
    """
    从 ORCA 输出中提取 SCF 能量和 Gibbs 自由能校正。
    失败时标记 record 但不终止。
    """
    # SCF / Total Energy
    scf_matches = re.findall(
        r'FINAL SINGLE POINT ENERGY\s+([-\d.]+)', content
    )
    if scf_matches:
        record.scf_energy = float(scf_matches[-1])  # 取最后一个（收敛后的值）
    else:
        # 回退：寻找 Total Energy
        m = re.search(r'Total Energy\s*:\s*([-\d.]+)\s*Eh', content)
        if m:
            record.scf_energy = float(m.group(1))

    # Gibbs free energy
    # ORCA 有两种常见表述："Final Gibbs free energy" 或 "Final Gibbs free enthalpy"
    m = re.search(
        r'Final Gibbs free energy\s*\.+\s*([-\d.]+)\s*Eh', content
    )
    if m:
        record.gibbs_energy = float(m.group(1))
    else:
        # 尝试 "Final Gibbs free enthalpy" 格式
        m = re.search(
            r'Final Gibbs free enthalpy\s*\.+\s*([-\d.]+)\s*Eh', content
        )
        if m:
            record.gibbs_energy = float(m.group(1))
        else:
            # 尝试 G(T) 格式
            m = re.search(r'G\s*=\s*([-\d.]+)\s*Eh', content)
            if m:
                record.gibbs_energy = float(m.group(1))

    # Gibbs correction (G - E_el)
    # 优先匹配 "G-E(el)" 行，这是最直接的吉布斯校正能
    m = re.search(
        r'G-E\(el\)\s*\.+\s*([-\d.]+)\s*Eh', content
    )
    if m:
        record.gibbs_correction = float(m.group(1))
    else:
        # 回退：尝试匹配 "Total entropy correction"
        m = re.search(
            r'Total entropy correction\s*\.+\s*([-\d.]+)\s*Eh', content
        )
        if m:
            record.gibbs_correction = float(m.group(1))
        else:
            # 再回退：尝试旧的 "Total correction" 格式
            m = re.search(
                r'Total correction\s*\.+\s*([-\d.]+)\s*Eh', content
            )
            if m:
                record.gibbs_correction = float(m.group(1))

    if record.scf_energy is None:
        record.status = ConformerStatus.NO_ENERGY
        record.add_error("[ORCA] Failed to extract SCF energy")



# ── 频率提取 ──────────────────────────────────────────────────────

def extract_frequencies(content: str, record: ConformerRecord, config: ECDConfig):
    """
    提取振动频率，检测虚频。
    根据 ImagFreqPolicy 决定是标记警告还是标记失败。
    """
    # ORCA 频率块
    freq_vals: List[float] = []
    for m in re.finditer(r'^\s*\d+:\s+([-\d.]+)\s+cm\*\*-1', content, re.MULTILINE):
        freq_vals.append(float(m.group(1)))

    if not freq_vals:
        # 回退格式
        block_match = re.search(
            r'VIBRATIONAL FREQUENCIES.*?(?=\n\n|\Z)', content, re.DOTALL
        )
        if block_match:
            for m in re.finditer(r'([-\d.]+)\s+cm\*?\*?-1', block_match.group()):
                freq_vals.append(float(m.group(1)))

    if not freq_vals:
        record.add_warning(
            "[ORCA] No vibrational frequencies found (may be ECD-only file)"
        )
        return

    record.frequencies = np.array(freq_vals)
    record.min_frequency = min(freq_vals)

    # 统计虚频
    if config.imag_freq_policy == ImagFreqPolicy.STRICT:
        imag = [f for f in freq_vals if f < 0]
    elif config.imag_freq_policy == ImagFreqPolicy.TOLERANT:
        imag = [f for f in freq_vals if f < config.imag_freq_threshold]
    else:  # MANUAL
        imag = [f for f in freq_vals if f < 0]

    record.n_imaginary = len(imag)

    if imag:
        if config.imag_freq_policy == ImagFreqPolicy.STRICT:
            record.status = ConformerStatus.IMAGINARY_FREQ
            record.add_error(
                f"[ORCA] Imaginary frequency detected (strict): "
                f"min = {min(imag):.1f} cm⁻¹ ({len(imag)} total)"
            )
        elif config.imag_freq_policy == ImagFreqPolicy.TOLERANT:
            # 仅超过阈值的才标记为失败
            record.status = ConformerStatus.IMAGINARY_FREQ
            record.add_error(
                f"[ORCA] Imaginary frequency below threshold "
                f"({config.imag_freq_threshold} cm⁻¹): "
                f"min = {min(imag):.1f} cm⁻¹"
            )
        else:
            record.status = ConformerStatus.SOFT_IMAGINARY_FREQ
            record.add_warning(
                f"[ORCA] Imaginary frequency detected (manual review): "
                f"min = {min(freq_vals):.1f} cm⁻¹"
            )

    # 小虚频仅警告
    soft_imag = [f for f in freq_vals if f < 0 and f >= config.imag_freq_threshold]
    if soft_imag and record.status == ConformerStatus.OK:
        record.status = ConformerStatus.SOFT_IMAGINARY_FREQ
        record.add_warning(
            f"[ORCA] Soft imaginary frequencies (above threshold): "
            f"{[f'{v:.1f}' for v in soft_imag]} cm⁻¹"
        )


# ── CD 数据提取 ───────────────────────────────────────────────────

def extract_cd_data(
    content: str,
    record: ConformerRecord,
    gauge: CDGauge = CDGauge.LENGTH
) -> bool:
    """
    提取 CD 旋转强度和跃迁能量。
    支持 length gauge 和 velocity gauge。
    返回 True 表示成功。
    """
    # 选择目标块标记
    if gauge == CDGauge.LENGTH:
        header = 'CD SPECTRUM VIA TRANSITION ELECTRIC DIPOLE MOMENTS'
    else:
        header = 'CD SPECTRUM VIA TRANSITION VELOCITY DIPOLE MOMENTS'

    # 回退标记列表
    headers = [header, 'CD SPECTRUM']
    start_idx = None
    for h in headers:
        m = re.search(re.escape(h), content)
        if m:
            start_idx = m.start()
            break

    if start_idx is None:
        record.add_error("[ORCA] No CD SPECTRUM block found")
        if record.status == ConformerStatus.OK or \
           record.status == ConformerStatus.SOFT_IMAGINARY_FREQ:
            record.status = ConformerStatus.NO_CD_DATA
        return False

    # 确定块的结束位置
    chunk = content[start_idx:start_idx + 10000]
    end_markers = [
        'CD SPECTRUM VIA TRANSITION VELOCITY',
        'ABSORPTION SPECTRUM',
        'Total run time',
        'PROPERTY CALCULATIONS',
    ]
    # 排除与自身相同的标记
    end_pos = len(chunk)
    for marker in end_markers:
        if marker in header:
            continue
        idx = chunk.find(marker)
        if idx > 50:  # 必须至少有一些数据行
            end_pos = min(end_pos, idx)

    block = chunk[:end_pos]

    # 提取数据行（含 '->' 的行）
    energies = []
    R_values = []

    for line in block.splitlines():
        if '->' not in line:
            continue
        if not re.search(r'\d', line):
            continue
        if len(line.strip()) < 10:
            continue

        # 提取所有浮点数
        floats = re.findall(r'-?\d+\.\d+(?:[eE][+\-]?\d+)?', line)
        floats = [float(x) for x in floats]

        if len(floats) < 2:
            continue

        # 识别能量（eV 范围 0.5-15）
        energy = None
        for f in floats:
            if 0.1 < abs(f) < 30:
                energy = f
                break
        if energy is None:
            energy = floats[0]

        # R 值通常在第 4 列（index 3）
        R = floats[3] if len(floats) >= 4 else floats[-1]

        if math.isfinite(energy) and math.isfinite(R):
            energies.append(energy)
            R_values.append(R)

    if not energies:
        record.add_error("[ORCA] CD block found but no valid transitions parsed")
        if record.status in (ConformerStatus.OK, ConformerStatus.SOFT_IMAGINARY_FREQ):
            record.status = ConformerStatus.NO_CD_DATA
        return False

    record.transition_energies = np.array(energies)
    record.rotatory_strengths = np.array(R_values)
    record.n_transitions = len(energies)
    return True


# ── 主解析函数 ────────────────────────────────────────────────────

def parse_opt_file(filepath: str, record: ConformerRecord, config: ECDConfig):
    """解析 OPT/FREQ 文件，提取能量和频率"""
    content = _read_file(filepath)
    if content is None:
        record.status = ConformerStatus.PARSE_FAILED
        record.add_error(f"[ORCA] Cannot read file: {filepath}")
        return

    extract_energies(content, record)
    extract_frequencies(content, record, config)


def parse_ecd_file(filepath: str, record: ConformerRecord, config: ECDConfig):
    """解析 ECD 计算文件，提取 CD 数据（以及可能的能量）"""
    content = _read_file(filepath)
    if content is None:
        record.status = ConformerStatus.PARSE_FAILED
        record.add_error(f"[ORCA] Cannot read file: {filepath}")
        return

    # 尝试提取 CD 数据
    extract_cd_data(content, record, config.cd_gauge)

    # 如果 opt 文件中没有能量，尝试从 ecd 文件补充
    if record.scf_energy is None:
        extract_energies(content, record)
        if record.scf_energy is not None:
            record.add_warning("[ORCA] Energy extracted from ECD file (not OPT)")


def parse_single_file(filepath: str, record: ConformerRecord, config: ECDConfig):
    """
    当 opt 和 ecd 在同一个文件中时的解析入口。
    """
    content = _read_file(filepath)
    if content is None:
        record.status = ConformerStatus.PARSE_FAILED
        record.add_error(f"[ORCA] Cannot read file: {filepath}")
        return

    extract_energies(content, record)
    extract_frequencies(content, record, config)
    extract_cd_data(content, record, config.cd_gauge)
