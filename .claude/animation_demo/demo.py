"""DP4 Platform — GUI Animation Demo Sandbox.

Self-contained PyQt6 showcase of interaction-animation patterns that fit your
existing PyQt code style (matches ``dp4_platform/gui.py`` QSS conventions).

Each pattern lives in its own widget class so you can copy them into
``dp4_platform`` or ``ecd_platform`` without rewiring anything.

Run from this folder via:
    .\\run.ps1
or directly:
    "C:\\Users\\LXY\\Documents\\code\\dp4-platform\\.venv\\Scripts\\python.exe" demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSequentialAnimationGroup,
    QSize,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from result_charts import (
    AtomDeviationHeatmap,
    CandidateRankingChart,
    NMRScatterChart,
)


# ════════════════════════════════════════════════════════════════════════════
#  Theme — mirrors dp4_platform/gui.py palette
# ════════════════════════════════════════════════════════════════════════════
COLOR_BG = "#f4f5f8"
COLOR_CARD = "#ffffff"
COLOR_BORDER = "#d9dde5"
COLOR_BORDER_SOFT = "#d0d5dd"
COLOR_TEXT = "#202124"
COLOR_TEXT_MUTED = "#6b7280"
COLOR_TEXT_FAINT = "#7b8492"
COLOR_ACCENT = "#4A7BF7"
COLOR_ACCENT_SOFT = "#e8f0fe"
COLOR_HOVER = "#f4f7ff"


# ════════════════════════════════════════════════════════════════════════════
#  Demo 1 — Sliding QStackedWidget for page transitions
#
#  Patterns: animate two QPropertyAnimation on QPoint pos in parallel.
#  Drop-in replacement for QStackedWidget — call slideTo() instead of
#  setCurrentIndex(). Use direction="forward" / "backward" for nav semantics.
# ════════════════════════════════════════════════════════════════════════════
class SlidingStackedWidget(QStackedWidget):
    """QStackedWidget that horizontally slides between pages.

    Drop-in: replace ``QStackedWidget`` with this class and call
    ``slideTo(index, direction)`` instead of ``setCurrentIndex(index)``.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._duration_ms = 360
        self._animating = False
        self._anim_group: QParallelAnimationGroup | None = None

    def slideTo(self, index: int, direction: str = "forward") -> None:
        if self._animating:
            return
        if index == self.currentIndex() or not (0 <= index < self.count()):
            return

        old = self.currentWidget()
        new = self.widget(index)
        w = self.frameRect().width()
        h = self.frameRect().height()

        sign = 1 if direction == "forward" else -1
        new.setGeometry(0, 0, w, h)
        new.move(QPoint(sign * w, 0))
        new.show()
        new.raise_()

        anim_old = self._slide_anim(old, QPoint(0, 0), QPoint(-sign * w, 0))
        anim_new = self._slide_anim(new, QPoint(sign * w, 0), QPoint(0, 0))

        group = QParallelAnimationGroup(self)
        group.addAnimation(anim_old)
        group.addAnimation(anim_new)
        group.finished.connect(lambda: self._on_slide_done(index, old))
        self._anim_group = group
        self._animating = True
        group.start()

    def _slide_anim(self, widget: QWidget, start: QPoint, end: QPoint) -> QPropertyAnimation:
        anim = QPropertyAnimation(widget, b"pos", self)
        anim.setDuration(self._duration_ms)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(start)
        anim.setEndValue(end)
        return anim

    def _on_slide_done(self, index: int, old: QWidget) -> None:
        old.move(0, 0)
        super().setCurrentIndex(index)
        self._animating = False


class PageTransitionDemo(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setSpacing(18)

        intro = QLabel(
            "QStackedWidget that slides horizontally between pages. "
            "Use it as the workflow stepper or the home → module-detail navigation."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        outer.addWidget(intro)

        self.stack = SlidingStackedWidget()
        self.stack.setMinimumHeight(280)
        self.stack.setStyleSheet(
            f"SlidingStackedWidget {{ background: {COLOR_CARD}; "
            f"border: 1px solid {COLOR_BORDER}; border-radius: 18px; }}"
        )

        for index, (title, body, accent) in enumerate(
            [
                ("Step 1 — Discover candidates", "Scan the project folder and pair Gaussian/ORCA outputs.", "#4A7BF7"),
                ("Step 2 — Configure DP4", "Pick reference solvent, weighting strategy, NMR options.", "#10b981"),
                ("Step 3 — Run & report", "Compute candidate probabilities and export the report.", "#f59e0b"),
            ]
        ):
            self.stack.addWidget(self._build_page(index + 1, title, body, accent))

        outer.addWidget(self.stack, 1)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.back_btn = QPushButton("← Back")
        self.next_btn = QPushButton("Next →")
        for b in (self.back_btn, self.next_btn):
            b.setObjectName("PrimaryButton")
        self.back_btn.clicked.connect(self._go_back)
        self.next_btn.clicked.connect(self._go_next)
        controls.addStretch()
        controls.addWidget(self.back_btn)
        controls.addWidget(self.next_btn)
        outer.addLayout(controls)
        self._refresh_buttons()

    def _build_page(self, num: int, title: str, body: str, accent: str) -> QWidget:
        page = QWidget()
        page.setAutoFillBackground(True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(36, 32, 36, 32)
        layout.setSpacing(14)

        bar = QFrame()
        bar.setFixedSize(56, 6)
        bar.setStyleSheet(f"background: {accent}; border-radius: 3px;")
        layout.addWidget(bar)

        step = QLabel(f"Page {num}")
        step.setStyleSheet(f"color: {COLOR_TEXT_FAINT}; font-size: 12px; font-weight: 600;")
        layout.addWidget(step)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size: 22px; font-weight: 700;")
        layout.addWidget(title_lbl)

        body_lbl = QLabel(body)
        body_lbl.setWordWrap(True)
        body_lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 14px;")
        layout.addWidget(body_lbl)

        layout.addStretch(1)
        return page

    def _go_next(self) -> None:
        idx = self.stack.currentIndex()
        if idx < self.stack.count() - 1:
            self.stack.slideTo(idx + 1, "forward")
            self._refresh_buttons(idx + 1)

    def _go_back(self) -> None:
        idx = self.stack.currentIndex()
        if idx > 0:
            self.stack.slideTo(idx - 1, "backward")
            self._refresh_buttons(idx - 1)

    def _refresh_buttons(self, target_idx: int | None = None) -> None:
        idx = self.stack.currentIndex() if target_idx is None else target_idx
        self.back_btn.setEnabled(idx > 0)
        self.next_btn.setEnabled(idx < self.stack.count() - 1)


# ════════════════════════════════════════════════════════════════════════════
#  Demo 2 — Collapsible section with chevron rotation
#
#  Patterns: tween maximumHeight on the content frame; pyqtProperty-driven
#  rotation on the chevron icon. Sized to siblings so multiple sections stack.
# ════════════════════════════════════════════════════════════════════════════
class _ChevronIcon(QWidget):
    """Hand-painted chevron with an animatable rotation property."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self._rotation = 0.0

    def get_rotation(self) -> float:
        return self._rotation

    def set_rotation(self, value: float) -> None:
        self._rotation = float(value)
        self.update()

    rotation = pyqtProperty(float, fget=get_rotation, fset=set_rotation)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(self._rotation)
        pen = QPen(QColor(COLOR_TEXT_FAINT), 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        s = 4.0
        painter.drawLine(int(-s), int(-s / 2), 0, int(s / 2))
        painter.drawLine(0, int(s / 2), int(s), int(-s / 2))


class CollapsibleSection(QWidget):
    """A section with a clickable header and a content area that animates open/closed."""

    toggled = pyqtSignal(bool)

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.is_open = False
        self._anim_group: QParallelAnimationGroup | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = QFrame()
        self.header.setObjectName("CollapsibleHeader")
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setFixedHeight(48)
        self.header.mouseReleaseEvent = lambda _e: self._toggle()  # type: ignore[assignment]
        h_layout = QHBoxLayout(self.header)
        h_layout.setContentsMargins(20, 0, 20, 0)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-weight: 600; font-size: 14px; color: #202124;")
        h_layout.addWidget(title_lbl)
        h_layout.addStretch()
        self.chevron = _ChevronIcon()
        h_layout.addWidget(self.chevron)
        outer.addWidget(self.header)

        self.content = QFrame()
        self.content.setObjectName("CollapsibleContent")
        self.content.setMaximumHeight(0)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(20, 6, 20, 18)
        self.content_layout.setSpacing(8)
        outer.addWidget(self.content)

    def add_content(self, widget: QWidget) -> None:
        self.content_layout.addWidget(widget)

    def _natural_height(self) -> int:
        return self.content_layout.sizeHint().height() + self.content_layout.contentsMargins().top() + self.content_layout.contentsMargins().bottom()

    def _toggle(self) -> None:
        self.is_open = not self.is_open
        target_h = self._natural_height() if self.is_open else 0
        target_rot = 180.0 if self.is_open else 0.0

        if self._anim_group is not None:
            self._anim_group.stop()

        h_anim = QPropertyAnimation(self.content, b"maximumHeight", self)
        h_anim.setDuration(280)
        h_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        h_anim.setStartValue(self.content.maximumHeight())
        h_anim.setEndValue(target_h)

        r_anim = QPropertyAnimation(self.chevron, b"rotation", self)
        r_anim.setDuration(280)
        r_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        r_anim.setStartValue(self.chevron.rotation)
        r_anim.setEndValue(target_rot)

        group = QParallelAnimationGroup(self)
        group.addAnimation(h_anim)
        group.addAnimation(r_anim)
        self._anim_group = group
        group.start()
        self.toggled.emit(self.is_open)


class CollapsibleDemo(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setSpacing(18)

        intro = QLabel(
            "Smooth expand / collapse with a rotating chevron. Useful for the candidate "
            "settings panel, advanced options, or grouped CLI parameters."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        outer.addWidget(intro)

        sections_holder = QFrame()
        sections_holder.setObjectName("SectionsHolder")
        sections_holder.setStyleSheet(
            f"#SectionsHolder {{ background: {COLOR_CARD}; "
            f"border: 1px solid {COLOR_BORDER}; border-radius: 14px; }}"
        )
        sh_layout = QVBoxLayout(sections_holder)
        sh_layout.setContentsMargins(0, 0, 0, 0)
        sh_layout.setSpacing(0)

        for title, body in [
            (
                "Reference solvent",
                "Set the reference solvent used to align the candidate NMR predictions "
                "with the experimental spectrum. Defaults to chloroform-d.",
            ),
            (
                "Weighting strategy",
                "Choose how computational candidates are weighted: equal, "
                "Boltzmann (with energy file), or custom per-candidate weights.",
            ),
            (
                "Advanced overrides",
                "Tweak DP4 parameters such as scaling, expectation broadening, "
                "and the prior distribution. Most users won't need these.",
            ),
        ]:
            section = CollapsibleSection(title)
            body_lbl = QLabel(body)
            body_lbl.setWordWrap(True)
            body_lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 13px;")
            section.add_content(body_lbl)
            sh_layout.addWidget(section)
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet(f"background: {COLOR_BORDER}; max-height: 1px;")
            sh_layout.addWidget(sep)

        outer.addWidget(sections_holder)
        outer.addStretch(1)


# ════════════════════════════════════════════════════════════════════════════
#  Demo 3 — Animated status badge
#
#  Patterns: pyqtProperty-driven QColor and scale; sequential pulse; parallel
#  group combining color tween + bounce. paintEvent draws a pill manually so
#  no QSS reparse churn during animation.
# ════════════════════════════════════════════════════════════════════════════
class AnimatedStatusBadge(QWidget):
    STATES: dict[str, dict[str, object]] = {
        "pending":  {"text": "Pending",  "bg": QColor("#eef1f5"), "fg": QColor("#5b6470")},
        "running":  {"text": "Running",  "bg": QColor("#dbe8ff"), "fg": QColor("#1947a8")},
        "success":  {"text": "Success",  "bg": QColor("#d8f3dc"), "fg": QColor("#2b7a3a")},
        "failed":   {"text": "Failed",   "bg": QColor("#ffd6d6"), "fg": QColor("#a51d1d")},
    }

    def __init__(self, initial_state: str = "pending", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = initial_state
        self._bg_color = QColor(self.STATES[self.state]["bg"])  # type: ignore[arg-type]
        self._fg_color = QColor(self.STATES[self.state]["fg"])  # type: ignore[arg-type]
        self._scale = 1.0
        self._anim: QParallelAnimationGroup | None = None
        self.setMinimumSize(124, 36)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def get_bg(self) -> QColor:
        return self._bg_color

    def set_bg(self, c: QColor) -> None:
        self._bg_color = QColor(c)
        self.update()

    bg_color = pyqtProperty(QColor, fget=get_bg, fset=set_bg)

    def get_fg(self) -> QColor:
        return self._fg_color

    def set_fg(self, c: QColor) -> None:
        self._fg_color = QColor(c)
        self.update()

    fg_color = pyqtProperty(QColor, fget=get_fg, fset=set_fg)

    def get_scale(self) -> float:
        return self._scale

    def set_scale(self, v: float) -> None:
        self._scale = float(v)
        self.update()

    scale = pyqtProperty(float, fget=get_scale, fset=set_scale)

    def setState(self, new_state: str) -> None:
        if new_state not in self.STATES or new_state == self.state:
            return
        target = self.STATES[new_state]

        if self._anim is not None:
            self._anim.stop()

        bg_anim = QPropertyAnimation(self, b"bg_color", self)
        bg_anim.setDuration(220)
        bg_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        bg_anim.setEndValue(target["bg"])

        fg_anim = QPropertyAnimation(self, b"fg_color", self)
        fg_anim.setDuration(220)
        fg_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        fg_anim.setEndValue(target["fg"])

        pulse_up = QPropertyAnimation(self, b"scale", self)
        pulse_up.setDuration(120)
        pulse_up.setStartValue(1.0)
        pulse_up.setEndValue(1.08)
        pulse_up.setEasingCurve(QEasingCurve.Type.OutQuad)
        pulse_down = QPropertyAnimation(self, b"scale", self)
        pulse_down.setDuration(160)
        pulse_down.setStartValue(1.08)
        pulse_down.setEndValue(1.0)
        pulse_down.setEasingCurve(QEasingCurve.Type.InOutQuad)
        pulse = QSequentialAnimationGroup(self)
        pulse.addAnimation(pulse_up)
        pulse.addAnimation(pulse_down)

        group = QParallelAnimationGroup(self)
        group.addAnimation(bg_anim)
        group.addAnimation(fg_anim)
        group.addAnimation(pulse)
        self._anim = group
        self.state = new_state
        group.start()

    def sizeHint(self) -> QSize:
        return QSize(124, 36)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = self.width() / 2
        cy = self.height() / 2
        painter.translate(cx, cy)
        painter.scale(self._scale, self._scale)
        painter.translate(-cx, -cy)

        rect = QRectF(self.rect()).adjusted(2, 4, -2, -4)
        radius = rect.height() / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._bg_color)
        painter.drawRoundedRect(rect, radius, radius)

        painter.setPen(self._fg_color)
        font = QFont(painter.font())
        font.setBold(True)
        font.setPixelSize(13)
        painter.setFont(font)
        text = str(self.STATES[self.state]["text"])
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)


class StatusBadgeDemo(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setSpacing(18)

        intro = QLabel(
            "Pill that color-tweens on state change with a subtle scale pulse. "
            "Apply per-candidate row to broadcast Pending → Running → Success/Failed."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        outer.addWidget(intro)

        card = QFrame()
        card.setObjectName("BadgeCard")
        card.setStyleSheet(
            f"#BadgeCard {{ background: {COLOR_CARD}; "
            f"border: 1px solid {COLOR_BORDER}; border-radius: 14px; }}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 28, 28, 28)
        card_layout.setSpacing(20)

        rows: list[tuple[str, AnimatedStatusBadge]] = []
        for label_text in ["Candidate A — (R,R,S)", "Candidate B — (S,R,S)", "Candidate C — (R,S,R)"]:
            row = QHBoxLayout()
            label = QLabel(label_text)
            label.setStyleSheet("font-size: 14px; font-weight: 500;")
            badge = AnimatedStatusBadge("pending")
            row.addWidget(label, 1)
            row.addWidget(badge)
            card_layout.addLayout(row)
            rows.append((label_text, badge))

        outer.addWidget(card)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(QLabel("Try transitions:"))
        for label_text, target in [
            ("→ All Running", "running"),
            ("→ All Success", "success"),
            ("→ All Failed", "failed"),
            ("Reset", "pending"),
        ]:
            btn = QPushButton(label_text)
            btn.setObjectName("PrimaryButton" if target != "pending" else "GhostButton")
            btn.clicked.connect(lambda _checked=False, st=target: [b.setState(st) for _, b in rows])  # type: ignore[misc]
            controls.addWidget(btn)
        controls.addStretch(1)
        outer.addLayout(controls)
        outer.addStretch(1)


# ════════════════════════════════════════════════════════════════════════════
#  Demo 4 — Loading indicators
#
#  Patterns: looping QPropertyAnimation on a custom int "angle" property
#  (CircularSpinner), and a paintEvent-driven shimmer pass overlaid on a
#  QPropertyAnimation-driven progress (ShimmerProgressBar).
# ════════════════════════════════════════════════════════════════════════════
class CircularSpinner(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(48, 48)
        self._angle = 0
        self._anim = QPropertyAnimation(self, b"angle", self)
        self._anim.setDuration(900)
        self._anim.setStartValue(0)
        self._anim.setEndValue(360)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.Type.Linear)

    def get_angle(self) -> int:
        return self._angle

    def set_angle(self, v: int) -> None:
        self._angle = int(v)
        self.update()

    angle = pyqtProperty(int, fget=get_angle, fset=set_angle)

    def start(self) -> None:
        if self._anim.state() != QPropertyAnimation.State.Running:
            self._anim.start()

    def stop(self) -> None:
        self._anim.stop()
        self._angle = 0
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() / 2
        cy = self.height() / 2
        painter.translate(cx, cy)
        painter.rotate(self._angle)
        pen = QPen()
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setWidth(3)
        for i in range(12):
            alpha = int(255 * (i + 1) / 12)
            pen.setColor(QColor(74, 123, 247, alpha))
            painter.setPen(pen)
            painter.save()
            painter.rotate(i * 30)
            painter.drawLine(0, -16, 0, -10)
            painter.restore()


class ShimmerProgressBar(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._progress = 0.0
        self._shimmer_x = -0.3
        self.setFixedHeight(8)
        self.setMinimumWidth(160)

        self._prog_anim = QPropertyAnimation(self, b"progress", self)
        self._prog_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._shim_anim = QPropertyAnimation(self, b"shimmer", self)
        self._shim_anim.setDuration(1400)
        self._shim_anim.setStartValue(-0.3)
        self._shim_anim.setEndValue(1.3)
        self._shim_anim.setLoopCount(-1)

    def get_progress(self) -> float:
        return self._progress

    def set_progress(self, v: float) -> None:
        self._progress = max(0.0, min(1.0, float(v)))
        self.update()

    progress = pyqtProperty(float, fget=get_progress, fset=set_progress)

    def get_shimmer(self) -> float:
        return self._shimmer_x

    def set_shimmer(self, v: float) -> None:
        self._shimmer_x = float(v)
        self.update()

    shimmer = pyqtProperty(float, fget=get_shimmer, fset=set_shimmer)

    def setProgress(self, value: float, duration_ms: int = 400) -> None:
        self._prog_anim.stop()
        self._prog_anim.setDuration(duration_ms)
        self._prog_anim.setStartValue(self._progress)
        self._prog_anim.setEndValue(max(0.0, min(1.0, value)))
        self._prog_anim.start()

    def startShimmer(self) -> None:
        if self._shim_anim.state() != QPropertyAnimation.State.Running:
            self._shim_anim.start()

    def stopShimmer(self) -> None:
        self._shim_anim.stop()
        self._shimmer_x = -0.3
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        radius = rect.height() / 2

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e8eaef"))
        painter.drawRoundedRect(rect, radius, radius)

        if self._progress <= 0:
            return

        fill_w = rect.width() * self._progress
        fill_rect = QRectF(0, 0, fill_w, rect.height())
        painter.setBrush(QColor(COLOR_ACCENT))
        painter.setClipRect(fill_rect)
        painter.drawRoundedRect(rect, radius, radius)

        if self._shim_anim.state() == QPropertyAnimation.State.Running:
            shimmer_x = rect.width() * self._shimmer_x
            grad = QLinearGradient(shimmer_x - 40, 0, shimmer_x + 40, 0)
            grad.setColorAt(0.0, QColor(255, 255, 255, 0))
            grad.setColorAt(0.5, QColor(255, 255, 255, 110))
            grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setBrush(grad)
            painter.drawRoundedRect(rect, radius, radius)


class LoadingIndicatorsDemo(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setSpacing(18)

        intro = QLabel(
            "Two patterns: a custom-painted spinner driven by a looping QPropertyAnimation, "
            "and a progress bar with an animated shimmer overlay. Both are start/stoppable."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        outer.addWidget(intro)

        card = QFrame()
        card.setObjectName("LoadingCard")
        card.setStyleSheet(
            f"#LoadingCard {{ background: {COLOR_CARD}; "
            f"border: 1px solid {COLOR_BORDER}; border-radius: 14px; }}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 28, 28, 28)
        card_layout.setSpacing(28)

        spinner_row = QHBoxLayout()
        spinner_row.setSpacing(20)
        self.spinner = CircularSpinner()
        spinner_row.addWidget(self.spinner)
        spinner_label = QLabel("Computing DP4 probabilities…")
        spinner_label.setStyleSheet("font-size: 14px;")
        spinner_row.addWidget(spinner_label)
        spinner_row.addStretch(1)
        spinner_btn_start = QPushButton("Start")
        spinner_btn_start.setObjectName("PrimaryButton")
        spinner_btn_stop = QPushButton("Stop")
        spinner_btn_stop.setObjectName("GhostButton")
        spinner_btn_start.clicked.connect(self.spinner.start)
        spinner_btn_stop.clicked.connect(self.spinner.stop)
        spinner_row.addWidget(spinner_btn_start)
        spinner_row.addWidget(spinner_btn_stop)
        card_layout.addLayout(spinner_row)

        progress_block = QVBoxLayout()
        progress_block.setSpacing(10)
        progress_label = QLabel("Auto-assigning chemical shifts")
        progress_label.setStyleSheet("font-size: 14px;")
        progress_block.addWidget(progress_label)
        self.progress = ShimmerProgressBar()
        progress_block.addWidget(self.progress)

        progress_controls = QHBoxLayout()
        progress_controls.setSpacing(8)
        for label_text, value in [("0%", 0.0), ("33%", 0.33), ("66%", 0.66), ("100%", 1.0)]:
            btn = QPushButton(label_text)
            btn.setObjectName("GhostButton")
            btn.clicked.connect(lambda _checked=False, v=value: self.progress.setProgress(v))  # type: ignore[misc]
            progress_controls.addWidget(btn)
        progress_controls.addStretch(1)
        shim_start = QPushButton("Shimmer on")
        shim_start.setObjectName("PrimaryButton")
        shim_stop = QPushButton("Shimmer off")
        shim_stop.setObjectName("GhostButton")
        shim_start.clicked.connect(self.progress.startShimmer)
        shim_stop.clicked.connect(self.progress.stopShimmer)
        progress_controls.addWidget(shim_start)
        progress_controls.addWidget(shim_stop)
        progress_block.addLayout(progress_controls)
        card_layout.addLayout(progress_block)

        outer.addWidget(card)
        outer.addStretch(1)


# ════════════════════════════════════════════════════════════════════════════
#  Demo 5 — Feedback & decoration indicators
#
#  Patterns:
#   • Animated checkmark / cross drawn as a single ``progress`` parameter
#     (segments revealed proportionally — works because both shapes are
#     2 line segments with known length ratios).
#   • Indeterminate progress band — a sliding gradient over a track for
#     unknown-duration tasks (parsing, scanning, network).
#   • Pulsing dot — radial halo that grows + fades, layered under a solid
#     dot. Ideal "live" / "running" indicator.
#   • Skeleton line — gray rounded rect with a shimmer sweep, used as a
#     placeholder while data loads.
# ════════════════════════════════════════════════════════════════════════════
class _AnimatedGlyph(QWidget):
    """Base class for stroke-revealed glyphs (checkmark, cross). Subclasses
    define the line segments via ``_segments()`` and the ring color."""

    BG_COLOR: str = "#e5e7eb"
    STROKE_COLOR: str = "#5b6470"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(56, 56)
        self._progress = 0.0
        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(560)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_progress(self) -> float:
        return self._progress

    def set_progress(self, v: float) -> None:
        self._progress = float(v)
        self.update()

    progress = pyqtProperty(float, fget=get_progress, fset=set_progress)

    def play(self) -> None:
        self._anim.stop()
        self._progress = 0.0
        self._anim.start()

    def reset(self) -> None:
        self._anim.stop()
        self._progress = 0.0
        self.update()

    def _segments(self, cx: float, cy: float, scale: float) -> list[tuple[QPointF, QPointF]]:
        """Return the line segments that make up the glyph, in order."""
        raise NotImplementedError

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() / 2
        cy = self.height() / 2
        radius = min(self.width(), self.height()) / 2 - 2

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.BG_COLOR))
        painter.drawEllipse(QPointF(cx, cy), radius, radius)

        if self._progress <= 0:
            return

        segments = self._segments(cx, cy, radius * 0.55)
        # Distribute progress evenly across segments
        per = 1.0 / len(segments)
        pen = QPen(QColor(self.STROKE_COLOR), 4.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        for idx, (start, end) in enumerate(segments):
            seg_start = idx * per
            seg_end = seg_start + per
            if self._progress >= seg_end:
                painter.drawLine(start, end)
            elif self._progress > seg_start:
                t = (self._progress - seg_start) / per
                mid = QPointF(start.x() + (end.x() - start.x()) * t,
                              start.y() + (end.y() - start.y()) * t)
                painter.drawLine(start, mid)
                break
            else:
                break


class SuccessCheckmark(_AnimatedGlyph):
    BG_COLOR = "#d8f3dc"
    STROKE_COLOR = "#2b7a3a"

    def _segments(self, cx: float, cy: float, scale: float) -> list[tuple[QPointF, QPointF]]:
        p1 = QPointF(cx - scale * 0.65, cy + scale * 0.05)
        p2 = QPointF(cx - scale * 0.05, cy + scale * 0.55)
        p3 = QPointF(cx + scale * 0.75, cy - scale * 0.45)
        return [(p1, p2), (p2, p3)]


class ErrorCross(_AnimatedGlyph):
    BG_COLOR = "#ffd6d6"
    STROKE_COLOR = "#a51d1d"

    def _segments(self, cx: float, cy: float, scale: float) -> list[tuple[QPointF, QPointF]]:
        s = scale * 0.55
        a1, a2 = QPointF(cx - s, cy - s), QPointF(cx + s, cy + s)
        b1, b2 = QPointF(cx + s, cy - s), QPointF(cx - s, cy + s)
        return [(a1, a2), (b1, b2)]


class IndeterminateProgressBar(QWidget):
    """A track with a sliding gradient band — for unknown-duration tasks."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pos = -0.4
        self.setFixedHeight(8)
        self.setMinimumWidth(160)
        self._anim = QPropertyAnimation(self, b"position", self)
        self._anim.setDuration(1500)
        self._anim.setStartValue(-0.4)
        self._anim.setEndValue(1.0)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

    def get_position(self) -> float:
        return self._pos

    def set_position(self, v: float) -> None:
        self._pos = float(v)
        self.update()

    position = pyqtProperty(float, fget=get_position, fset=set_position)

    def start(self) -> None:
        if self._anim.state() != QPropertyAnimation.State.Running:
            self._anim.start()

    def stop(self) -> None:
        self._anim.stop()
        self._pos = -0.4
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        radius = rect.height() / 2

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e8eaef"))
        painter.drawRoundedRect(rect, radius, radius)

        if self._anim.state() != QPropertyAnimation.State.Running:
            return

        band_w = rect.width() * 0.4
        band_x = rect.width() * self._pos
        painter.setClipRect(rect)
        grad = QLinearGradient(band_x, 0, band_x + band_w, 0)
        grad.setColorAt(0.0, QColor(74, 123, 247, 0))
        grad.setColorAt(0.5, QColor(74, 123, 247, 230))
        grad.setColorAt(1.0, QColor(74, 123, 247, 0))
        painter.setBrush(grad)
        painter.drawRoundedRect(rect, radius, radius)


class PulsingDot(QWidget):
    """Solid dot with an animated halo — 'live' indicator."""

    def __init__(self, color: str = "#10b981", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._pulse = 0.0
        self.setFixedSize(28, 28)
        self._anim = QPropertyAnimation(self, b"pulse", self)
        self._anim.setDuration(1500)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_pulse(self) -> float:
        return self._pulse

    def set_pulse(self, v: float) -> None:
        self._pulse = float(v)
        self.update()

    pulse = pyqtProperty(float, fget=get_pulse, fset=set_pulse)

    def start(self) -> None:
        if self._anim.state() != QPropertyAnimation.State.Running:
            self._anim.start()

    def stop(self) -> None:
        self._anim.stop()
        self._pulse = 0.0
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() / 2
        cy = self.height() / 2

        if self._anim.state() == QPropertyAnimation.State.Running:
            halo_r = 4.0 + 9.0 * self._pulse
            halo_alpha = int(180 * (1.0 - self._pulse))
            halo = QColor(self._color)
            halo.setAlpha(halo_alpha)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(QPointF(cx, cy), halo_r, halo_r)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(QPointF(cx, cy), 4.0, 4.0)


class SkeletonLine(QWidget):
    """A gray rounded rect with a shimmer sweep — placeholder while loading."""

    def __init__(self, width_ratio: float = 1.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._width_ratio = max(0.1, min(1.0, width_ratio))
        self._shim = -0.3
        self.setFixedHeight(14)
        self.setMinimumWidth(80)
        self._anim = QPropertyAnimation(self, b"shimmer", self)
        self._anim.setDuration(1300)
        self._anim.setStartValue(-0.3)
        self._anim.setEndValue(1.3)
        self._anim.setLoopCount(-1)
        self._anim.start()

    def get_shimmer(self) -> float:
        return self._shim

    def set_shimmer(self, v: float) -> None:
        self._shim = float(v)
        self.update()

    shimmer = pyqtProperty(float, fget=get_shimmer, fset=set_shimmer)

    def start(self) -> None:
        if self._anim.state() != QPropertyAnimation.State.Running:
            self._anim.start()

    def stop(self) -> None:
        self._anim.stop()
        self._shim = -0.3
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track_rect = QRectF(0, 0, self.width() * self._width_ratio, self.height())
        radius = 4.0

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e8eaef"))
        painter.drawRoundedRect(track_rect, radius, radius)

        x = track_rect.width() * self._shim
        grad = QLinearGradient(x - 60, 0, x + 60, 0)
        grad.setColorAt(0.0, QColor(255, 255, 255, 0))
        grad.setColorAt(0.5, QColor(255, 255, 255, 130))
        grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(grad)
        painter.setClipRect(track_rect)
        painter.drawRoundedRect(track_rect, radius, radius)


class FeedbackDecorationDemo(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setSpacing(18)

        intro = QLabel(
            "Feedback indicators (✓ / ✗ / live pulse / indeterminate progress) "
            "and skeleton placeholders. Pure-PyQt; copy a class into "
            "dp4_platform/animations.py and import where needed."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        outer.addWidget(intro)

        # ── Result indicators (✓ + ✗)
        results_card = QFrame()
        results_card.setObjectName("FeedbackCard")
        results_card.setStyleSheet(
            f"#FeedbackCard {{ background: {COLOR_CARD}; "
            f"border: 1px solid {COLOR_BORDER}; border-radius: 14px; }}"
        )
        rc_layout = QHBoxLayout(results_card)
        rc_layout.setContentsMargins(28, 24, 28, 24)
        rc_layout.setSpacing(36)

        # Success column
        ok_col = QVBoxLayout()
        ok_col.setSpacing(10)
        ok_col.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.checkmark = SuccessCheckmark()
        ok_col.addWidget(self.checkmark, 0, Qt.AlignmentFlag.AlignCenter)
        ok_label = QLabel("Calculation complete")
        ok_label.setStyleSheet("font-weight: 600; font-size: 13px;")
        ok_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ok_col.addWidget(ok_label)
        ok_btn = QPushButton("Replay")
        ok_btn.setObjectName("GhostButton")
        ok_btn.clicked.connect(self.checkmark.play)
        ok_col.addWidget(ok_btn)
        rc_layout.addLayout(ok_col)

        # Error column
        err_col = QVBoxLayout()
        err_col.setSpacing(10)
        err_col.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cross = ErrorCross()
        err_col.addWidget(self.cross, 0, Qt.AlignmentFlag.AlignCenter)
        err_label = QLabel("Parser failed")
        err_label.setStyleSheet("font-weight: 600; font-size: 13px;")
        err_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        err_col.addWidget(err_label)
        err_btn = QPushButton("Replay")
        err_btn.setObjectName("GhostButton")
        err_btn.clicked.connect(self.cross.play)
        err_col.addWidget(err_btn)
        rc_layout.addLayout(err_col)

        rc_layout.addStretch(1)

        # Live pulse + indeterminate progress
        live_col = QVBoxLayout()
        live_col.setSpacing(14)

        pulse_row = QHBoxLayout()
        pulse_row.setSpacing(10)
        self.dot = PulsingDot()
        self.dot.start()
        pulse_row.addWidget(self.dot)
        pulse_label = QLabel("Worker is live")
        pulse_label.setStyleSheet("font-weight: 600; font-size: 13px;")
        pulse_row.addWidget(pulse_label)
        pulse_row.addStretch(1)
        pulse_btn = QPushButton("Toggle")
        pulse_btn.setObjectName("GhostButton")

        def _toggle_pulse() -> None:
            if self.dot._anim.state() == QPropertyAnimation.State.Running:
                self.dot.stop()
            else:
                self.dot.start()

        pulse_btn.clicked.connect(_toggle_pulse)
        pulse_row.addWidget(pulse_btn)
        live_col.addLayout(pulse_row)

        prog_row = QHBoxLayout()
        prog_row.setSpacing(10)
        self.indeterminate = IndeterminateProgressBar()
        self.indeterminate.start()
        prog_row.addWidget(QLabel("Scanning…"))
        prog_row.addWidget(self.indeterminate, 1)
        prog_btn = QPushButton("Toggle")
        prog_btn.setObjectName("GhostButton")

        def _toggle_prog() -> None:
            if self.indeterminate._anim.state() == QPropertyAnimation.State.Running:
                self.indeterminate.stop()
            else:
                self.indeterminate.start()

        prog_btn.clicked.connect(_toggle_prog)
        prog_row.addWidget(prog_btn)
        live_col.addLayout(prog_row)

        rc_layout.addLayout(live_col, 2)
        outer.addWidget(results_card)

        # ── Skeleton loader card
        skeleton_card = QFrame()
        skeleton_card.setObjectName("SkeletonCard")
        skeleton_card.setStyleSheet(
            f"#SkeletonCard {{ background: {COLOR_CARD}; "
            f"border: 1px solid {COLOR_BORDER}; border-radius: 14px; }}"
        )
        sk_layout = QVBoxLayout(skeleton_card)
        sk_layout.setContentsMargins(28, 24, 28, 24)
        sk_layout.setSpacing(14)

        sk_title = QLabel("Skeleton placeholder (shown while a candidate row is loading)")
        sk_title.setStyleSheet(f"color: {COLOR_TEXT_FAINT}; font-size: 12px;")
        sk_layout.addWidget(sk_title)

        for ratios in [(0.45, 0.30, 0.18), (0.65, 0.20), (0.30, 0.55, 0.10)]:
            row = QHBoxLayout()
            row.setSpacing(10)
            for r in ratios:
                line = SkeletonLine(width_ratio=1.0)
                line.setMinimumWidth(60)
                line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                # Convert ratio to stretch factor (×100 keeps integer math reasonable)
                row.addWidget(line, int(r * 100))
            row.addStretch(1)
            sk_layout.addLayout(row)

        outer.addWidget(skeleton_card)

        # ── Trigger row
        trig_row = QHBoxLayout()
        trig_row.setSpacing(8)
        replay_all = QPushButton("Trigger ✓ + ✗ replay")
        replay_all.setObjectName("PrimaryButton")
        replay_all.clicked.connect(lambda: (self.checkmark.play(), self.cross.play()))
        trig_row.addStretch(1)
        trig_row.addWidget(replay_all)
        outer.addLayout(trig_row)

        outer.addStretch(1)


# ════════════════════════════════════════════════════════════════════════════
#  Demos 6/7/8 — DP4 result charts (matplotlib + animated entrance + export)
#
#  See ``result_charts.py`` for the chart classes. The wrappers below share
#  a small base that handles the card frame + Replay + Export PNG/SVG/PDF
#  buttons, so each concrete demo only declares its sample data and the
#  chart factory.
# ════════════════════════════════════════════════════════════════════════════
class _ChartDemoBase(QWidget):
    INTRO_TEXT: str = ""
    DEFAULT_FILE_STEM: str = "chart"

    def _create_chart(self) -> QWidget:
        raise NotImplementedError

    def _seed_chart(self, chart: QWidget) -> None:
        raise NotImplementedError

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setSpacing(18)

        intro = QLabel(self.INTRO_TEXT)
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        outer.addWidget(intro)

        card = QFrame()
        card.setObjectName("ChartCard")
        card.setStyleSheet(
            f"#ChartCard {{ background: {COLOR_CARD}; "
            f"border: 1px solid {COLOR_BORDER}; border-radius: 14px; }}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)

        self.chart = self._create_chart()
        self._seed_chart(self.chart)
        card_layout.addWidget(self.chart)
        outer.addWidget(card, 1)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        replay_btn = QPushButton("▶ Replay animation")
        replay_btn.setObjectName("PrimaryButton")
        replay_btn.clicked.connect(self.chart.animate_in)  # type: ignore[attr-defined]
        controls.addStretch(1)
        controls.addWidget(replay_btn)

        for label_text, ext, filt in [
            ("Export PNG…", "png", "PNG image (*.png)"),
            ("Export SVG…", "svg", "Scalable Vector Graphics (*.svg)"),
            ("Export PDF…", "pdf", "PDF document (*.pdf)"),
        ]:
            btn = QPushButton(label_text)
            btn.setObjectName("GhostButton")
            btn.clicked.connect(lambda _checked=False, e=ext, f=filt: self._export(e, f))  # type: ignore[misc]
            controls.addWidget(btn)
        outer.addLayout(controls)

        self._auto_played = False

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if not self._auto_played:
            self._auto_played = True
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(180, self.chart.animate_in)  # type: ignore[attr-defined]

    def _export(self, ext: str, file_filter: str) -> None:
        default_name = f"{self.DEFAULT_FILE_STEM}.{ext}"
        path, _selected = QFileDialog.getSaveFileName(
            self,
            f"Export as {ext.upper()}",
            default_name,
            file_filter,
        )
        if not path:
            return
        try:
            self.chart.export(path)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Export failed", f"Could not save: {exc}")
            return
        QMessageBox.information(
            self,
            "Export complete",
            f"Saved to:\n{path}\n\nDPI 300, transparent margins removed.",
        )


class CandidateRankingDemo(_ChartDemoBase):
    INTRO_TEXT = (
        "matplotlib FigureCanvasQTAgg embedded in Qt. Bars grow with a per-bar "
        "stagger; winner highlighted in Okabe–Ito blue. Same Figure backs the "
        "animation and the export — what you see is what saves to disk."
    )
    DEFAULT_FILE_STEM = "candidate_ranking"
    SAMPLE_DATA: list[tuple[str, float]] = [
        ("(R,R,S)", 0.823),
        ("(S,R,S)", 0.084),
        ("(R,S,R)", 0.052),
        ("(S,S,R)", 0.041),
    ]

    def _create_chart(self) -> QWidget:
        return CandidateRankingChart()

    def _seed_chart(self, chart) -> None:
        chart.set_data(self.SAMPLE_DATA)


class NMRScatterDemo(_ChartDemoBase):
    INTRO_TEXT = (
        "Computed vs experimental ¹³C shifts, one color per candidate. The y=x "
        "reference draws first; candidate point groups fade in with a stagger; "
        "the best-fit MAE / R² annotation lands at the end."
    )
    DEFAULT_FILE_STEM = "nmr_scatter"

    # Synthetic ¹³C shifts for a hypothetical 12-carbon scaffold.
    EXPERIMENTAL: list[float] = [
        156.4, 142.2, 128.7, 127.9, 126.4, 124.5,
        84.3, 67.8, 41.2, 28.6, 22.3, 14.5,
    ]
    # Per-candidate predicted shifts. Hand-tuned so (R,R,S) is clearly the
    # best fit (small, scattered residuals) and the others diverge more.
    PREDICTIONS: list[tuple[str, list[float]]] = [
        ("(R,R,S)", [156.8, 141.8, 128.9, 127.4, 126.9, 124.8,
                     84.7, 67.4, 40.9, 29.0, 22.0, 14.7]),
        ("(S,R,S)", [158.3, 144.5, 130.6, 129.4, 124.8, 122.6,
                     86.3, 70.9, 39.4, 30.7, 24.2, 12.8]),
        ("(R,S,R)", [153.1, 139.7, 132.8, 124.3, 130.0, 127.4,
                     80.7, 71.6, 44.2, 25.6, 19.8, 17.6]),
        ("(S,S,R)", [161.6, 147.0, 124.3, 132.1, 122.4, 120.2,
                     90.1, 62.4, 36.9, 33.5, 18.1, 18.8]),
    ]

    def _create_chart(self) -> QWidget:
        return NMRScatterChart()

    def _seed_chart(self, chart) -> None:
        chart.set_data([(label, self.EXPERIMENTAL, predicted)
                        for label, predicted in self.PREDICTIONS])


class AtomDeviationDemo(_ChartDemoBase):
    INTRO_TEXT = (
        "Heatmap of |Δδ| (computed − experimental) per (candidate, atom). "
        "Cells reveal along the leading anti-diagonal; winner row is bolded "
        "and tinted to match the ranking chart."
    )
    DEFAULT_FILE_STEM = "atom_deviation"

    ATOM_LABELS: list[str] = [f"C{i + 1}" for i in range(12)]
    CANDIDATE_LABELS: list[str] = ["(R,R,S)", "(S,R,S)", "(R,S,R)", "(S,S,R)"]

    def _create_chart(self) -> QWidget:
        return AtomDeviationHeatmap()

    def _seed_chart(self, chart) -> None:
        # Build the deviation matrix from NMRScatterDemo's synthetic data so
        # the two charts tell a consistent story.
        exp = NMRScatterDemo.EXPERIMENTAL
        matrix: list[list[float]] = []
        for _label, predicted in NMRScatterDemo.PREDICTIONS:
            matrix.append([abs(p - e) for p, e in zip(predicted, exp)])
        chart.set_data(matrix, self.CANDIDATE_LABELS, self.ATOM_LABELS)


# ════════════════════════════════════════════════════════════════════════════
#  Launcher window — sidebar + content host
# ════════════════════════════════════════════════════════════════════════════
APP_QSS = f"""
QMainWindow, QWidget#AppShell {{
    background: {COLOR_BG};
    color: {COLOR_TEXT};
    font-size: 13px;
}}
QFrame#Sidebar {{
    background: {COLOR_CARD};
    border: 1px solid {COLOR_BORDER};
    border-radius: 18px;
}}
QListWidget#DemoList {{
    background: transparent;
    border: 0;
    padding: 6px;
    outline: 0;
}}
QListWidget#DemoList::item {{
    padding: 12px 16px;
    border-radius: 12px;
    margin: 3px 4px;
    color: {COLOR_TEXT};
}}
QListWidget#DemoList::item:hover {{
    background: {COLOR_HOVER};
}}
QListWidget#DemoList::item:selected {{
    background: {COLOR_ACCENT_SOFT};
    color: {COLOR_ACCENT};
    font-weight: 600;
}}
QFrame#ContentHost {{
    background: {COLOR_CARD};
    border: 1px solid {COLOR_BORDER};
    border-radius: 18px;
}}
QLabel#ShellTitle {{
    font-size: 22px;
    font-weight: 700;
    color: {COLOR_TEXT};
}}
QLabel#ShellSubtitle {{
    color: {COLOR_TEXT_MUTED};
    font-size: 13px;
}}
QPushButton#PrimaryButton {{
    background: {COLOR_ACCENT};
    color: white;
    border: 0;
    border-radius: 18px;
    padding: 8px 18px;
    font-weight: 600;
    min-height: 24px;
}}
QPushButton#PrimaryButton:hover {{
    background: #2f5fe0;
}}
QPushButton#PrimaryButton:disabled {{
    background: #c7d1e0;
    color: #f4f5f8;
}}
QPushButton#GhostButton {{
    background: transparent;
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    border-radius: 18px;
    padding: 7px 16px;
    font-weight: 600;
    min-height: 24px;
}}
QPushButton#GhostButton:hover {{
    background: {COLOR_HOVER};
    border-color: #b8c0cc;
}}
QPushButton#GhostButton:disabled {{
    color: #b0b6c0;
    border-color: #e2e5ec;
}}
QFrame#CollapsibleHeader {{
    background: transparent;
}}
QFrame#CollapsibleHeader:hover {{
    background: {COLOR_HOVER};
}}
QFrame#CollapsibleContent {{
    background: transparent;
}}
"""


class DemoLauncher(QMainWindow):
    DEMOS: list[tuple[str, str, type[QWidget]]] = [
        (
            "Page transitions",
            "Sliding stacked widget for forward / backward navigation",
            PageTransitionDemo,
        ),
        (
            "Collapsible sections",
            "Animated expand / collapse with a rotating chevron",
            CollapsibleDemo,
        ),
        (
            "Status badges",
            "Color-tweening pill with a scale pulse on state change",
            StatusBadgeDemo,
        ),
        (
            "Loading indicators",
            "Custom-painted spinner and a shimmering progress bar",
            LoadingIndicatorsDemo,
        ),
        (
            "Feedback & decoration",
            "Animated ✓ / ✗, indeterminate progress, live-pulse dot, skeleton lines",
            FeedbackDecorationDemo,
        ),
        (
            "Result · ranking",
            "Journal-styled DP4 ranking — animated bars, exportable PNG / SVG / PDF",
            CandidateRankingDemo,
        ),
        (
            "Result · NMR scatter",
            "Computed vs experimental ¹³C shifts with R² / MAE annotation",
            NMRScatterDemo,
        ),
        (
            "Result · atom heatmap",
            "Per-atom |Δδ| deviation, diagonal-wipe reveal",
            AtomDeviationDemo,
        ),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DP4 Platform — GUI Animation Demo")
        self.resize(1180, 760)

        shell = QWidget()
        shell.setObjectName("AppShell")
        self.setCentralWidget(shell)
        outer = QHBoxLayout(shell)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(18)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(260)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(20, 22, 20, 20)
        side_layout.setSpacing(10)

        title = QLabel("Animation patterns")
        title.setObjectName("ShellTitle")
        side_layout.addWidget(title)
        subtitle = QLabel("Drop-in PyQt6 widgets, palette-matched to dp4_platform.")
        subtitle.setObjectName("ShellSubtitle")
        subtitle.setWordWrap(True)
        side_layout.addWidget(subtitle)

        side_layout.addSpacing(12)

        self.list = QListWidget()
        self.list.setObjectName("DemoList")
        self.list.setSpacing(2)
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        for name, _desc, _cls in self.DEMOS:
            item = QListWidgetItem(name)
            self.list.addItem(item)
        self.list.currentRowChanged.connect(self._on_selected)
        side_layout.addWidget(self.list, 1)

        footer = QLabel("v0.1 · sandbox · existing files untouched")
        footer.setStyleSheet(f"color: {COLOR_TEXT_FAINT}; font-size: 11px;")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side_layout.addWidget(footer)
        outer.addWidget(sidebar)

        host = QFrame()
        host.setObjectName("ContentHost")
        self.host_layout = QVBoxLayout(host)
        self.host_layout.setContentsMargins(36, 32, 36, 32)
        self.host_layout.setSpacing(18)

        self.page_title = QLabel("")
        self.page_title.setObjectName("ShellTitle")
        self.host_layout.addWidget(self.page_title)

        self.page_subtitle = QLabel("")
        self.page_subtitle.setObjectName("ShellSubtitle")
        self.page_subtitle.setWordWrap(True)
        self.host_layout.addWidget(self.page_subtitle)

        self.host_layout.addSpacing(6)

        self.stack = QStackedWidget()
        self.host_layout.addWidget(self.stack, 1)

        for _name, _desc, demo_cls in self.DEMOS:
            self.stack.addWidget(demo_cls())

        outer.addWidget(host, 1)

        self.list.setCurrentRow(0)

    def _on_selected(self, row: int) -> None:
        if not (0 <= row < len(self.DEMOS)):
            return
        name, desc, _cls = self.DEMOS[row]
        self.page_title.setText(name)
        self.page_subtitle.setText(desc)
        self.stack.setCurrentIndex(row)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_QSS)
    win = DemoLauncher()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
