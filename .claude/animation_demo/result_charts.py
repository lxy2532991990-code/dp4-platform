"""DP4 result visualization — journal-quality matplotlib charts with PyQt animation.

Two-mode design backed by a single ``matplotlib.figure.Figure``:
  • In-app animation: ``QPropertyAnimation`` drives a 0→1 progress, which is
    sliced per-bar with a stagger and an OutCubic easing applied locally.
    Per tick we update each bar's width via ``Rectangle.set_width()`` and
    request ``canvas.draw_idle()`` — no clear-and-redraw, so it stays smooth.
  • Export: ``Figure.savefig()`` at 300 DPI to PNG / SVG / PDF. The same
    Figure is used, so the exported image visually matches the final
    animated frame exactly. Export forces progress=1.0 first so partial
    states never end up on disk.

Color palette: Okabe–Ito (colorblind-safe, recommended by *Nature*).

Drop-in pattern for ``dp4_platform``:

.. code-block:: python

    from dp4_platform.result_charts import CandidateRankingChart

    chart = CandidateRankingChart()
    chart.set_data([("(R,R,S)", 0.823), ("(S,R,S)", 0.084), ...])
    chart.animate_in()              # in-app reveal
    chart.export("ranking.svg")     # publication-ready static
"""
from __future__ import annotations

import matplotlib as mpl
import numpy as np
from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    pyqtProperty,
)
from PyQt6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, MultipleLocator


# ─── Palette ───────────────────────────────────────────────────────────────
# Okabe–Ito 8-color palette. Order matches the original publication
# (Wong, B. Points of view: Color blindness. Nat Methods 8, 441 (2011)).
OKABE_ITO: list[str] = [
    "#E69F00",  # orange
    "#56B4E9",  # sky blue
    "#009E73",  # bluish green
    "#F0E442",  # yellow
    "#0072B2",  # blue
    "#D55E00",  # vermillion
    "#CC79A7",  # reddish purple
    "#000000",  # black
]

WINNER_COLOR = OKABE_ITO[4]  # blue — best contrast on white at small sizes
NEUTRAL_COLOR = "#cdd2db"    # muted gray for non-winners
TEXT_COLOR = "#202124"
AXIS_COLOR = "#444444"
GRID_COLOR = "#e5e7eb"


# ─── Chart widget ──────────────────────────────────────────────────────────
class CandidateRankingChart(QWidget):
    """Horizontal bar chart of DP4 candidate probabilities, animated."""

    DEFAULT_DURATION_MS = 1600

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data: list[tuple[str, float]] = []
        self._progress = 0.0
        self._stagger_frac = 0.30   # last bar starts when global progress = stagger_frac
        self._per_bar_frac = 0.55   # each bar grows over this fraction of total

        self.figure = Figure(figsize=(7.2, 4.0), constrained_layout=True)
        self.figure.patch.set_facecolor("white")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.ax = self.figure.add_subplot(111)
        self._style_axes(self.ax)

        self._bar_artists: list = []
        self._value_labels: list = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(self.DEFAULT_DURATION_MS)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        # Easing handled per-bar; keep the global driver linear so timing math is simple.
        self._anim.setEasingCurve(QEasingCurve.Type.Linear)

    # ─── pyqtProperty plumbing ────────────────────────────────────────────
    def get_progress(self) -> float:
        return self._progress

    def set_progress(self, v: float) -> None:
        self._progress = float(v)
        self._update_bars()

    progress = pyqtProperty(float, fget=get_progress, fset=set_progress)

    # ─── Public API ───────────────────────────────────────────────────────
    def set_data(self, data: list[tuple[str, float]]) -> None:
        """Set candidates as a list of ``(label, probability_in_0_to_1)`` tuples.

        Items are displayed top-to-bottom in the order given.
        """
        self._data = list(data)
        self._draw_static()

    def animate_in(self) -> None:
        """Replay the entrance animation from progress=0."""
        self._anim.stop()
        self.set_progress(0.0)
        self._anim.start()

    def export(self, path: str, dpi: int = 300) -> None:
        """Save the chart to ``path`` at its final (full) state.

        Format inferred from extension by matplotlib: .png .svg .pdf .eps .jpg.
        """
        saved = self._progress
        self._anim.stop()
        self.set_progress(1.0)
        try:
            self.figure.savefig(
                path,
                dpi=dpi,
                bbox_inches="tight",
                facecolor="white",
                edgecolor="none",
            )
        finally:
            # Restore prior visual state without re-triggering animation.
            self.set_progress(saved)

    # ─── Internal: drawing ─────────────────────────────────────────────────
    def _draw_static(self) -> None:
        """Render axes, ticks, gridlines, and zero-width bars + faded labels."""
        self.ax.clear()
        self._style_axes(self.ax)

        if not self._data:
            self.canvas.draw_idle()
            return

        labels = [d[0] for d in self._data]
        values = [float(d[1]) for d in self._data]
        positions = list(range(len(labels)))

        winner_idx = max(range(len(values)), key=lambda i: values[i])
        colors = [
            WINNER_COLOR if i == winner_idx else NEUTRAL_COLOR
            for i in range(len(values))
        ]

        self._bar_artists = list(
            self.ax.barh(
                positions,
                [0.0] * len(values),
                color=colors,
                height=0.65,
                edgecolor="none",
                zorder=2,
            )
        )

        self._value_labels = []
        for i, v in enumerate(values):
            text = self.ax.text(
                0.0,
                i,
                f"{v * 100:.1f}%",
                va="center",
                ha="left",
                fontsize=10,
                color=TEXT_COLOR,
                fontweight="600",
                alpha=0.0,
                zorder=3,
            )
            self._value_labels.append(text)

        self.ax.set_yticks(positions)
        self.ax.set_yticklabels(labels, color=TEXT_COLOR)
        self.ax.invert_yaxis()  # winner at top
        self.ax.set_xlim(0.0, max(1.0, max(values) * 1.08))
        self.ax.set_xlabel("DP4 probability", labelpad=8, color=TEXT_COLOR)
        self.ax.xaxis.set_major_locator(MultipleLocator(0.2))
        self.ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _pos: f"{x * 100:.0f}%"))

        self.ax.set_title(
            "Candidate ranking",
            loc="left",
            pad=10,
            fontsize=13,
            fontweight=600,
            color=TEXT_COLOR,
        )

        self.ax.grid(axis="x", linestyle="--", linewidth=0.6, color=GRID_COLOR, zorder=0)
        self.ax.set_axisbelow(True)

        self.canvas.draw_idle()

    def _update_bars(self) -> None:
        if not self._bar_artists:
            return
        n = len(self._bar_artists)
        denom = max(n - 1, 1)
        for i, bar in enumerate(self._bar_artists):
            target = self._data[i][1]
            stagger_start = (i / denom) * self._stagger_frac if n > 1 else 0.0
            local = (self._progress - stagger_start) / max(self._per_bar_frac, 1e-3)
            local = max(0.0, min(1.0, local))
            eased = self._ease_out_cubic(local)
            bar.set_width(target * eased)

            label = self._value_labels[i]
            label.set_x(target * eased + 0.012)
            label.set_alpha(eased)
        self.canvas.draw_idle()

    @staticmethod
    def _ease_out_cubic(t: float) -> float:
        t = max(0.0, min(1.0, t))
        return 1.0 - (1.0 - t) ** 3

    @staticmethod
    def _style_axes(ax) -> None:
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        for name in ("left", "bottom"):
            ax.spines[name].set_color(AXIS_COLOR)
            ax.spines[name].set_linewidth(0.8)
        ax.tick_params(
            direction="out",
            length=3.0,
            width=0.8,
            labelsize=10,
            colors=AXIS_COLOR,
            pad=4,
        )


# ─── NMR scatter chart ────────────────────────────────────────────────────
class NMRScatterChart(QWidget):
    """Computed vs experimental NMR shifts, colored by candidate.

    Animation phases:
      • 0% → 20%   : y=x reference line fades in
      • 20% → 90%  : per-candidate point groups fade in with stagger
      • 90% → 100% : R² / MAE annotation block + legend fade in
    """

    DEFAULT_DURATION_MS = 1800

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._candidates: list[tuple[str, np.ndarray, np.ndarray]] = []
        self._progress = 0.0
        self._line_phase_end = 0.20
        self._candidate_phase_end = 0.90
        self._stagger_frac = 0.30
        self._title = "Computed vs experimental ¹³C shifts"
        self._x_label = "Experimental shift (ppm)"
        self._y_label = "Computed shift (ppm)"

        self.figure = Figure(figsize=(6.0, 5.6), constrained_layout=True)
        self.figure.patch.set_facecolor("white")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.ax = self.figure.add_subplot(111)
        CandidateRankingChart._style_axes(self.ax)

        self._ref_line = None
        self._scatters: list = []
        self._stat_text = None
        self._legend = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(self.DEFAULT_DURATION_MS)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.Linear)

    # ─── pyqtProperty plumbing
    def get_progress(self) -> float:
        return self._progress

    def set_progress(self, v: float) -> None:
        self._progress = float(v)
        self._update_artists()

    progress = pyqtProperty(float, fget=get_progress, fset=set_progress)

    # ─── Public API
    def set_data(self, candidates: list[tuple[str, "np.ndarray | list[float]", "np.ndarray | list[float]"]]) -> None:
        """``candidates``: list of ``(label, x_experimental, y_computed)``.

        Both arrays must be the same length within a candidate; lengths can
        differ across candidates (sparse atom subsets are allowed).
        """
        self._candidates = [
            (lbl, np.asarray(x, dtype=float), np.asarray(y, dtype=float))
            for lbl, x, y in candidates
        ]
        self._draw_static()

    def set_axis_labels(self, title: str | None = None, x_label: str | None = None, y_label: str | None = None) -> None:
        if title is not None:
            self._title = title
        if x_label is not None:
            self._x_label = x_label
        if y_label is not None:
            self._y_label = y_label
        if self._candidates:
            self._draw_static()

    def animate_in(self) -> None:
        self._anim.stop()
        self.set_progress(0.0)
        self._anim.start()

    def export(self, path: str, dpi: int = 300) -> None:
        saved = self._progress
        self._anim.stop()
        self.set_progress(1.0)
        try:
            self.figure.savefig(
                path, dpi=dpi, bbox_inches="tight",
                facecolor="white", edgecolor="none",
            )
        finally:
            self.set_progress(saved)

    # ─── Internal
    def _draw_static(self) -> None:
        self.ax.clear()
        CandidateRankingChart._style_axes(self.ax)
        self._ref_line = None
        self._scatters = []
        self._stat_text = None
        self._legend = None

        if not self._candidates:
            self.canvas.draw_idle()
            return

        all_x = np.concatenate([c[1] for c in self._candidates])
        all_y = np.concatenate([c[2] for c in self._candidates])
        lo = float(min(all_x.min(), all_y.min()))
        hi = float(max(all_x.max(), all_y.max()))
        margin = max((hi - lo) * 0.08, 1.0)
        ax_lo, ax_hi = lo - margin, hi + margin
        self.ax.set_xlim(ax_lo, ax_hi)
        self.ax.set_ylim(ax_lo, ax_hi)
        self.ax.set_aspect("equal", adjustable="box")

        (self._ref_line,) = self.ax.plot(
            [ax_lo, ax_hi], [ax_lo, ax_hi],
            "--", color="#9ca3af", linewidth=1.0, alpha=0.0, zorder=1,
            label="y = x",
        )

        for i, (lbl, x, y) in enumerate(self._candidates):
            color = OKABE_ITO[i % len(OKABE_ITO)]
            sc = self.ax.scatter(
                x, y,
                color=color,
                s=44,
                alpha=0.0,
                edgecolor="white",
                linewidth=0.8,
                label=lbl,
                zorder=2 + i,
            )
            self._scatters.append(sc)

        best_idx, best_mae, best_r2 = self._best_fit_stats()
        best_label = self._candidates[best_idx][0]
        stat_text = (
            f"Best fit — {best_label}\n"
            f"MAE = {best_mae:.2f} ppm\n"
            f"R² = {best_r2:.4f}"
        )
        self._stat_text = self.ax.text(
            0.03, 0.97, stat_text,
            transform=self.ax.transAxes,
            ha="left", va="top",
            fontsize=10, color=TEXT_COLOR,
            family="monospace", fontweight=500,
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                      edgecolor="#d9dde5", linewidth=0.6),
            alpha=0.0,
        )

        self._legend = self.ax.legend(
            loc="lower right", frameon=True,
            fontsize=10, facecolor="white", edgecolor="#d9dde5",
            framealpha=0.0,
        )
        self._legend.set_visible(False)
        for text in self._legend.get_texts():
            text.set_alpha(0.0)
        for handle in getattr(self._legend, "legend_handles", []):
            try:
                handle.set_alpha(0.0)
            except Exception:
                pass

        self.ax.set_title(self._title, loc="left", pad=10, fontsize=13,
                          fontweight=600, color=TEXT_COLOR)
        self.ax.set_xlabel(self._x_label, labelpad=8, color=TEXT_COLOR)
        self.ax.set_ylabel(self._y_label, labelpad=8, color=TEXT_COLOR)
        self.ax.grid(True, linestyle="--", linewidth=0.5, color=GRID_COLOR, zorder=0)
        self.ax.set_axisbelow(True)

        self.canvas.draw_idle()

    def _best_fit_stats(self) -> tuple[int, float, float]:
        """Return (best_index, mae, r2) for the candidate with lowest MAE."""
        best = (0, float("inf"), 0.0)
        for i, (_lbl, x, y) in enumerate(self._candidates):
            if x.size == 0:
                continue
            mae = float(np.mean(np.abs(y - x)))
            ss_res = float(np.sum((y - x) ** 2))
            ss_tot = float(np.sum((x - np.mean(x)) ** 2))
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-9 else 0.0
            if mae < best[1]:
                best = (i, mae, r2)
        return best

    def _update_artists(self) -> None:
        if not self._candidates:
            return
        p = self._progress

        line_t = max(0.0, min(1.0, p / max(self._line_phase_end, 1e-3)))
        if self._ref_line is not None:
            self._ref_line.set_alpha(0.85 * self._ease_out_cubic(line_t))

        phase2_p = max(0.0, p - self._line_phase_end)
        phase2_window = max(self._candidate_phase_end - self._line_phase_end, 1e-3)
        n = len(self._scatters)
        denom = max(n - 1, 1)
        per_window = (1.0 - self._stagger_frac) * phase2_window
        for i, sc in enumerate(self._scatters):
            start_offset = (i / denom) * (self._stagger_frac * phase2_window) if n > 1 else 0
            local_t = (phase2_p - start_offset) / max(per_window, 1e-3)
            local_t = max(0.0, min(1.0, local_t))
            sc.set_alpha(0.85 * self._ease_out_cubic(local_t))

        phase3_t = max(0.0, min(1.0,
            (p - self._candidate_phase_end) / max(1.0 - self._candidate_phase_end, 1e-3)
        ))
        eased3 = self._ease_out_cubic(phase3_t)
        if self._stat_text is not None:
            self._stat_text.set_alpha(eased3)
        if self._legend is not None:
            visible = phase3_t > 0.01
            self._legend.set_visible(visible)
            self._legend.get_frame().set_alpha(0.95 * eased3)
            for text in self._legend.get_texts():
                text.set_alpha(eased3)
            for handle in getattr(self._legend, "legend_handles", []):
                try:
                    handle.set_alpha(eased3)
                except Exception:
                    pass

        self.canvas.draw_idle()

    @staticmethod
    def _ease_out_cubic(t: float) -> float:
        t = max(0.0, min(1.0, t))
        return 1.0 - (1.0 - t) ** 3


# ─── Per-atom deviation heatmap ───────────────────────────────────────────
class AtomDeviationHeatmap(QWidget):
    """Heatmap of |Δδ| per (candidate, atom). Diagonal-wipe reveal.

    Cells "warm up" along the leading anti-diagonal: each cell tweens
    from value 0 (pale colormap start) to its true value over a brief
    per-cell window, with the corresponding text fading in.
    """

    DEFAULT_DURATION_MS = 1900

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._matrix: np.ndarray | None = None
        self._candidate_labels: list[str] = []
        self._atom_labels: list[str] = []
        self._winner_idx: int = -1
        self._progress: float = 0.0
        self._cell_window: float = 0.18  # per-cell fade-up window (fraction of total)

        self.figure = Figure(figsize=(7.4, 4.0), constrained_layout=True)
        self.figure.patch.set_facecolor("white")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.ax = self.figure.add_subplot(111)

        self._im = None
        self._cell_texts: list = []
        self._colorbar = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(self.DEFAULT_DURATION_MS)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.Linear)

    def get_progress(self) -> float:
        return self._progress

    def set_progress(self, v: float) -> None:
        self._progress = float(v)
        self._update_cells()

    progress = pyqtProperty(float, fget=get_progress, fset=set_progress)

    # ─── Public API
    def set_data(
        self,
        matrix: "np.ndarray | list[list[float]]",
        candidate_labels: list[str],
        atom_labels: list[str],
        winner_index: int | None = None,
    ) -> None:
        self._matrix = np.asarray(matrix, dtype=float)
        self._candidate_labels = list(candidate_labels)
        self._atom_labels = list(atom_labels)
        if winner_index is None:
            winner_index = int(np.argmin(self._matrix.mean(axis=1)))
        self._winner_idx = int(winner_index)
        self._draw_static()

    def animate_in(self) -> None:
        self._anim.stop()
        self.set_progress(0.0)
        self._anim.start()

    def export(self, path: str, dpi: int = 300) -> None:
        saved = self._progress
        self._anim.stop()
        self.set_progress(1.0)
        try:
            self.figure.savefig(
                path, dpi=dpi, bbox_inches="tight",
                facecolor="white", edgecolor="none",
            )
        finally:
            self.set_progress(saved)

    # ─── Internal
    def _draw_static(self) -> None:
        if self._colorbar is not None:
            try:
                self._colorbar.remove()
            except Exception:
                pass
            self._colorbar = None
        self.ax.clear()
        self._cell_texts = []

        if self._matrix is None or self._matrix.size == 0:
            self.canvas.draw_idle()
            return

        rows, cols = self._matrix.shape
        vmax = float(np.nanmax(self._matrix))

        cmap = mpl.colormaps["YlOrRd"].copy()
        cmap.set_bad(color="#fafbfc")

        nan_matrix = np.full_like(self._matrix, np.nan)
        self._im = self.ax.imshow(
            nan_matrix,
            cmap=cmap,
            vmin=0.0,
            vmax=vmax,
            aspect="auto",
            interpolation="nearest",
        )

        self.ax.set_xticks(range(cols))
        self.ax.set_xticklabels(self._atom_labels, color=TEXT_COLOR, rotation=0)
        self.ax.set_yticks(range(rows))
        self.ax.set_yticklabels(self._candidate_labels, color=TEXT_COLOR)
        for i, ticklabel in enumerate(self.ax.get_yticklabels()):
            if i == self._winner_idx:
                ticklabel.set_fontweight("bold")
                ticklabel.set_color(WINNER_COLOR)

        for r in range(rows):
            for c in range(cols):
                v = float(self._matrix[r, c])
                txt_color = "white" if v > vmax * 0.6 else TEXT_COLOR
                t = self.ax.text(
                    c, r, f"{v:.1f}",
                    ha="center", va="center",
                    fontsize=9, color=txt_color, fontweight=500,
                    alpha=0.0,
                )
                self._cell_texts.append(t)

        self.ax.spines["top"].set_visible(False)
        self.ax.spines["right"].set_visible(False)
        for name in ("left", "bottom"):
            self.ax.spines[name].set_color(AXIS_COLOR)
            self.ax.spines[name].set_linewidth(0.8)
        self.ax.tick_params(
            direction="out", length=0, width=0.8,
            labelsize=10, colors=AXIS_COLOR, pad=4,
        )

        self.ax.set_title(
            "Per-atom |Δδ| deviation (ppm)",
            loc="left", pad=10, fontsize=13, fontweight=600, color=TEXT_COLOR,
        )

        self._colorbar = self.figure.colorbar(
            self._im, ax=self.ax, fraction=0.04, pad=0.02, shrink=0.85,
        )
        self._colorbar.outline.set_edgecolor(AXIS_COLOR)
        self._colorbar.outline.set_linewidth(0.8)
        self._colorbar.ax.tick_params(
            direction="out", length=3, width=0.8,
            labelsize=9, colors=AXIS_COLOR,
        )
        self._colorbar.set_label("|Δδ| (ppm)", color=TEXT_COLOR, fontsize=10)

        self.canvas.draw_idle()

    def _update_cells(self) -> None:
        if self._matrix is None or self._im is None:
            return
        rows, cols = self._matrix.shape
        max_diag = max(rows + cols - 2, 1)
        partial = np.full_like(self._matrix, np.nan)

        for r in range(rows):
            for c in range(cols):
                cell_diag_norm = (r + c) / max_diag
                start = cell_diag_norm * (1.0 - self._cell_window)
                local_t = (self._progress - start) / max(self._cell_window, 1e-3)
                local_t = max(0.0, min(1.0, local_t))
                if local_t > 0:
                    eased = self._ease_out_cubic(local_t)
                    partial[r, c] = self._matrix[r, c] * eased
                txt = self._cell_texts[r * cols + c]
                txt.set_alpha(self._ease_out_cubic(local_t))

        self._im.set_data(partial)
        self.canvas.draw_idle()

    @staticmethod
    def _ease_out_cubic(t: float) -> float:
        t = max(0.0, min(1.0, t))
        return 1.0 - (1.0 - t) ** 3
