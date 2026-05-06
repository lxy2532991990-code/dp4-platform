#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ECD-Platform GUI v1.2 (PyQt6)
- 构象匹配可视化编辑器
- 所有 v1.1 功能
- 增强的构象管理界面
"""

import os
import re
import sys
import numpy as np

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QSlider, QComboBox, QPushButton,
    QFileDialog, QScrollArea, QFrame, QProgressBar,
    QAbstractSpinBox, QDoubleSpinBox, QSpinBox, QSizePolicy, QToolBar,
    QScrollBar, QCheckBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QDialog, QDialogButtonBox, QMessageBox,
    QAbstractItemView, QGroupBox, QSplitter, QTextEdit
)
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPalette, QAction, QFont, QLinearGradient, QPainter, QPainterPath, QRegion

import matplotlib
matplotlib.use("QtAgg")
matplotlib.rcParams["font.family"] = ["Times New Roman", "Times", "DejaVu Serif"]
matplotlib.rcParams["mathtext.fontset"] = "stix"
matplotlib.rcParams["axes.unicode_minus"] = False

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure

from .config import ECDConfig, WeightingStrategy, ImagFreqPolicy, CDGauge, QMProgram
from .matcher import ConformerMatcher, _glob_orca_outputs
from .parser_dispatch import (
    parse_opt_file,
    parse_ecd_file,
    parse_single_file,
    same_output_file,
)
from .energy import compute_boltzmann_weights, load_manual_weights
from .spectrum import generate_wavelength_grid, compute_weighted_spectrum
from .experimental import read_experimental_data, smooth_spectrum
from .comparison import shift_scan, compare_spectra
from .report import (
    plot_shift_scan,
    save_spectrum_csv, generate_full_report,
)

PREVIEW_PTS = 500
EXPORT_PTS = 2000

PLOT_FIGSIZE = (10, 6)
PLOT_DPI_PREVIEW = 100
PLOT_DPI_EXPORT = 300
PLOT_BG = "#FFFFFF"


def _style_asset_url(filename):
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "assets", filename)).replace("\\", "/")


STYLESHEET = """
* { font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif; }

QMainWindow {
    background-color: #F5F6FA;
}

QWidget#ecd_toolbar_shell {
    background-color: #F5F6FA;
}

QToolBar {
    background-color: #FFFFFF;
    border: 1px solid #E2E5EB;
    border-radius: 8px;
    spacing: 8px;
    padding: 8px 12px;
}
QToolBar QPushButton {
    border: 1px solid #D0D5DD;
    border-radius: 8px;
    padding: 7px 16px;
    font-size: 12px;
    color: #344054;
    background-color: #FFFFFF;
    min-height: 32px;
}
QToolBar QPushButton:hover {
    background-color: #F0F4FF;
    border-color: #4A7BF7;
}
QToolBar QPushButton#btn_load {
    background-color: #4A7BF7;
    color: white;
    border: 1px solid #3B6CE6;
    font-weight: bold;
}
QToolBar QPushButton#btn_load:hover {
    background-color: #3B6CE6;
}
QToolBar QPushButton#btn_editor {
    background-color: #8B5CF6;
    color: #FFFFFF;
    border: 1px solid #7C3AED;
}
QToolBar QPushButton#btn_editor:hover {
    background-color: #7C3AED;
    border-color: #6D28D9;
}
QToolBar QPushButton#btn_editor:disabled {
    background-color: #DDD6FE;
    color: #F5F3FF;
    border-color: #C4B5FD;
}
QToolBar QPushButton#btn_export {
    background-color: #ECFDF5;
    color: #059669;
    border: 1px solid #A7F3D0;
}
QToolBar QPushButton#btn_export:hover {
    background-color: #D1FAE5;
}

QScrollArea#sidebar_scroll {
    background-color: #F5F6FA;
    border: none;
    border-radius: 8px;
}
QWidget#sidebar_scroll_viewport {
    background-color: #F5F6FA;
    border: none;
    border-radius: 8px;
}
QWidget#sidebar_inner {
    background-color: #F5F6FA;
}

QFrame#section_card[altTone="0"] {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
}
QFrame#section_card[altTone="1"] {
    background-color: #EEF4FF;
    border: 1px solid #D6E2F5;
    border-radius: 8px;
}
QFrame#section_accent {
    border: none;
    border-radius: 1px;
    min-width: 3px;
    max-width: 3px;
    min-height: 14px;
    max-height: 14px;
}
QLabel#section_hdr {
    background-color: transparent;
    color: #475569;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 0 0 2px 0;
}
QLabel {
    background-color: transparent;
    border: none;
    color: #374151;
    font-size: 12px;
}
QLabel#field_label {
    background-color: transparent;
    color: #6B7280;
    font-size: 11px;
}
QLabel#value_readout {
    background-color: transparent;
    color: #4A7BF7;
    font-size: 11px;
    font-weight: 600;
}
QLabel#hint_label {
    background-color: transparent;
    color: #9CA3AF;
    font-size: 10px;
}

QLineEdit, QDoubleSpinBox, QSpinBox {
    background-color: #F9FAFB;
    border: 1px solid #D1D5DB;
    border-radius: 8px;
    color: #1F2937;
    padding: 3px 8px;
    font-size: 12px;
    min-height: 24px;
}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus {
    border-color: #4A7BF7;
    background-color: #FFFFFF;
}
QComboBox {
    background-color: #F9FAFB;
    border: 1px solid #D1D5DB;
    border-radius: 20px;
    color: #1F2937;
    padding: 7px 40px 7px 16px;
    font-size: 12px;
    min-height: 26px;
    selection-background-color: #E8F0FE;
    selection-color: #111827;
}
QComboBox:hover {
    border-color: #B8C0CC;
    background-color: #FFFFFF;
}
QComboBox:focus, QComboBox:on {
    border-color: #4A7BF7;
    background-color: #FFFFFF;
}
QComboBox::drop-down {
    border: none;
    width: 38px;
}
QComboBox::down-arrow {
    image: url("__COMBO_ARROW_DOWN__");
    width: 18px;
    height: 18px;
    margin-right: 14px;
}
QComboBox::down-arrow:on {
    image: url("__COMBO_ARROW_UP__");
}
QComboBox QAbstractItemView, QComboBox QListView {
    background-color: #FFFFFF;
    border: 12px solid #FFFFFF;
    border-radius: 28px;
    padding: 2px;
    color: #1F2937;
    outline: 0;
    selection-background-color: #E8F0FE;
    selection-color: #111827;
}
QComboBox QAbstractItemView::item, QComboBox QListView::item {
    min-height: 44px;
    padding: 8px 22px;
    border-radius: 20px;
    margin: 4px;
}
QComboBox QAbstractItemView::item:hover, QComboBox QListView::item:hover {
    background-color: #F4F7FF;
    color: #111827;
}
QComboBox QAbstractItemView::item:selected, QComboBox QListView::item:selected {
    background-color: #E8F0FE;
    color: #111827;
    font-weight: 600;
}

QCheckBox {
    color: #374151;
    font-size: 12px;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
}

QSlider::groove:horizontal {
    height: 2px;
    background: #D6DEE8;
    border-radius: 1px;
}
QSlider::handle:horizontal {
    width: 12px;
    height: 12px;
    margin: -5px 0;
    background: #4A7BF7;
    border: 1px solid #F8FAFC;
    border-radius: 6px;
}
QSlider::handle:horizontal:hover {
    background: #3B6CE6;
}
QSlider::add-page:horizontal {
    background: #D6DEE8;
    border-radius: 1px;
}
QSlider::sub-page:horizontal {
    background: #D6DEE8;
    border-radius: 1px;
}

QPushButton#btn_browse {
    background-color: #F3F4F6;
    color: #6B7280;
    border: 1px solid #D1D5DB;
    border-radius: 8px;
    min-width: 28px;
    max-width: 28px;
    min-height: 24px;
    font-size: 12px;
    padding: 0;
}
QPushButton#btn_browse:hover {
    background-color: #E5E7EB;
}

QWidget#external_spin {
    background-color: transparent;
}
QPushButton#spin_step_button {
    background-color: #FFFFFF;
    color: #475569;
    border: 1px solid #D1D5DB;
    border-radius: 6px;
    padding: 0;
    font-size: 10px;
    font-weight: 700;
    min-width: 24px;
    max-width: 24px;
    min-height: 15px;
    max-height: 15px;
}
QPushButton#spin_step_button:hover {
    background-color: #F0F4FF;
    border-color: #4A7BF7;
}
QPushButton#spin_step_button:pressed {
    background-color: #E8F0FF;
}
QPushButton#spin_step_button:disabled {
    background-color: #F3F4F6;
    color: #CBD5E1;
    border-color: #E2E8F0;
}

QProgressBar {
    background-color: #E5E7EB;
    border: none;
    border-radius: 2px;
    max-height: 3px;
}
QProgressBar::chunk {
    background-color: #4A7BF7;
    border-radius: 2px;
}

QStatusBar {
    background-color: #FFFFFF;
    color: #6B7280;
    font-size: 11px;
    border-top: 1px solid #E2E5EB;
    padding: 2px 12px;
}

QScrollBar:vertical {
    background: transparent;
    width: 14px;
    border: none;
    border-radius: 7px;
    padding: 2px 0;
}
QScrollBar::handle:vertical {
    background: #C4C4C4;
    border-radius: 5px;
    min-height: 40px;
    margin: 0 3px;
}
QScrollBar::handle:vertical:hover {
    background: #9CA3AF;
}
QScrollBar::add-line:vertical {
    height: 0;
    subcontrol-position: bottom;
}
QScrollBar::sub-line:vertical {
    height: 0;
    subcontrol-position: top;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}

QWidget#plot_toolbar {
    background-color: #FFFFFF;
    border: 1px solid #E2E5EB;
    border-radius: 8px;
}

QFrame#plot_card {
    background-color: #FFFFFF;
    border: 1px solid #E2E5EB;
    border-radius: 8px;
}

QWidget#plot_host {
    background-color: #FFFFFF;
}

/* 构象编辑器表格样式 */
QTableWidget {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    gridline-color: #E2E8F0;
    font-size: 11px;
}
QTableWidget::item {
    padding: 2px 4px;
}
QTableWidget::item:selected {
    background-color: #EFF6FF;
    color: #1D4ED8;
}
QHeaderView::section {
    background-color: #F8FAFC;
    color: #475569;
    font-weight: 600;
    font-size: 10px;
    padding: 4px 8px;
    border: none;
    border-right: 1px solid #E2E8F0;
    border-bottom: 1px solid #E2E8F0;
}
"""
STYLESHEET = STYLESHEET.replace("__COMBO_ARROW_DOWN__", _style_asset_url("chevron-down.svg"))
STYLESHEET = STYLESHEET.replace("__COMBO_ARROW_UP__", _style_asset_url("chevron-up.svg"))


def nm_to_ev(x):
    return 1239.84 / x


def ev_to_nm(x):
    return 1239.84 / x


def fmt_num(value):
    return f"{value:.2f}".rstrip("0").rstrip(".")


def italicize_rs_outside_math(text: str) -> str:
    if not text:
        return text

    parts = re.split(r'(\$.*?\$)', text)

    def repl(match):
        chunk = match.group(1)
        return ''.join(f'${ch}$' for ch in chunk)

    out = []
    for part in parts:
        if not part:
            continue
        if part.startswith("$") and part.endswith("$"):
            out.append(part)
        else:
            new_part = re.sub(r'(?<![A-Za-z])([RS]+)(?![A-Za-z])', repl, part)
            out.append(new_part)
    return ''.join(out)


def normalize_legend_text(text: str, fallback: str) -> str:
    raw = (text or "").strip()
    if not raw:
        raw = fallback
    return italicize_rs_outside_math(raw)


def build_similarity_text(spec, wl, cfg, exp_wl=None, exp_spec=None):
    if exp_wl is None or exp_spec is None:
        return ""

    ma = np.max(np.abs(spec))
    nm_spec = spec / ma * cfg.scale_factor if ma > 0 else spec
    sn = compare_spectra(nm_spec, wl, exp_spec, exp_wl, cfg.similarity_metric)
    si = compare_spectra(-nm_spec, wl, exp_spec, exp_wl, cfg.similarity_metric)
    best = max(sn, si)
    tag = "enantiomer" if si > sn else "original"
    return f"Similarity = {best:.3f} ({tag})"


def build_param_line(cfg):
    parts = [
        f"sigma = {fmt_num(cfg.sigma)} eV",
        f"shift = {fmt_num(cfg.shift)} eV",
        f"scale = {fmt_num(cfg.scale_factor)}",
    ]

    if cfg.smooth_method == "fft":
        parts.append(f"smooth (FFT) = {fmt_num(cfg.smooth_factor)}")
    elif cfg.smooth_method == "savgol":
        parts.append(f"smooth (SG) = {fmt_num(cfg.savgol_window)} / {fmt_num(cfg.savgol_order)}")

    return ", ".join(parts)


def compute_top_margin(show_title, show_params, show_top_axis):
    count = int(show_title) + int(show_params) + int(show_top_axis)
    if count == 3:
        return 0.82
    if count == 2:
        return 0.86
    if count == 1:
        return 0.91
    return 0.96


def clear_plot_extras(ax):
    fig = ax.figure

    if hasattr(ax, "_top_secondary_axis") and ax._top_secondary_axis is not None:
        try:
            ax._top_secondary_axis.remove()
        except Exception:
            pass
        ax._top_secondary_axis = None

    if getattr(fig, "_suptitle", None) is not None:
        try:
            fig._suptitle.set_text("")
        except Exception:
            pass


def apply_plot_style(ax, cfg, display_opts, has_exp=False):
    fig = ax.figure
    clear_plot_extras(ax)

    fig.patch.set_facecolor(PLOT_BG)
    ax.set_facecolor(PLOT_BG)

    for spine in ax.spines.values():
        spine.set_color("black")
        spine.set_linewidth(0.8)

    ax.tick_params(axis="both", labelsize=11, width=0.8, direction="in", colors="black")
    ax.set_xlabel("Wavelength (nm)", fontsize=14, fontweight="bold")
    ax.set_ylabel(r"Δε (M$^{-1}$cm$^{-1}$)", fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.3)

    wl_lo, wl_hi = cfg.wavelength_range
    ax.set_xlim(wl_lo, wl_hi)

    if int(round(wl_lo)) == 200 and int(round(wl_hi)) == 400:
        ax.set_xticks([200, 250, 300, 350, 400])
    else:
        ax.set_xticks(np.linspace(wl_lo, wl_hi, 5))

    show_title = display_opts.get("show_title", True)
    show_params = display_opts.get("show_params", True)
    show_top_axis = display_opts.get("show_top_axis", True)

    # 先清空旧标题
    ax.set_title("")

    if show_top_axis:
        secax = ax.secondary_xaxis("top", functions=(nm_to_ev, ev_to_nm))
        secax.set_xlabel("Energy (eV)", fontsize=12)
        secax.tick_params(labelsize=10, width=0.8, direction="in", colors="black")
        ax._top_secondary_axis = secax
    else:
        ax._top_secondary_axis = None

    # 关键：先固定布局
    fig.subplots_adjust(
        left=0.11,
        right=0.97,
        bottom=0.14,
        top=compute_top_margin(show_title, show_params, show_top_axis)
    )

    # 参数行本身就是相对 axes 居中
    if show_params:
        ax.set_title(build_param_line(cfg), fontsize=13, pad=10)

    # 再按固定后的轴位置放总标题
    if show_title:
        title_text = "ECD Spectrum Comparison" if has_exp else "Calculated ECD Spectrum"
        pos = ax.get_position()
        title_x = (pos.x0 + pos.x1) / 2
        fig.suptitle(title_text, fontsize=13, y=0.98, x=title_x)


def draw_main_plot(ax, wl, spec, cfg, exp_wl=None, exp_spec=None,
                   sim_text="", legend_labels=None, display_opts=None):
    ax.clear()

    legend_labels = legend_labels or (
        "Experimental ECD",
        "Calculated ECD",
        "Calculated ECD (Inverted)",
    )
    display_opts = display_opts or {
        "show_title": True,
        "show_params": True,
        "show_top_axis": True,
        "show_similarity": True,
    }

    exp_label, calc_label, inv_label = legend_labels

    max_calc = np.max(np.abs(spec))
    norm_calc = spec if max_calc == 0 else spec / max_calc
    scaled_calc = norm_calc * cfg.scale_factor
    inverted_calc = -scaled_calc

    has_exp = exp_wl is not None and exp_spec is not None

    apply_plot_style(ax, cfg, display_opts, has_exp=has_exp)

    ax.plot(
        wl, scaled_calc,
        "r--",
        linewidth=1.5,
        label=calc_label
    )
    ax.plot(
        wl, inverted_calc,
        "b--",
        linewidth=1.5,
        alpha=0.7,
        label=inv_label
    )

    if has_exp:
        ax.plot(
            exp_wl, exp_spec,
            "k-",
            linewidth=1.5,
            label=exp_label
        )

    ax.axhline(y=0, color="black", linewidth=0.5)

    if display_opts.get("show_similarity", True) and sim_text:
        ax.text(
            0.98, 0.02, sim_text,
            transform=ax.transAxes,
            ha="right", va="bottom",
            fontsize=10,
            color="black"
        )

    ax.legend(
        loc="best",
        shadow=True,
        edgecolor="black",
        facecolor="white",
        fontsize=10
    )


def save_consistent_ecd_plot(output_dir, wl, spec, cfg, exp_wl=None, exp_spec=None,
                             sim_text="", legend_labels=None, display_opts=None):
    fig = Figure(figsize=PLOT_FIGSIZE, dpi=PLOT_DPI_EXPORT, facecolor=PLOT_BG)
    ax = fig.add_subplot(111)
    draw_main_plot(
        ax, wl, spec, cfg,
        exp_wl=exp_wl, exp_spec=exp_spec,
        sim_text=sim_text,
        legend_labels=legend_labels,
        display_opts=display_opts
    )

    png_file = os.path.join(output_dir, "ecd_comparison.png")
    pdf_file = os.path.join(output_dir, "ecd_comparison.pdf")

    fig.savefig(png_file, dpi=PLOT_DPI_EXPORT, bbox_inches="tight", facecolor=PLOT_BG)
    fig.savefig(pdf_file, dpi=PLOT_DPI_EXPORT, bbox_inches="tight", facecolor=PLOT_BG)


class LoadWorker(QThread):
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    finished = pyqtSignal(object, object, object)
    error = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config

    def run(self):
        try:
            cfg = self.config
            self.status.emit("Matching conformers...")
            self.progress.emit(10)
            matcher = ConformerMatcher(cfg)
            collection = matcher.match()

            self.status.emit("Parsing QM outputs...")
            self.progress.emit(30)
            for rec in collection.all_records:
                same_file = (
                    same_output_file(rec.opt_file, rec.ecd_file)
                    and os.path.exists(rec.opt_file)
                )
                if same_file:
                    parse_single_file(rec.opt_file, rec, cfg)
                else:
                    if rec.opt_file and os.path.exists(rec.opt_file):
                        parse_opt_file(rec.opt_file, rec, cfg)
                    if rec.ecd_file and os.path.exists(rec.ecd_file):
                        parse_ecd_file(rec.ecd_file, rec, cfg)

            self.status.emit("Computing weights...")
            self.progress.emit(60)
            wf = cfg.weights_file
            if wf is None:
                for c in [
                    os.path.join(cfg.opt_dir, "ecd_weights.txt"),
                    os.path.join(cfg.opt_dir, "weights.csv"),
                    "ecd_weights.txt",
                ]:
                    if os.path.exists(c):
                        wf = c
                        break

            if wf and os.path.exists(wf):
                load_manual_weights(collection, wf)
            else:
                compute_boltzmann_weights(collection, cfg)
            collection.normalize_weights()

            exp_wl = exp_spec = None
            if cfg.exp_file and os.path.exists(cfg.exp_file):
                exp_wl, exp_spec = read_experimental_data(cfg.exp_file)

            self.progress.emit(100)
            self.finished.emit(collection, exp_wl, exp_spec)
        except Exception as e:
            self.error.emit(str(e))


class ExportWorker(QThread):
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    done = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, cfg, coll, ew, es, out, legend_labels, display_opts):
        super().__init__()
        self.cfg = cfg
        self.coll = coll
        self.ew = ew
        self.es = es
        self.out = out
        self.legend_labels = legend_labels
        self.display_opts = display_opts

    def run(self):
        try:
            cfg = self.cfg
            cfg.output_dir = self.out
            os.makedirs(self.out, exist_ok=True)
            self.progress.emit(20)

            wl, eg = generate_wavelength_grid(*cfg.wavelength_range, EXPORT_PTS)
            spec, indiv = compute_weighted_spectrum(self.coll, wl, eg, cfg.sigma, cfg.shift)

            exp_wl = exp_sp = None
            if self.ew is not None:
                exp_wl = self.ew.copy()
                exp_sp = (
                    smooth_spectrum(
                        self.es.copy(),
                        cfg.smooth_method,
                        cfg.smooth_factor,
                        cfg.savgol_window,
                        cfg.savgol_order
                    )
                    if cfg.smooth_method != "none" else self.es.copy()
                )

            self.progress.emit(40)
            ac = None
            if exp_wl is not None:
                self.status.emit("Running shift scan...")
                ac = shift_scan(
                    spec, eg, exp_sp, exp_wl,
                    cfg.shift_scan_range, cfg.shift_scan_step,
                    cfg.similarity_metric
                )

            sim_text = build_similarity_text(spec, wl, cfg, exp_wl, exp_sp)

            self.progress.emit(60)
            self.status.emit("Generating reports...")
            generate_full_report(cfg, self.coll, ac)
            save_spectrum_csv(wl, spec, cfg, exp_wl, exp_sp)
            cfg.to_json(os.path.join(self.out, "config.json"))

            self.progress.emit(80)
            save_consistent_ecd_plot(
                self.out, wl, spec, cfg,
                exp_wl=exp_wl, exp_spec=exp_sp,
                sim_text=sim_text,
                legend_labels=self.legend_labels,
                display_opts=self.display_opts
            )

            if ac:
                plot_shift_scan(ac, cfg)

            with open(
                os.path.join(self.out, "conformer_status.txt"),
                "w",
                encoding="utf-8"
            ) as f:
                f.write(self.coll.report_text())

            self.progress.emit(100)
            self.done.emit(self.out)
        except Exception as e:
            self.error.emit(str(e))


class PlotCanvas(FigureCanvasQTAgg):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=PLOT_FIGSIZE, dpi=PLOT_DPI_PREVIEW, facecolor=PLOT_BG)
        super().__init__(self.fig)
        self.ax = self.fig.add_subplot(111)
        self.setParent(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.placeholder()

    def placeholder(self):
        self.ax.clear()
        self.fig.patch.set_facecolor(PLOT_BG)
        self.ax.set_facecolor(PLOT_BG)
        self.ax.text(
            0.5, 0.5, "Load data to begin",
            transform=self.ax.transAxes,
            ha="center", va="center",
            fontsize=16, color="#9CA3AF"
        )
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self.fig.subplots_adjust(left=0.05, right=0.95, bottom=0.08, top=0.92)
        self.draw_idle()

    def refresh(self, wl, spec, cfg, exp_wl=None, exp_spec=None,
                sim_text="", legend_labels=None, display_opts=None):
        draw_main_plot(
            self.ax, wl, spec, cfg,
            exp_wl=exp_wl, exp_spec=exp_spec,
            sim_text=sim_text,
            legend_labels=legend_labels,
            display_opts=display_opts
        )
        self.draw_idle()


class AspectRatioPlotHost(QWidget):
    def __init__(self, child_widget, aspect_w=10, aspect_h=6, parent=None):
        super().__init__(parent)
        self.setObjectName("plot_host")
        self.child = child_widget
        self.aspect_w = aspect_w
        self.aspect_h = aspect_h
        self.child.setParent(self)
        self.child.show()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def resizeEvent(self, event):
        super().resizeEvent(event)

        avail_w = max(1, self.width())
        avail_h = max(1, self.height())

        target_h = int(avail_w * self.aspect_h / self.aspect_w)

        if target_h <= avail_h:
            w = avail_w
            h = target_h
        else:
            h = avail_h
            w = int(avail_h * self.aspect_w / self.aspect_h)

        x = (avail_w - w) // 2
        y = (avail_h - h) // 2
        self.child.setGeometry(x, y, w, h)


class ScrollFadeOverlay(QWidget):
    def __init__(self, parent=None, color="#F5F6FA", edge="top"):
        super().__init__(parent)
        self._color = QColor(color)
        self._edge = edge
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        gradient = QLinearGradient(0, 0, 0, max(1, self.height()))
        top = QColor(self._color)
        middle = QColor(self._color)
        bottom = QColor(self._color)
        top.setAlpha(255)
        middle.setAlpha(150)
        bottom.setAlpha(0)
        if self._edge == "bottom":
            gradient.setColorAt(0.0, bottom)
            gradient.setColorAt(0.45, middle)
            gradient.setColorAt(1.0, top)
        else:
            gradient.setColorAt(0.0, top)
            gradient.setColorAt(0.55, middle)
            gradient.setColorAt(1.0, bottom)
        painter.fillRect(self.rect(), gradient)


class RoundedScrollArea(QScrollArea):
    def __init__(self, *args, radius=8, shadow_padding=6, **kwargs):
        super().__init__(*args, **kwargs)
        self._viewport_radius = radius
        self._shadow_padding = shadow_padding
        self._top_fade = None
        self._bottom_fade = None
        self._connect_scrollbar_signals(self.verticalScrollBar())

    def setVerticalScrollBar(self, scrollbar):
        super().setVerticalScrollBar(scrollbar)
        self._connect_scrollbar_signals(scrollbar)

    def _connect_scrollbar_signals(self, scrollbar):
        scrollbar.valueChanged.connect(lambda _value: self._refresh_viewport_layers())
        scrollbar.rangeChanged.connect(lambda _minimum, _maximum: self._refresh_viewport_layers())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_viewport_layers()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_viewport_layers()

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self._refresh_viewport_layers()

    def _content_clip_bounds(self):
        viewport = self.viewport()
        width = viewport.width()
        left = 0
        right = width
        child = self.widget()
        child_layout = child.layout() if child is not None else None
        if child is not None and child_layout is not None:
            margins = child_layout.contentsMargins()
            left = max(0, child.x() + margins.left())
            right = min(width, child.x() + child.width() - margins.right())
            if right <= left:
                left = 0
                right = width
        return (
            max(0, left - self._shadow_padding),
            min(width, right + self._shadow_padding),
        )

    def _refresh_viewport_layers(self):
        self._apply_viewport_mask()
        self._position_edge_fades()

    def _apply_viewport_mask(self):
        viewport = self.viewport()
        width = viewport.width()
        height = viewport.height()
        if width <= 0 or height <= 0:
            viewport.clearMask()
            return
        left, right = self._content_clip_bounds()
        radius = min(
            self._viewport_radius + self._shadow_padding,
            (right - left) // 2,
            height // 2,
        )
        path = QPainterPath()
        path.addRoundedRect(left, 0, right - left, height, radius, radius)
        viewport.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def _position_edge_fades(self):
        viewport = self.viewport()
        width = viewport.width()
        height = viewport.height()
        if width <= 0 or height <= 0:
            return
        if self._top_fade is None:
            self._top_fade = ScrollFadeOverlay(viewport, edge="top")
        if self._bottom_fade is None:
            self._bottom_fade = ScrollFadeOverlay(viewport, edge="bottom")
        left, right = self._content_clip_bounds()
        fade_height = min(24, height)
        scrollbar = self.verticalScrollBar()
        has_top_content = scrollbar.value() > scrollbar.minimum()
        has_bottom_content = scrollbar.value() < scrollbar.maximum()
        self._top_fade.setGeometry(left, 0, right - left, fade_height)
        self._top_fade.setVisible(has_top_content)
        self._top_fade.raise_()
        self._top_fade.update()
        self._bottom_fade.setGeometry(left, height - fade_height, right - left, fade_height)
        self._bottom_fade.setVisible(has_bottom_content)
        self._bottom_fade.raise_()
        self._bottom_fade.update()


class SmoothWheelScrollBar(QScrollBar):
    def wheelEvent(self, e):
        delta_y = e.angleDelta().y()
        if delta_y == 0:
            e.accept()
            return

        steps = delta_y / 120.0
        step_size = max(12, self.singleStep())
        new_value = self.value() - int(steps * step_size)
        self.setValue(new_value)
        e.accept()


class NoWheelSlider(QSlider):
    def wheelEvent(self, e):
        e.ignore()


class NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, e):
        e.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, e):
        e.ignore()


class NoWheelComboBox(QComboBox):
    def wheelEvent(self, e):
        e.ignore()


class LabeledSlider(QWidget):
    valueChanged = pyqtSignal(float)

    def __init__(self, label, lo, hi, step, default, decimals=2, parent=None):
        super().__init__(parent)
        self._lo = lo
        self._hi = hi
        self._step = step
        self._decimals = decimals
        self._n = max(1, int(round((hi - lo) / step)))
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setStyleSheet("background: transparent; border: none;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 1, 0, 1)
        lay.setSpacing(0)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel(label)
        lbl.setObjectName("field_label")

        self.vl = QLabel(f"{default:.{decimals}f}")
        self.vl.setObjectName("value_readout")
        self.vl.setAlignment(Qt.AlignmentFlag.AlignRight)

        top.addWidget(lbl)
        top.addStretch()
        top.addWidget(self.vl)
        lay.addLayout(top)

        self.sl = NoWheelSlider(Qt.Orientation.Horizontal)
        self.sl.setRange(0, self._n)
        self.sl.setValue(self._v_to_tick(default))
        self.sl.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.sl.valueChanged.connect(self._upd)
        lay.addWidget(self.sl)

    def _v_to_tick(self, v):
        return int(round((v - self._lo) / self._step))

    def _tick_to_v(self, t):
        return self._lo + t * self._step

    def _upd(self, t):
        value = self._tick_to_v(t)
        self.vl.setText(f"{value:.{self._decimals}f}")
        self.valueChanged.emit(value)

    def value(self):
        return self._tick_to_v(self.sl.value())

    def setValue(self, value):
        value = max(self._lo, min(self._hi, value))
        self.sl.setValue(self._v_to_tick(value))


class ConformerMatcherEditor(QDialog):
    """构象匹配可视化编辑器对话框"""

    def __init__(self, collection, config, parent=None):
        super().__init__(parent)
        self.collection = collection
        self.config = config
        self.setWindowTitle("Conformer Matching Editor")
        self.resize(1200, 700)

        self.setup_ui()
        self.load_collection_data()

    def setup_ui(self):
        """设置编辑器界面"""
        main_layout = QVBoxLayout(self)

        # 工具栏
        toolbar = QToolBar()
        toolbar.setMovable(False)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.refresh_table)
        toolbar.addWidget(self.btn_refresh)

        self.btn_import = QPushButton("Import CSV")
        self.btn_import.clicked.connect(self.import_mapping)
        toolbar.addWidget(self.btn_import)

        self.btn_export = QPushButton("Export CSV")
        self.btn_export.clicked.connect(self.export_mapping)
        toolbar.addWidget(self.btn_export)

        self.btn_apply = QPushButton("Apply Changes")
        self.btn_apply.setStyleSheet("background-color: #4A7BF7; color: white;")
        self.btn_apply.clicked.connect(self.apply_changes)
        toolbar.addWidget(self.btn_apply)

        toolbar.addSeparator()

        self.filter_label = QLabel("Filter:")
        toolbar.addWidget(self.filter_label)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Search conformers...")
        self.filter_edit.textChanged.connect(self.filter_table)
        toolbar.addWidget(self.filter_edit)

        main_layout.addWidget(toolbar)

        # 分割器：左侧表格，右侧详情
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧表格
        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(10)
        self.table_widget.setHorizontalHeaderLabels([
            "ID", "Label", "OPT File", "ECD File", "Status",
            "Weight", "ΔE (kcal)", "Transitions", "Imag Freq", "Warnings"
        ])
        self.table_widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_widget.setAlternatingRowColors(True)
        self.table_widget.itemChanged.connect(self.on_item_changed)
        self.table_widget.itemSelectionChanged.connect(self.on_selection_changed)
        self.table_widget.cellClicked.connect(self.on_cell_clicked)

        splitter.addWidget(self.table_widget)

        # 右侧详情面板
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)

        # 状态统计
        stats_group = QGroupBox("Statistics")
        stats_layout = QVBoxLayout()

        self.stats_label = QLabel()
        self.stats_label.setStyleSheet("font-family: monospace;")
        stats_layout.addWidget(self.stats_label)

        stats_group.setLayout(stats_layout)
        detail_layout.addWidget(stats_group)

        # 构象详情
        detail_group = QGroupBox("Conformer Details")
        detail_inner_layout = QVBoxLayout()

        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setMaximumHeight(200)
        self.detail_text.setStyleSheet("font-family: monospace; font-size: 10px;")
        detail_inner_layout.addWidget(self.detail_text)

        detail_group.setLayout(detail_inner_layout)
        detail_layout.addWidget(detail_group)

        # 文件浏览
        file_group = QGroupBox("File Operations")
        file_layout = QVBoxLayout()

        self.file_label = QLabel("Selected File:")
        file_layout.addWidget(self.file_label)

        self.file_path_edit = QLineEdit()
        self.file_path_edit.setReadOnly(True)
        file_layout.addWidget(self.file_path_edit)

        file_buttons_layout = QHBoxLayout()
        self.btn_browse_opt = QPushButton("Browse OPT...")

        def browse_opt_handler():
            try:
                self.browse_file("opt")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to browse OPT file: {str(e)}")

        def browse_ecd_handler():
            try:
                self.browse_file("ecd")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to browse ECD file: {str(e)}")

        self.btn_browse_opt.clicked.connect(browse_opt_handler)
        file_buttons_layout.addWidget(self.btn_browse_opt)

        self.btn_browse_ecd = QPushButton("Browse ECD...")
        self.btn_browse_ecd.clicked.connect(browse_ecd_handler)
        file_buttons_layout.addWidget(self.btn_browse_ecd)

        self.btn_clear_file = QPushButton("Clear")
        self.btn_clear_file.clicked.connect(self.clear_selected_file)
        file_buttons_layout.addWidget(self.btn_clear_file)

        file_layout.addLayout(file_buttons_layout)
        file_group.setLayout(file_layout)
        detail_layout.addWidget(file_group)

        detail_layout.addStretch()

        splitter.addWidget(detail_widget)

        # 设置分割器初始比例
        splitter.setSizes([800, 400])

        main_layout.addWidget(splitter, 1)

        # 底部按钮
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

    def load_collection_data(self):
        """加载构象数据到表格"""
        records = self.collection.all_records
        self.table_widget.setRowCount(len(records))

        for row, rec in enumerate(records):
            # ID
            id_item = QTableWidgetItem(str(rec.conf_id))
            id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table_widget.setItem(row, 0, id_item)

            # Label
            label_item = QTableWidgetItem(rec.label)
            self.table_widget.setItem(row, 1, label_item)

            # OPT File
            opt_item = QTableWidgetItem(rec.opt_file or "")
            self.table_widget.setItem(row, 2, opt_item)

            # ECD File
            ecd_item = QTableWidgetItem(rec.ecd_file or "")
            self.table_widget.setItem(row, 3, ecd_item)

            # Status
            status_item = QTableWidgetItem(rec.status.value)
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            # 根据状态设置颜色
            if rec.status.value == "ok":
                status_item.setBackground(QColor("#D1FAE5"))  # green
            elif rec.status.value.startswith("no_"):
                status_item.setBackground(QColor("#FEE2E2"))  # red
            elif "imag" in rec.status.value:
                status_item.setBackground(QColor("#FEF3C7"))  # yellow
            else:
                status_item.setBackground(QColor("#E5E7EB"))  # gray
            self.table_widget.setItem(row, 4, status_item)

            # Weight
            weight_item = QTableWidgetItem(f"{rec.effective_weight:.4f}")
            weight_item.setFlags(weight_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table_widget.setItem(row, 5, weight_item)

            # ΔE (kcal)
            de_item = QTableWidgetItem(f"{rec.relative_energy_kcal:.2f}" if rec.relative_energy_kcal is not None else "")
            de_item.setFlags(de_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table_widget.setItem(row, 6, de_item)

            # Transitions
            trans_item = QTableWidgetItem(str(rec.n_transitions) if rec.n_transitions > 0 else "")
            trans_item.setFlags(trans_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table_widget.setItem(row, 7, trans_item)

            # Imag Freq
            imag_item = QTableWidgetItem(str(rec.n_imaginary) if rec.n_imaginary > 0 else "")
            imag_item.setFlags(imag_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table_widget.setItem(row, 8, imag_item)

            # Warnings
            warnings_text = "; ".join(rec.warnings) if rec.warnings else ""
            warnings_item = QTableWidgetItem(warnings_text)
            warnings_item.setFlags(warnings_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table_widget.setItem(row, 9, warnings_item)

        self.update_statistics()

    def update_statistics(self):
        """更新状态统计信息"""
        records = self.collection.all_records
        usable = len(self.collection.usable_records)
        failed = len(self.collection.failed_records)

        stats_text = f"""Total Conformers: {len(records)}
Usable: {usable}
Failed: {failed}

Status Breakdown:
"""
        summary = self.collection.status_summary()
        for status, count in sorted(summary.items()):
            stats_text += f"  {status:<25s}: {count}\n"

        self.stats_label.setText(stats_text)

    def on_item_changed(self, item):
        """表格项更改时的处理"""
        row = item.row()
        col = item.column()
        conf_id = int(self.table_widget.item(row, 0).text())

        rec = self.collection.get(conf_id)
        if rec is None:
            return

        if col == 1:  # Label
            rec.label = item.text()
        elif col == 2:  # OPT File
            rec.opt_file = item.text() if item.text().strip() else None
        elif col == 3:  # ECD File
            rec.ecd_file = item.text() if item.text().strip() else None

        # 更新状态显示
        self.update_row_status(row, rec)

    def update_row_status(self, row, rec):
        """更新行的状态显示"""
        # 更新状态列
        status_item = self.table_widget.item(row, 4)
        if status_item:
            status_item.setText(rec.status.value)
            # 更新颜色
            if rec.status.value == "ok":
                status_item.setBackground(QColor("#D1FAE5"))
            elif rec.status.value.startswith("no_"):
                status_item.setBackground(QColor("#FEE2E2"))
            elif "imag" in rec.status.value:
                status_item.setBackground(QColor("#FEF3C7"))
            else:
                status_item.setBackground(QColor("#E5E7EB"))

    def on_selection_changed(self):
        """选择改变时更新详情面板"""
        selected_rows = self.table_widget.selectedItems()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        conf_id = int(self.table_widget.item(row, 0).text())
        rec = self.collection.get(conf_id)

        if rec:
            # 更新构象详情
            detail_text = f"""Conf ID: {rec.conf_id}
Label: {rec.label}
Status: {rec.status.value}
Weight: {rec.effective_weight:.4f}
ΔE (kcal/mol): {rec.relative_energy_kcal if rec.relative_energy_kcal is not None else 'N/A'}
Transitions: {rec.n_transitions}
Imaginary Frequencies: {rec.n_imaginary}

OPT File: {rec.opt_file or 'Not set'}
ECD File: {rec.ecd_file or 'Not set'}

Warnings: {len(rec.warnings)}
"""
            for w in rec.warnings:
                detail_text += f"  ⚠ {w}\n"

            detail_text += f"\nErrors: {len(rec.errors)}\n"
            for e in rec.errors:
                detail_text += f"  ✗ {e}\n"

            self.detail_text.setText(detail_text)

            # 更新文件路径显示（基于当前列）
            self._update_file_path_display(row)

    def on_cell_clicked(self, row, column):
        """单元格被点击时更新文件路径显示"""
        self._update_file_path_display(row)

    def _update_file_path_display(self, row):
        """根据当前列更新文件路径显示"""
        conf_id = int(self.table_widget.item(row, 0).text())
        rec = self.collection.get(conf_id)
        if not rec:
            return

        current_col = self.table_widget.currentColumn()
        current_file = ""
        if current_col == 2:  # OPT列
            current_file = rec.opt_file or ""
        elif current_col == 3:  # ECD列
            current_file = rec.ecd_file or ""

        self.file_path_edit.setText(current_file)

    def browse_file(self, file_type):
        """浏览文件对话框"""
        try:
            current_row = self.table_widget.currentRow()
            if current_row < 0:
                QMessageBox.warning(self, "Warning", "Please select a conformer row first")
                return

            # 确定初始目录
            if file_type == "opt" and self.config.opt_dir:
                initial_dir = self.config.opt_dir
            elif file_type == "ecd" and self.config.ecd_dir:
                initial_dir = self.config.ecd_dir
            else:
                initial_dir = ""

            file_path, _ = QFileDialog.getOpenFileName(
                self,
                f"Select {file_type.upper()} File",
                initial_dir,
                "QM Output (*.out *.log *.orca);;All Files (*)"
            )

            if file_path:
                col = 2 if file_type == "opt" else 3
                item = QTableWidgetItem(file_path)
                self.table_widget.setItem(current_row, col, item)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open file dialog: {str(e)}")

    def clear_selected_file(self):
        """清除选中的文件路径"""
        current_row = self.table_widget.currentRow()
        current_col = self.table_widget.currentColumn()

        if current_row >= 0 and current_col in [2, 3]:  # OPT或ECD列
            self.table_widget.setItem(current_row, current_col, QTableWidgetItem(""))

    def filter_table(self):
        """过滤表格内容"""
        filter_text = self.filter_edit.text().lower()

        for row in range(self.table_widget.rowCount()):
            show_row = False
            if not filter_text:
                show_row = True
            else:
                # 检查每一列是否包含过滤文本
                for col in range(self.table_widget.columnCount()):
                    item = self.table_widget.item(row, col)
                    if item and filter_text in item.text().lower():
                        show_row = True
                        break

            self.table_widget.setRowHidden(row, not show_row)

    def refresh_table(self):
        """刷新表格数据"""
        self.load_collection_data()

    def import_mapping(self):
        """导入CSV映射文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Mapping CSV",
            "",
            "CSV Files (*.csv);;All Files (*)"
        )

        if file_path:
            try:
                from ecd_platform.matcher import ConformerMatcher
                matcher = ConformerMatcher(self.config)
                matcher.import_mapping(file_path, self.collection)
                self.refresh_table()
                QMessageBox.information(self, "Success", f"Mapping imported from {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to import mapping: {str(e)}")

    def export_mapping(self):
        """导出CSV映射文件"""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Mapping CSV",
            "conformer_mapping.csv",
            "CSV Files (*.csv);;All Files (*)"
        )

        if file_path:
            try:
                from ecd_platform.matcher import ConformerMatcher
                matcher = ConformerMatcher(self.config)
                matcher.export_mapping(self.collection, file_path)
                QMessageBox.information(self, "Success", f"Mapping exported to {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export mapping: {str(e)}")

    def apply_changes(self):
        """应用更改到主窗口"""
        self.accept()


class _InlineStatusBar:
    def __init__(self, label):
        self._label = label

    def showMessage(self, message, timeout=0):
        self._label.setText(message)

    def currentMessage(self):
        return self._label.text()


class ECDPage(QWidget):
    def __init__(self, parent=None, embedded=False):
        super().__init__(parent)
        self.setMinimumSize(1000, 650)
        self.setStyleSheet(STYLESHEET)
        self._embedded = embedded

        self._collection = None
        self._exp_wl_raw = None
        self._exp_spec_raw = None
        self._data_loaded = False
        self._worker = None
        self._export_worker = None
        self.output_dir = os.path.abspath("ecd_results")
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(80)
        self._preview_timer.timeout.connect(self._on_preview)

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        toolbar_shell = QWidget()
        toolbar_shell.setObjectName("ecd_toolbar_shell")
        toolbar_layout = QVBoxLayout(toolbar_shell)
        if self._embedded:
            toolbar_layout.setContentsMargins(0, 10, 0, 10)
        else:
            toolbar_layout.setContentsMargins(12, 10, 12, 10)
        toolbar_layout.setSpacing(0)

        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        toolbar_layout.addWidget(tb)
        page_layout.addWidget(toolbar_shell)

        self.btn_load = QPushButton("  Load Data  ")
        self.btn_load.setObjectName("btn_load")
        self.btn_load.clicked.connect(self._on_load)
        tb.addWidget(self.btn_load)

        self.btn_preview = QPushButton("  Preview  ")
        self.btn_preview.clicked.connect(self._on_preview)
        tb.addWidget(self.btn_preview)

        # 添加构象编辑器按钮
        self.btn_editor = QPushButton("  Conformer Editor  ")
        self.btn_editor.setObjectName("btn_editor")
        self.btn_editor.clicked.connect(self._open_conformer_editor)
        self.btn_editor.setEnabled(False)  # 初始禁用，加载数据后启用
        tb.addWidget(self.btn_editor)

        self.btn_export = QPushButton("  Export All  ")
        self.btn_export.setObjectName("btn_export")
        self.btn_export.clicked.connect(self._on_export)
        tb.addWidget(self.btn_export)

        tb.addSeparator()
        self.tb_info = QLabel("")
        self.tb_info.setStyleSheet("color: #6B7280; font-size: 11px; padding: 0 8px;")
        tb.addWidget(self.tb_info)

        central = QWidget()
        central.setStyleSheet("background-color: #F5F6FA;")
        hbox = QHBoxLayout(central)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(0)

        scroll = RoundedScrollArea(radius=8)
        scroll.setObjectName("sidebar_scroll")
        scroll.viewport().setObjectName("sidebar_scroll_viewport")
        scroll.viewport().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        scroll.setFixedWidth(392)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        vbar = SmoothWheelScrollBar(Qt.Orientation.Vertical, scroll)
        vbar.setObjectName("sidebar_vscrollbar")
        vbar.setSingleStep(24)
        scroll.setVerticalScrollBar(vbar)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar_inner")
        sidebar.setMinimumWidth(366)
        sidebar.setMaximumWidth(366)
        sidebar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

        self.slay = QVBoxLayout(sidebar)
        if self._embedded:
            self.slay.setContentsMargins(0, 10, 12, 14)
        else:
            self.slay.setContentsMargins(12, 10, 12, 14)
        self.slay.setSpacing(10)
        self.slay.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._section_card_index = 0
        self._build_sidebar()

        scroll.setWidget(sidebar)

        right = QWidget()
        right.setStyleSheet("background-color: #F5F6FA;")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 8, 8, 4)
        rl.setSpacing(6)

        self.canvas = PlotCanvas()
        self.plot_host = AspectRatioPlotHost(
            self.canvas,
            aspect_w=PLOT_FIGSIZE[0],
            aspect_h=PLOT_FIGSIZE[1]
        )
        plot_card = QFrame()
        plot_card.setObjectName("plot_card")
        plot_card.setFrameShape(QFrame.Shape.NoFrame)
        plot_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        plot_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        plot_card_layout = QVBoxLayout(plot_card)
        plot_card_layout.setContentsMargins(12, 12, 12, 12)
        plot_card_layout.setSpacing(0)
        plot_card_layout.addWidget(self.plot_host)

        nav = NavigationToolbar2QT(self.canvas, self)
        nav.setObjectName("plot_toolbar")
        nav.setStyleSheet(
            "QWidget#plot_toolbar { background: #FFFFFF; border: 1px solid #E2E5EB; "
            "border-radius: 8px; padding: 2px; }"
        )

        rl.addWidget(nav)
        rl.addWidget(plot_card, 1)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        rl.addWidget(self.progress)

        hbox.addWidget(scroll, 0)
        hbox.addWidget(right, 1)

        page_layout.addWidget(central, 1)
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("inline_status")
        self.status_label.setStyleSheet(
            "QLabel#inline_status { background: #FFFFFF; border-top: 1px solid #E2E5EB; "
            "color: #4B5563; padding: 4px 10px; }"
        )
        page_layout.addWidget(self.status_label)
        self._status_bar = _InlineStatusBar(self.status_label)
        self.statusBar().showMessage("Ready")

    def statusBar(self):
        return self._status_bar

    def _build_sidebar(self):
        L = self._section_card("FILE INPUT", "#4A7BF7")
        self.inp_opt = self._path_row(L, "OPT/FREQ directory", True)
        self.inp_ecd = self._path_row(L, "ECD output directory", True)
        self.inp_exp = self._path_row(L, "Experimental ECD file", False)
        self.inp_wt = self._path_row(L, "Weights file (optional)", False)
        self.cb_prog = self._combo(L, "QM Program", ["auto", "gaussian", "orca"], 0)

        L = self._section_card("SPECTRUM PARAMETERS", "#0EA5E9")
        self.sl_sigma = LabeledSlider("Broadening (eV)", 0.05, 1.0, 0.05, 0.30)
        L.addWidget(self.sl_sigma)

        self.sl_shift = LabeledSlider("Shift (eV)", -1.0, 1.0, 0.01, 0.00)
        L.addWidget(self.sl_shift)

        self.sl_scale = LabeledSlider("Scale factor", 0.1, 50.0, 0.1, 1.0, 1)
        L.addWidget(self.sl_scale)

        r = QHBoxLayout()
        r.setSpacing(6)
        fl = QLabel("Range (nm)")
        fl.setObjectName("field_label")
        r.addWidget(fl)

        self.sp_wl_lo = NoWheelDoubleSpinBox()
        self.sp_wl_lo.setRange(100, 800)
        self.sp_wl_lo.setValue(200)
        self.sp_wl_lo.setDecimals(0)
        self.sp_wl_lo.setSingleStep(1)

        self.sp_wl_hi = NoWheelDoubleSpinBox()
        self.sp_wl_hi.setRange(100, 800)
        self.sp_wl_hi.setValue(400)
        self.sp_wl_hi.setDecimals(0)
        self.sp_wl_hi.setSingleStep(1)

        r.addWidget(self._external_stepper(self.sp_wl_lo, 68))
        r.addWidget(QLabel("-"))
        r.addWidget(self._external_stepper(self.sp_wl_hi, 68))
        r.addStretch()
        L.addLayout(r)

        L = self._section_card("STRATEGY", "#F59E0B")
        self.cb_wt = self._combo(L, "Weighting", ["electronic", "gibbs", "single_point", "manual"], 1)
        self.cb_imag = self._combo(L, "Imag freq policy", ["strict", "tolerant", "manual"], 1)

        self.sl_imag_th = LabeledSlider("Imag freq threshold (cm-1)", -100, 0, 1, -10, 0)
        L.addWidget(self.sl_imag_th)

        r2 = QHBoxLayout()
        fl2 = QLabel("Temperature (K)")
        fl2.setObjectName("field_label")
        r2.addWidget(fl2)

        self.sp_temp = NoWheelDoubleSpinBox()
        self.sp_temp.setRange(100, 500)
        self.sp_temp.setValue(298.15)
        self.sp_temp.setDecimals(2)
        self.sp_temp.setSingleStep(1.0)

        r2.addWidget(self._external_stepper(self.sp_temp, 78))
        r2.addStretch()
        L.addLayout(r2)

        self.cb_gauge = self._combo(L, "CD gauge", ["length", "velocity"], 0)

        L = self._section_card("SMOOTHING", "#10B981")
        self.cb_sm = self._combo(L, "Method", ["fft", "savgol", "none"], 0)

        self.sl_fft = LabeledSlider("FFT cutoff", 0.01, 1.0, 0.01, 0.10)
        L.addWidget(self.sl_fft)

        r3 = QHBoxLayout()
        r3.setSpacing(6)

        fl3 = QLabel("SG window")
        fl3.setObjectName("field_label")
        r3.addWidget(fl3)

        self.sp_sgw = NoWheelSpinBox()
        self.sp_sgw.setRange(3, 101)
        self.sp_sgw.setValue(15)
        self.sp_sgw.setSingleStep(2)
        r3.addWidget(self._external_stepper(self.sp_sgw, 56))

        fl4 = QLabel("order")
        fl4.setObjectName("field_label")
        r3.addWidget(fl4)

        self.sp_sgo = NoWheelSpinBox()
        self.sp_sgo.setRange(1, 10)
        self.sp_sgo.setValue(3)
        r3.addWidget(self._external_stepper(self.sp_sgo, 48))

        r3.addStretch()
        L.addLayout(r3)

        L = self._section_card("COMPARISON", "#EF4444")
        self.cb_metric = self._combo(L, "Similarity", ["cosine", "pearson", "tanimoto"], 0)

        fl5 = QLabel("Shift scan (eV)")
        fl5.setObjectName("field_label")
        L.addWidget(fl5)

        self.sp_scn_lo = NoWheelDoubleSpinBox()
        self.sp_scn_lo.setRange(-2, 0)
        self.sp_scn_lo.setValue(-0.5)
        self.sp_scn_lo.setDecimals(2)
        self.sp_scn_lo.setSingleStep(0.01)

        self.sp_scn_hi = NoWheelDoubleSpinBox()
        self.sp_scn_hi.setRange(0, 2)
        self.sp_scn_hi.setValue(0.5)
        self.sp_scn_hi.setDecimals(2)
        self.sp_scn_hi.setSingleStep(0.01)

        self.sp_scn_st = NoWheelDoubleSpinBox()
        self.sp_scn_st.setRange(0.005, 0.2)
        self.sp_scn_st.setValue(0.02)
        self.sp_scn_st.setDecimals(3)
        self.sp_scn_st.setSingleStep(0.005)

        r4 = QHBoxLayout()
        r4.setSpacing(6)
        r4.addWidget(self._external_stepper(self.sp_scn_lo, 72))
        r4.addWidget(QLabel("to"))
        r4.addWidget(self._external_stepper(self.sp_scn_hi, 72))
        r4.addStretch()
        L.addLayout(r4)

        step_label = QLabel("step")
        step_label.setObjectName("field_label")
        L.addWidget(step_label)

        r4_step = QHBoxLayout()
        r4_step.setSpacing(6)
        r4_step.addWidget(self._external_stepper(self.sp_scn_st, 78))
        r4_step.addStretch()
        L.addLayout(r4_step)

        L = self._section_card("PLOT LEGENDS", "#8B5CF6")
        hint = QLabel("Standalone uppercase R / S will be auto-italicized in legends.")
        hint.setObjectName("hint_label")
        hint.setWordWrap(True)
        L.addWidget(hint)

        self.inp_lbl_exp = self._text_row(
            L,
            "Experimental legend",
            "Experimental ECD of 8*"
        )
        self.inp_lbl_calc = self._text_row(
            L,
            "Calculated legend",
            "Calculated ECD of (8R, 8'S, 7''S, 8''S)-1"
        )
        self.inp_lbl_calc_inv = self._text_row(
            L,
            "Inverted calculated legend",
            "Calculated ECD of (8S, 8'R, 7''R, 8''R)-1"
        )

        L = self._section_card("DISPLAY OPTIONS", "#64748B")
        self.ck_show_title = QCheckBox("Show title")
        self.ck_show_title.setChecked(True)
        L.addWidget(self.ck_show_title)

        self.ck_show_params = QCheckBox("Show parameters")
        self.ck_show_params.setChecked(True)
        L.addWidget(self.ck_show_params)

        self.ck_show_top_axis = QCheckBox("Show top energy axis")
        self.ck_show_top_axis.setChecked(True)
        L.addWidget(self.ck_show_top_axis)

        self.ck_show_similarity = QCheckBox("Show similarity text")
        self.ck_show_similarity.setChecked(True)
        L.addWidget(self.ck_show_similarity)

        self._connect_live_preview_controls()

    def _connect_live_preview_controls(self):
        for slider in (
            self.sl_sigma,
            self.sl_shift,
            self.sl_scale,
            self.sl_fft,
        ):
            slider.valueChanged.connect(self._schedule_preview_refresh)

    def _section_card(self, title, accent):
        card = QFrame()
        card.setObjectName("section_card")
        alt_tone = self._section_card_index % 2
        card.setProperty("altTone", str(alt_tone))
        self._section_card_index += 1
        if alt_tone == 0:
            bg_color = "#FFFFFF"
            border_color = "#E2E8F0"
        else:
            bg_color = "#E8F0FF"
            border_color = "#CBDCF8"
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(
            f"QFrame#section_card {{ "
            f"background-color: {bg_color}; "
            f"border: 1px solid {border_color}; "
            f"border-radius: 8px; }}"
            f"QFrame#section_card QLabel {{ "
            f"background-color: {bg_color}; "
            f"border: none; }}"
            f"QFrame#section_card QLabel#section_hdr {{ "
            f"background-color: {bg_color}; }}"
            f"QFrame#section_card QLabel#field_label {{ "
            f"background-color: {bg_color}; }}"
            f"QFrame#section_card QLabel#value_readout {{ "
            f"background-color: {bg_color}; }}"
            f"QFrame#section_card QLabel#hint_label {{ "
            f"background-color: {bg_color}; }}"
        )
        card.setFrameShape(QFrame.Shape.NoFrame)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        outer = QVBoxLayout(card)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(7)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(7)

        bar = QFrame()
        bar.setObjectName("section_accent")
        bar.setFixedSize(3, 14)
        bar.setStyleSheet(f"background-color: {accent}; border-radius: 1px;")
        title_row.addWidget(bar)

        lbl = QLabel(title)
        lbl.setObjectName("section_hdr")
        title_row.addWidget(lbl)
        title_row.addStretch()

        outer.addLayout(title_row)
        self.slay.addWidget(card)
        return outer

    def _path_row(self, L, label, is_dir):
        fl = QLabel(label)
        fl.setObjectName("field_label")
        L.addWidget(fl)

        row = QHBoxLayout()
        row.setSpacing(4)

        le = QLineEdit()
        le.setPlaceholderText("Click ... to select")
        row.addWidget(le, 1)

        btn = QPushButton("...")
        btn.setObjectName("btn_browse")

        # 使用闭包函数确保正确的变量捕获
        def make_dir_handler(line_edit):
            def handler():
                try:
                    self._bdir(line_edit)
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to open directory dialog: {str(e)}")
            return handler

        def make_file_handler(line_edit):
            def handler():
                try:
                    self._bfile(line_edit)
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to open file dialog: {str(e)}")
            return handler

        if is_dir:
            btn.clicked.connect(make_dir_handler(le))
        else:
            btn.clicked.connect(make_file_handler(le))
        row.addWidget(btn)

        L.addLayout(row)
        return le

    def _text_row(self, L, label, default_text):
        fl = QLabel(label)
        fl.setObjectName("field_label")
        L.addWidget(fl)

        le = QLineEdit()
        le.setText(default_text)
        L.addWidget(le)
        return le

    def _combo(self, L, label, items, idx):
        fl = QLabel(label)
        fl.setObjectName("field_label")
        L.addWidget(fl)

        cb = NoWheelComboBox()
        cb.addItems(items)
        cb.setCurrentIndex(idx)
        L.addWidget(cb)
        return cb

    def _external_stepper(self, spin: QAbstractSpinBox, display_width: int) -> QWidget:
        spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        spin.setFixedWidth(display_width)
        spin.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        wrapper = QWidget()
        wrapper.setObjectName("external_spin")
        wrapper.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(spin)

        buttons = QWidget()
        buttons_layout = QVBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(2)

        up_button = QPushButton("+")
        down_button = QPushButton("-")
        for button in (up_button, down_button):
            button.setObjectName("spin_step_button")
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            buttons_layout.addWidget(button)

        up_button.clicked.connect(spin.stepUp)
        down_button.clicked.connect(spin.stepDown)

        def refresh_buttons(*_ignored) -> None:
            up_button.setEnabled(spin.value() < spin.maximum())
            down_button.setEnabled(spin.value() > spin.minimum())

        spin.valueChanged.connect(refresh_buttons)
        refresh_buttons()

        row.addWidget(buttons)
        return wrapper

    def _bdir(self, le):
        try:
            self.statusBar().showMessage("Opening directory dialog...")
            d = QFileDialog.getExistingDirectory(self, "Select Directory")
            if d:
                le.setText(d)
                self.statusBar().showMessage(f"Selected directory: {d}")
            else:
                self.statusBar().showMessage("Directory selection cancelled")
        except Exception as e:
            self.statusBar().showMessage(f"Error: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to open directory dialog: {str(e)}")

    def _bfile(self, le):
        try:
            self.statusBar().showMessage("Opening file dialog...")
            f, _ = QFileDialog.getOpenFileName(
                self,
                "Select File",
                "",
                "Data (*.csv *.txt *.dat);;All (*)"
            )
            if f:
                le.setText(f)
                self.statusBar().showMessage(f"Selected file: {os.path.basename(f)}")
            else:
                self.statusBar().showMessage("File selection cancelled")
        except Exception as e:
            self.statusBar().showMessage(f"Error: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to open file dialog: {str(e)}")

    def _legend_labels(self):
        exp_label = normalize_legend_text(self.inp_lbl_exp.text(), "Experimental ECD")
        calc_label = normalize_legend_text(self.inp_lbl_calc.text(), "Calculated ECD")
        inv_label = normalize_legend_text(self.inp_lbl_calc_inv.text(), "Calculated ECD (Inverted)")
        return exp_label, calc_label, inv_label

    def _display_options(self):
        return {
            "show_title": self.ck_show_title.isChecked(),
            "show_params": self.ck_show_params.isChecked(),
            "show_top_axis": self.ck_show_top_axis.isChecked(),
            "show_similarity": self.ck_show_similarity.isChecked(),
        }

    def current_config(self, n_points=None):
        n_points = ECDConfig().n_points if n_points is None else n_points
        return ECDConfig(
            opt_dir=self.inp_opt.text() or "opt_conf",
            ecd_dir=self.inp_ecd.text() or "ecd_conf",
            exp_file=self.inp_exp.text() or None,
            weights_file=self.inp_wt.text() or None,
            program=QMProgram(self.cb_prog.currentText()),
            sigma=self.sl_sigma.value(),
            shift=self.sl_shift.value(),
            scale_factor=self.sl_scale.value(),
            wavelength_range=(self.sp_wl_lo.value(), self.sp_wl_hi.value()),
            n_points=n_points,
            weighting=WeightingStrategy(self.cb_wt.currentText()),
            imag_freq_policy=ImagFreqPolicy(self.cb_imag.currentText()),
            imag_freq_threshold=self.sl_imag_th.value(),
            temperature=self.sp_temp.value(),
            cd_gauge=CDGauge(self.cb_gauge.currentText()),
            smooth_method=self.cb_sm.currentText(),
            smooth_factor=self.sl_fft.value(),
            savgol_window=self.sp_sgw.value(),
            savgol_order=self.sp_sgo.value(),
            similarity_metric=self.cb_metric.currentText(),
            shift_scan_range=(self.sp_scn_lo.value(), self.sp_scn_hi.value()),
            shift_scan_step=self.sp_scn_st.value(),
            output_dir=self.output_dir,
            plot_exp_label=self.inp_lbl_exp.text(),
            plot_calc_label=self.inp_lbl_calc.text(),
            plot_ent_label=self.inp_lbl_calc_inv.text(),
        )

    def _cfg(self, n=PREVIEW_PTS):
        return self.current_config(n)

    def to_project_dict(self):
        return {
            "config": self.current_config().to_dict(),
            "legend_labels": {
                "experimental": self.inp_lbl_exp.text(),
                "calculated": self.inp_lbl_calc.text(),
                "inverted": self.inp_lbl_calc_inv.text(),
            },
            "display_options": self._display_options(),
            "output_dir": self.output_dir,
        }

    def load_project_dict(self, data):
        data = data or {}
        cfg_data = dict(data.get("config", data))
        defaults = ECDConfig()

        def value(name):
            return cfg_data.get(name, getattr(defaults, name))

        def set_combo(combo, text):
            index = combo.findText(str(text))
            combo.setCurrentIndex(index if index >= 0 else 0)

        self.inp_opt.setText(str(value("opt_dir") or ""))
        self.inp_ecd.setText(str(value("ecd_dir") or ""))
        self.inp_exp.setText(str(value("exp_file") or ""))
        self.inp_wt.setText(str(value("weights_file") or ""))
        set_combo(self.cb_prog, getattr(value("program"), "value", value("program")))
        self.sl_sigma.setValue(float(value("sigma")))
        self.sl_shift.setValue(float(value("shift")))
        self.sl_scale.setValue(float(value("scale_factor")))
        wl_range = value("wavelength_range")
        self.sp_wl_lo.setValue(float(wl_range[0]))
        self.sp_wl_hi.setValue(float(wl_range[1]))
        set_combo(self.cb_wt, getattr(value("weighting"), "value", value("weighting")))
        set_combo(self.cb_imag, getattr(value("imag_freq_policy"), "value", value("imag_freq_policy")))
        self.sl_imag_th.setValue(float(value("imag_freq_threshold")))
        self.sp_temp.setValue(float(value("temperature")))
        set_combo(self.cb_gauge, getattr(value("cd_gauge"), "value", value("cd_gauge")))
        set_combo(self.cb_sm, value("smooth_method"))
        self.sl_fft.setValue(float(value("smooth_factor")))
        self.sp_sgw.setValue(int(value("savgol_window")))
        self.sp_sgo.setValue(int(value("savgol_order")))
        set_combo(self.cb_metric, value("similarity_metric"))
        scan_range = value("shift_scan_range")
        self.sp_scn_lo.setValue(float(scan_range[0]))
        self.sp_scn_hi.setValue(float(scan_range[1]))
        self.sp_scn_st.setValue(float(value("shift_scan_step")))

        labels = data.get("legend_labels", {})
        self.inp_lbl_exp.setText(str(labels.get("experimental", value("plot_exp_label"))))
        self.inp_lbl_calc.setText(str(labels.get("calculated", value("plot_calc_label"))))
        self.inp_lbl_calc_inv.setText(str(labels.get("inverted", value("plot_ent_label"))))

        display = data.get("display_options", {})
        self.ck_show_title.setChecked(bool(display.get("show_title", True)))
        self.ck_show_params.setChecked(bool(display.get("show_params", True)))
        self.ck_show_top_axis.setChecked(bool(display.get("show_top_axis", True)))
        self.ck_show_similarity.setChecked(bool(display.get("show_similarity", True)))
        self.output_dir = str(data.get("output_dir") or value("output_dir") or os.path.abspath("ecd_results"))
        self.statusBar().showMessage("Ready")

    def _schedule_preview_refresh(self, *_):
        if not self._data_loaded:
            return

        if self._worker is not None and self._worker.isRunning():
            return

        if self._export_worker is not None and self._export_worker.isRunning():
            return

        self._preview_timer.start()

    def _on_load(self):
        self.btn_load.setEnabled(False)
        self._worker = LoadWorker(self._cfg())
        self._worker.progress.connect(self.progress.setValue)
        self._worker.status.connect(lambda s: self.statusBar().showMessage(s))
        self._worker.finished.connect(self._load_done)
        self._worker.error.connect(self._load_err)
        self._worker.start()

    def _load_done(self, coll, ew, es):
        self._collection = coll
        self._exp_wl_raw = ew
        self._exp_spec_raw = es
        self._data_loaded = True
        self.btn_load.setEnabled(True)
        self.btn_editor.setEnabled(True)  # 启用编辑器按钮

        n_ok = len(coll.usable_records)
        n_fail = len(coll.failed_records)
        exp_s = f"  |  Exp: {len(ew)} pts" if ew is not None else ""
        msg = f"Loaded: {n_ok} usable, {n_fail} failed{exp_s}"

        self.statusBar().showMessage(msg)
        self.tb_info.setText(msg)
        self._on_preview()

    def _load_err(self, msg):
        self.btn_load.setEnabled(True)
        self.statusBar().showMessage(f"Error: {msg}")
        self.progress.setValue(0)

    def _open_conformer_editor(self):
        """打开构象匹配编辑器"""
        if not self._data_loaded:
            self.statusBar().showMessage("Load data first")
            return

        cfg = self._cfg(PREVIEW_PTS)
        editor = ConformerMatcherEditor(self._collection, cfg, self)
        if editor.exec():
            # 编辑器被接受，可以重新解析构象
            self.statusBar().showMessage("Conformer mapping updated")
            # 可选：重新计算权重和预览
            self._on_preview()

    def _on_preview(self):
        if not self._data_loaded:
            self.statusBar().showMessage("Load data first")
            return

        cfg = self._cfg(PREVIEW_PTS)
        legend_labels = self._legend_labels()
        display_opts = self._display_options()

        ew = es = None
        if self._exp_wl_raw is not None:
            ew = self._exp_wl_raw.copy()
            es = (
                smooth_spectrum(
                    self._exp_spec_raw.copy(),
                    cfg.smooth_method,
                    cfg.smooth_factor,
                    cfg.savgol_window,
                    cfg.savgol_order
                )
                if cfg.smooth_method != "none" else self._exp_spec_raw.copy()
            )

        wl, eg = generate_wavelength_grid(*cfg.wavelength_range, PREVIEW_PTS)
        spec, _ = compute_weighted_spectrum(
            self._collection, wl, eg, sigma=cfg.sigma, shift=cfg.shift
        )

        sim_text = build_similarity_text(spec, wl, cfg, ew, es)
        self.canvas.refresh(
            wl, spec, cfg,
            exp_wl=ew, exp_spec=es,
            sim_text=sim_text,
            legend_labels=legend_labels,
            display_opts=display_opts
        )
        self.statusBar().showMessage("Preview updated")

    def _on_export(self):
        if not self._data_loaded:
            self.statusBar().showMessage("Load data first")
            return

        d = QFileDialog.getExistingDirectory(self, "Export to", self.output_dir)
        if not d:
            return
        self.output_dir = d

        legend_labels = self._legend_labels()
        display_opts = self._display_options()

        self.btn_export.setEnabled(False)
        self._export_worker = ExportWorker(
            self._cfg(EXPORT_PTS),
            self._collection,
            self._exp_wl_raw,
            self._exp_spec_raw,
            d,
            legend_labels,
            display_opts
        )
        self._export_worker.progress.connect(self.progress.setValue)
        self._export_worker.status.connect(lambda s: self.statusBar().showMessage(s))
        self._export_worker.done.connect(self._exp_done)
        self._export_worker.error.connect(self._exp_err)
        self._export_worker.start()

    def _exp_done(self, p):
        self.btn_export.setEnabled(True)
        self.statusBar().showMessage(f"Exported to {p}")

    def _exp_err(self, m):
        self.btn_export.setEnabled(True)
        self.statusBar().showMessage(f"Export error: {m}")
        self.progress.setValue(0)


class ECDMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ECD-Platform v1.2 - Natural Product Absolute Configuration")
        self.resize(1400, 860)
        self.setMinimumSize(1000, 650)
        self.page = ECDPage(self)
        self.setCentralWidget(self.page)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)

    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor("#F5F6FA"))
    pal.setColor(QPalette.ColorRole.WindowText, QColor("#1F2937"))
    pal.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.Text, QColor("#1F2937"))
    pal.setColor(QPalette.ColorRole.Button, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor("#374151"))
    pal.setColor(QPalette.ColorRole.Highlight, QColor("#4A7BF7"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(pal)

    win = ECDMainWindow()
    win.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
