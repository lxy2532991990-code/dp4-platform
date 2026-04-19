"""PyQt GUI for the standalone DP4 workflow."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


_QT_DLL_DIRECTORY_HANDLES = []


def _enable_windows_dpi_awareness() -> None:
    """Ask Windows to render native dialogs crisply on high-DPI displays."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        awareness_context_per_monitor_v2 = ctypes.c_void_p(-4)
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(awareness_context_per_monitor_v2):
            return
    except Exception:
        pass
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        import ctypes

        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _resolved_path_text(path: str) -> str:
    try:
        return str(Path(path).resolve()).casefold()
    except (OSError, RuntimeError):
        return path.casefold()


def _prepare_qt_environment() -> None:
    """Keep Qt startup stable when VS Code runs from an activated venv terminal."""
    _enable_windows_dpi_awareness()
    os.environ.setdefault("QT_API", "pyqt6")

    executable = Path(sys.executable).resolve()
    venv_scripts = executable.parent
    if venv_scripts.name.lower() == "scripts" and executable.name.lower().startswith("python"):
        venv_scripts_text = _resolved_path_text(str(venv_scripts))
        path_parts = os.environ.get("PATH", "").split(os.pathsep)
        os.environ["PATH"] = os.pathsep.join(
            part for part in path_parts if part and _resolved_path_text(part) != venv_scripts_text
        )

    site_packages = venv_scripts.parent / "Lib" / "site-packages"
    pyqt_qt = site_packages / "PyQt6" / "Qt6"
    qt_bin = pyqt_qt / "bin"
    qt_plugins = pyqt_qt / "plugins"
    if qt_plugins.is_dir():
        os.environ["QT_PLUGIN_PATH"] = str(qt_plugins)
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(qt_plugins / "platforms")
    if qt_bin.is_dir() and hasattr(os, "add_dll_directory"):
        _QT_DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(qt_bin)))


_prepare_qt_environment()

if __package__ in (None, ""):
    package_root = Path(__file__).resolve().parents[1]
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    from dp4_platform.autoassign import (
        AutoAssignRow,
        auto_assign,
        build_candidate_predictions,
        parse_nmr_text,
        write_assignments_csv,
    )
    from dp4_platform.config import DP4Config, WeightingStrategy
    from dp4_platform.experimental import load_experimental_assignments
    from dp4_platform.models import OrcaFileInfo
    from dp4_platform.gui_logic import (
        CandidateCardState,
        CandidateScanResult,
        PairingRow,
        ScanSummary,
        build_discovery_signature,
        build_pairing_rows_by_strategy,
        build_scan_signature,
        candidate_can_reuse_discovered_files,
        candidate_scan_is_fresh,
        clone_pairing_rows,
        detect_program_from_files,
    )
    from dp4_platform.parser import (
        discover_candidate_directories,
        discover_candidate_files,
    )
    from dp4_platform.pipeline import DP4Pipeline
    from dp4_platform.structure_model import build_c_h_adjacency
else:
    from .autoassign import (
        AutoAssignRow,
        auto_assign,
        build_candidate_predictions,
        parse_nmr_text,
        write_assignments_csv,
    )
    from .config import DP4Config, WeightingStrategy
    from .experimental import load_experimental_assignments
    from .models import OrcaFileInfo
    from .gui_logic import (
        CandidateCardState,
        CandidateScanResult,
        PairingRow,
        ScanSummary,
        build_discovery_signature,
        build_pairing_rows_by_strategy,
        build_scan_signature,
        candidate_can_reuse_discovered_files,
        candidate_scan_is_fresh,
        clone_pairing_rows,
        detect_program_from_files,
    )
    from .parser import (
        discover_candidate_directories,
        discover_candidate_files,
    )
    from .pipeline import DP4Pipeline
    from .structure_model import build_c_h_adjacency

try:
    from PyQt6.QtCore import Qt, QThread, pyqtSignal
    from PyQt6.QtGui import QAction, QColor
    from PyQt6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QDoubleSpinBox,
        QFileDialog,
        QFrame,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMenuBar,
        QMessageBox,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QScrollArea,
        QSplitter,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PyQt6 is required for the DP4 GUI") from exc

try:
    from .structure3d import StructureView
except ImportError:  # pragma: no cover
    try:
        from dp4_platform.structure3d import StructureView
    except ImportError:
        StructureView = None  # type: ignore[assignment]

try:
    from .structure2d import Structure2DView
except ImportError:  # pragma: no cover
    try:
        from dp4_platform.structure2d import Structure2DView
    except ImportError:
        Structure2DView = None  # type: ignore[assignment]


NONE_OPTION = "(none)"


def _get_existing_directory_with_tk(title: str, initial_path: str) -> str:
    script = (
        "import sys\n"
        "if sys.platform == 'win32':\n"
        "    try:\n"
        "        import ctypes\n"
        "        if not ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):\n"
        "            ctypes.windll.shcore.SetProcessDpiAwareness(2)\n"
        "    except Exception:\n"
        "        try:\n"
        "            ctypes.windll.user32.SetProcessDPIAware()\n"
        "        except Exception:\n"
        "            pass\n"
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "root = tk.Tk()\n"
        "root.withdraw()\n"
        "root.attributes('-topmost', True)\n"
        "root.update()\n"
        "try:\n"
        "    value = filedialog.askdirectory(title=sys.argv[1], initialdir=sys.argv[2], mustexist=True)\n"
        "finally:\n"
        "    root.destroy()\n"
        "if value:\n"
        "    print(value, end='')\n"
    )
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(
        [sys.executable, "-c", script, title, initial_path],
        capture_output=True,
        text=True,
        creationflags=creationflags,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "Folder picker failed")
    return completed.stdout.strip()


def _get_existing_directory(parent: QWidget, title: str, start_path: str) -> str:
    initial_path = start_path if start_path and os.path.isdir(start_path) else os.getcwd()
    initial_path = os.path.abspath(initial_path)
    if sys.platform == "win32":
        try:
            return _get_existing_directory_with_tk(title, initial_path)
        except Exception:
            pass
    # Use static method instead of dialog object to avoid qtpy compatibility issues
    # Don't set any options to use default native dialog
    result = QFileDialog.getExistingDirectory(
        parent,
        title,
        initial_path,
        # options=QFileDialog.Option.ShowDirsOnly  # Usually not needed for getExistingDirectory
    )
    return result if result else ""


class CandidateScanWorker(QThread):
    finished = pyqtSignal(object)

    def __init__(
        self,
        request_id: int,
        directory: str,
        config: DP4Config,
        overrides: dict[str, str],
    ):
        super().__init__()
        self.request_id = request_id
        self.directory = directory
        self.config = config
        self.overrides = dict(overrides)

    def run(self) -> None:
        discovery_signature = build_discovery_signature(self.directory, self.config)
        scan_signature = build_scan_signature(self.directory, self.config, self.overrides)
        try:
            discovered_files = discover_candidate_files(self.directory, self.config)
            rows_by_strategy, summary_by_strategy = build_pairing_rows_by_strategy(
                discovered_files,
                self.config,
                self.overrides,
            )
            result = CandidateScanResult(
                request_id=self.request_id,
                discovery_signature=discovery_signature,
                scan_signature=scan_signature,
                discovered_files=discovered_files,
                pairing_rows_by_strategy=rows_by_strategy,
                summary_by_strategy=summary_by_strategy,
            )
        except Exception as exc:
            result = CandidateScanResult(
                request_id=self.request_id,
                discovery_signature=discovery_signature,
                scan_signature=scan_signature,
                error=str(exc),
            )
        self.finished.emit(result)


class AutoAssignWorker(QThread):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, name: str, directory: str, config: DP4Config):
        super().__init__()
        self.name = name
        self.directory = directory
        self.config = config

    def run(self) -> None:
        try:
            _, predicted, elements, coordinates = build_candidate_predictions(
                self.name, self.directory, self.config
            )
            self.finished.emit(
                {
                    "predicted": predicted,
                    "elements": elements,
                    "coordinates": coordinates,
                }
            )
        except Exception as exc:
            self.error.emit(str(exc))


class AutoAssignDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        candidate_states: list[CandidateCardState],
        config: DP4Config,
        default_csv_path: str,
    ):
        super().__init__(parent)
        self.setWindowTitle("从 NMR 文本自动指派")
        self.resize(1440, 820)
        self.base_config = config
        self.default_csv_path = default_csv_path
        self.candidate_states = [state for state in candidate_states if state.directory]
        self.predicted_by_nucleus: dict[str, dict[int, float]] = {}
        self.elements: dict[int, str] = {}
        self.coordinates: dict[int, tuple[float, float, float]] = {}
        self.rows: list[AutoAssignRow] = []
        self.hydrogens_by_carbon: dict[int, list[int]] = {}
        self.carbon_by_hydrogen: dict[int, int] = {}
        self._focused_row_indices: set[int] | None = None
        self.worker: AutoAssignWorker | None = None
        self.saved_csv_path: str | None = None
        self.structure_view = None
        self.structure_2d_view = None
        self.structure_tabs = None
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        top_row = QGridLayout()
        top_row.addWidget(QLabel("候选结构"), 0, 0)
        self.cmb_candidate = QComboBox()
        for state in self.candidate_states:
            self.cmb_candidate.addItem(f"{state.name}  ({state.directory})", state)
        top_row.addWidget(self.cmb_candidate, 0, 1, 1, 3)

        top_row.addWidget(QLabel("1H NMR 文本"), 1, 0)
        self.ed_h_text = QPlainTextEdit()
        self.ed_h_text.setPlaceholderText("粘贴 1H NMR 原文，例如：1H NMR (500 MHz, CDCl3) δ 7.32, 6.85, 6.73 ...")
        self.ed_h_text.setFixedHeight(56)
        top_row.addWidget(self.ed_h_text, 1, 1, 1, 3)

        top_row.addWidget(QLabel("13C NMR 文本"), 2, 0)
        self.ed_c_text = QPlainTextEdit()
        self.ed_c_text.setPlaceholderText("粘贴 13C NMR 原文，例如：13C NMR (125 MHz, CD3OD-d) δ 154.2, 148.8, 148.7 ...")
        self.ed_c_text.setFixedHeight(56)
        top_row.addWidget(self.ed_c_text, 2, 1, 1, 3)

        self.btn_parse = QPushButton("解析并指派")
        self.btn_parse.clicked.connect(self._run_assignment)
        top_row.addWidget(self.btn_parse, 3, 3)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        top_row.addWidget(self.status_label, 3, 0, 1, 3)

        top_row.addWidget(QLabel("Assignment mode"), 4, 0)
        self.cmb_assignment_mode = QComboBox()
        self.cmb_assignment_mode.addItem("13C", "13C")
        self.cmb_assignment_mode.addItem("1H", "1H")
        self.cmb_assignment_mode.currentIndexChanged.connect(self._on_assignment_mode_changed)
        top_row.addWidget(self.cmb_assignment_mode, 4, 1)

        self.btn_show_all_rows = QPushButton("Show all rows")
        self.btn_show_all_rows.clicked.connect(self._clear_table_focus)
        self.btn_show_all_rows.setEnabled(False)
        top_row.addWidget(self.btn_show_all_rows, 4, 3)

        outer.addLayout(top_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.structure_tabs = QTabWidget()
        if StructureView is not None:
            self.structure_view = StructureView()
            self.structure_view.atom_clicked.connect(self._on_atom_clicked)
            self.structure_tabs.addTab(self.structure_view, "3D")
        else:
            placeholder = QLabel(
                "未安装 pyvista / pyvistaqt，\n无法显示 3D 结构。\n"
                "请执行：pip install pyvista pyvistaqt"
            )
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.structure_tabs.addTab(placeholder, "3D")

        if Structure2DView is not None:
            self.structure_2d_view = Structure2DView()
            self.structure_2d_view.atom_clicked.connect(self._on_atom_clicked)
            self.structure_tabs.addTab(self.structure_2d_view, "2D")
        else:
            placeholder = QLabel("RDKit 未安装，无法生成二维结构。")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.structure_tabs.addTab(placeholder, "2D")

        splitter.addWidget(self.structure_tabs)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 0, 0, 0)

        right_splitter = QSplitter(Qt.Orientation.Vertical)

        peaks_container = QWidget()
        peaks_row = QHBoxLayout(peaks_container)
        peaks_row.setContentsMargins(0, 0, 0, 0)
        c_box = QGroupBox("13C 实测峰 (点击分配给选中原子)")
        c_box_layout = QVBoxLayout(c_box)
        self.list_c_peaks = QListWidget()
        self.list_c_peaks.itemClicked.connect(lambda item: self._on_peak_clicked(item, "13C"))
        c_box_layout.addWidget(self.list_c_peaks)
        peaks_row.addWidget(c_box, 1)

        h_box = QGroupBox("1H 实测峰")
        h_box_layout = QVBoxLayout(h_box)
        self.list_h_peaks = QListWidget()
        self.list_h_peaks.itemClicked.connect(lambda item: self._on_peak_clicked(item, "1H"))
        h_box_layout.addWidget(self.list_h_peaks)
        peaks_row.addWidget(h_box, 1)
        right_splitter.addWidget(peaks_container)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["核", "原子序号", "元素", "预测 (ppm)", "实测 (ppm)", "误差 (ppm)"]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._on_row_selection_changed)
        right_splitter.addWidget(self.table)
        right_splitter.setStretchFactor(0, 1)
        right_splitter.setStretchFactor(1, 2)
        right_splitter.setCollapsible(0, False)
        right_splitter.setCollapsible(1, False)
        right_layout.addWidget(right_splitter, 1)

        hint = QLabel(
            "操作：点击 3D 结构上的原子 → 高亮对应行；"
            "再点击左侧列表里的一个实测峰 → 填入该行。"
            "行可直接编辑；黄色表示指派置信度较低；绿色球 = 已分配原子。"
        )
        hint.setWordWrap(True)
        right_layout.addWidget(hint)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        self.btn_save = QPushButton("保存为 CSV")
        self.btn_save.clicked.connect(self._save_csv)
        self.btn_save.setEnabled(False)
        buttons.addWidget(cancel)
        buttons.addWidget(self.btn_save)
        outer.addLayout(buttons)

    def _structure_views(self) -> list[object]:
        return [
            view
            for view in (self.structure_view, self.structure_2d_view)
            if view is not None
        ]

    def _assignment_mode(self) -> str:
        value = self.cmb_assignment_mode.currentData()
        return str(value) if value in ("1H", "13C") else "13C"

    def _structure_pick_nuclei(self) -> tuple[str, ...]:
        if self._assignment_mode() == "1H":
            return ("1H", "13C")
        return ("13C",)

    def _refresh_assignment_mode_options(self) -> None:
        available = [
            nucleus
            for nucleus in ("13C", "1H")
            if self.predicted_by_nucleus.get(nucleus)
        ]
        if not available:
            available = [nucleus for nucleus in ("13C", "1H") if nucleus in self._active_nuclei()]
        if not available:
            available = ["13C", "1H"]

        current = self._assignment_mode()
        selected = current if current in available else ("13C" if "13C" in available else available[0])

        self.cmb_assignment_mode.blockSignals(True)
        try:
            self.cmb_assignment_mode.clear()
            for nucleus in available:
                self.cmb_assignment_mode.addItem(nucleus, nucleus)
            index = self.cmb_assignment_mode.findData(selected)
            self.cmb_assignment_mode.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self.cmb_assignment_mode.blockSignals(False)

    def _on_assignment_mode_changed(self) -> None:
        self._clear_table_focus()
        self._clear_table_selection()
        self._clear_structure_highlights()
        for view in self._structure_views():
            view.set_active_nuclei(self._structure_pick_nuclei())

    def _row_indices_for_atom(self, atom_id: int, nucleus: str | None = None) -> list[int]:
        return [
            row_index
            for row_index, row in enumerate(self.rows)
            if row.atom_id == atom_id and (nucleus is None or row.nucleus == nucleus)
        ]

    def _row_indices_for_atoms(self, atom_ids: list[int], nucleus: str) -> list[int]:
        wanted = set(atom_ids)
        return [
            row_index
            for row_index, row in enumerate(self.rows)
            if row.nucleus == nucleus and row.atom_id in wanted
        ]

    def _select_table_row(self, row_index: int) -> None:
        self.table.blockSignals(True)
        try:
            self.table.selectRow(row_index)
        finally:
            self.table.blockSignals(False)
        self._apply_table_focus()
        item = self.table.item(row_index, 0)
        if item is not None:
            self.table.scrollToItem(item)

    def _clear_table_selection(self) -> None:
        self.table.blockSignals(True)
        try:
            self.table.clearSelection()
            self.table.setCurrentCell(-1, -1)
        finally:
            self.table.blockSignals(False)

    def _focus_rows(self, row_indices: list[int], select_row: int | None = None) -> None:
        self._focused_row_indices = set(row_indices) if row_indices else None
        self._apply_table_focus()
        if select_row is not None and 0 <= select_row < len(self.rows):
            self._select_table_row(select_row)

    def _clear_table_focus(self) -> None:
        self._focused_row_indices = None
        self._apply_table_focus()

    def _apply_table_focus(self) -> None:
        focused = self._focused_row_indices
        for row_index in range(self.table.rowCount()):
            self.table.setRowHidden(row_index, focused is not None and row_index not in focused)
        self.btn_show_all_rows.setEnabled(focused is not None)

    def _set_structure_highlights(
        self,
        primary_atom: int | None,
        related_atoms: list[int] | set[int] | tuple[int, ...] = (),
    ) -> None:
        related = set(related_atoms)
        if primary_atom is not None:
            related.discard(primary_atom)
        for view in self._structure_views():
            if hasattr(view, "set_related_atoms"):
                view.set_related_atoms(related)
            view.set_highlighted_atom(primary_atom)

    def _clear_structure_highlights(self) -> None:
        self._set_structure_highlights(None, ())

    def _highlight_for_row(self, row: AutoAssignRow) -> None:
        if row.nucleus == "1H":
            carbon_id = self.carbon_by_hydrogen.get(row.atom_id)
            related = self.hydrogens_by_carbon.get(carbon_id, []) if carbon_id is not None else []
            self._set_structure_highlights(row.atom_id, related)
            return
        self._set_structure_highlights(row.atom_id, ())

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self.structure_view is not None:
            self.structure_view.close_plotter()
        super().closeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        from PyQt6.QtCore import QTimer

        def _refresh() -> None:
            self.updateGeometry()
            self.update()
            for view in self._structure_views():
                view.update()
            if self.structure_view is not None:
                try:
                    self.structure_view.plotter.render()
                except Exception:
                    pass

        QTimer.singleShot(0, _refresh)

    def _active_nuclei(self) -> tuple[str, ...]:
        nuclei: list[str] = []
        if self.ed_h_text.toPlainText().strip():
            nuclei.append("1H")
        if self.ed_c_text.toPlainText().strip():
            nuclei.append("13C")
        return tuple(nuclei) or self.base_config.nuclei

    def _run_assignment(self) -> None:
        state = self.cmb_candidate.currentData()
        if state is None:
            QMessageBox.warning(self, "缺少候选", "请先在主界面添加一个候选结构并选择其文件夹。")
            return

        nuclei = self._active_nuclei()
        config = DP4Config(
            exp_nmr_file="",
            output_dir=self.base_config.output_dir,
            nuclei=nuclei,
            weighting=self.base_config.weighting,
            temperature=self.base_config.temperature,
            program_mode=self.base_config.program_mode,
        )

        self.btn_parse.setEnabled(False)
        self.btn_save.setEnabled(False)
        self.status_label.setText(f"正在解析候选 '{state.name}' 的 DFT 结果...")

        self.worker = AutoAssignWorker(state.name, state.directory, config)
        self.worker.finished.connect(self._on_prediction_ready)
        self.worker.error.connect(self._on_prediction_failed)
        self.worker.start()

    def _on_prediction_failed(self, message: str) -> None:
        self.btn_parse.setEnabled(True)
        self.status_label.setText(f"解析失败：{message}")
        QMessageBox.critical(self, "解析失败", message)

    def _on_prediction_ready(self, payload: dict) -> None:
        self.btn_parse.setEnabled(True)
        self.predicted_by_nucleus = payload.get("predicted", {})
        self.elements = payload.get("elements", {})
        self.coordinates = payload.get("coordinates", {})
        self.hydrogens_by_carbon, self.carbon_by_hydrogen = build_c_h_adjacency(
            self.coordinates,
            self.elements,
        )

        exp_shifts_by_nucleus: dict[str, list[float]] = {}
        if "1H" in self.predicted_by_nucleus:
            exp_shifts_by_nucleus["1H"] = parse_nmr_text(self.ed_h_text.toPlainText())
        if "13C" in self.predicted_by_nucleus:
            exp_shifts_by_nucleus["13C"] = parse_nmr_text(self.ed_c_text.toPlainText())

        self.rows = auto_assign(
            self.predicted_by_nucleus,
            exp_shifts_by_nucleus,
            elements=self.elements,
        )
        self._focused_row_indices = None
        self._refresh_assignment_mode_options()

        summary_bits = []
        for nucleus, peaks in exp_shifts_by_nucleus.items():
            atoms = len(self.predicted_by_nucleus.get(nucleus, {}))
            summary_bits.append(f"{nucleus}: {len(peaks)} 个实测峰 / {atoms} 个原子")
        if not self.coordinates:
            summary_bits.append("未从计算输出解析到 XYZ 坐标，3D 结构无法显示")
        self.status_label.setText("；".join(summary_bits) if summary_bits else "未解析到化学位移")

        self._populate_peak_lists(exp_shifts_by_nucleus)
        self._populate_table()

        for view in self._structure_views():
            view.set_structure(
                self.coordinates,
                self.elements,
                self._structure_pick_nuclei(),
            )
            view.set_assigned_atoms(self._current_assigned_atoms())
            if hasattr(view, "set_related_atoms"):
                view.set_related_atoms(())
            view.set_highlighted_atom(None)

        self.btn_save.setEnabled(bool(self.rows))

    def _populate_peak_lists(self, exp_shifts_by_nucleus: dict[str, list[float]]) -> None:
        for widget, nucleus in (
            (self.list_c_peaks, "13C"),
            (self.list_h_peaks, "1H"),
        ):
            widget.clear()
            for value in exp_shifts_by_nucleus.get(nucleus, []):
                label = f"{value:.3f} ppm"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, value)
                widget.addItem(item)

    def _populate_table(self) -> None:
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(0)
            for row in self.rows:
                row_index = self.table.rowCount()
                self.table.insertRow(row_index)

                nucleus_item = QTableWidgetItem(row.nucleus)
                nucleus_item.setFlags(nucleus_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row_index, 0, nucleus_item)

                atom_item = QTableWidgetItem(str(row.atom_id))
                atom_item.setFlags(atom_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row_index, 1, atom_item)

                element_item = QTableWidgetItem(row.element)
                element_item.setFlags(element_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row_index, 2, element_item)

                predicted_item = QTableWidgetItem(f"{row.predicted_shift_ppm:.3f}")
                predicted_item.setFlags(predicted_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row_index, 3, predicted_item)

                exp_text = "" if row.exp_shift_ppm is None else f"{row.exp_shift_ppm:.3f}"
                exp_item = QTableWidgetItem(exp_text)
                self.table.setItem(row_index, 4, exp_item)

                self.table.setItem(row_index, 5, QTableWidgetItem(""))

                self._refresh_error_for_row(row_index)
                self._apply_row_confidence_color(row_index, row)
        finally:
            self.table.blockSignals(False)

    def _apply_row_confidence_color(self, row_index: int, row: AutoAssignRow) -> None:
        ambiguous_threshold = 0.5 if row.nucleus == "1H" else 3.0
        color = QColor("#ffffff")
        if row.exp_shift_ppm is None:
            color = QColor("#ffc9c9")
        elif row.confidence < ambiguous_threshold:
            color = QColor("#fff3bf")
        for column in range(self.table.columnCount()):
            item = self.table.item(row_index, column)
            if item is not None:
                item.setBackground(color)

    def _refresh_error_for_row(self, row_index: int) -> None:
        exp_item = self.table.item(row_index, 4)
        pred_item = self.table.item(row_index, 3)
        err_item = self.table.item(row_index, 5)
        if exp_item is None or pred_item is None or err_item is None:
            return
        exp_text = exp_item.text().strip()
        if not exp_text:
            err_item.setText("")
            return
        try:
            exp_value = float(exp_text)
            pred_value = float(pred_item.text())
        except ValueError:
            err_item.setText("?")
            return
        err_item.setText(f"{exp_value - pred_value:+.3f}")

    def _current_assigned_atoms(self) -> set[int]:
        return {row.atom_id for row in self.rows if row.exp_shift_ppm is not None}

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 4:
            return
        row_index = item.row()
        text = item.text().strip()
        if text:
            try:
                value = float(text)
            except ValueError:
                QMessageBox.warning(self, "无效输入", f"第 {row_index + 1} 行实测位移不是合法数字：'{text}'")
                self.table.blockSignals(True)
                item.setText("")
                self.table.blockSignals(False)
                self.rows[row_index].exp_shift_ppm = None
                self._refresh_error_for_row(row_index)
                self._apply_row_confidence_color(row_index, self.rows[row_index])
                for view in self._structure_views():
                    view.set_assigned_atoms(self._current_assigned_atoms())
                return
            self.rows[row_index].exp_shift_ppm = value
        else:
            self.rows[row_index].exp_shift_ppm = None
        self._refresh_error_for_row(row_index)
        self._apply_row_confidence_color(row_index, self.rows[row_index])
        for view in self._structure_views():
            view.set_assigned_atoms(self._current_assigned_atoms())

    def _on_atom_clicked(self, atom_id: int) -> None:
        element = self.elements.get(atom_id, "")
        mode = self._assignment_mode()

        if mode == "1H":
            if element == "C":
                hydrogen_ids = self.hydrogens_by_carbon.get(atom_id, [])
                row_indices = self._row_indices_for_atoms(hydrogen_ids, "1H")
                self._focus_rows(row_indices, row_indices[0] if row_indices else None)
                self._set_structure_highlights(atom_id, hydrogen_ids)
                return
            if element == "H":
                carbon_id = self.carbon_by_hydrogen.get(atom_id)
                hydrogen_ids = (
                    self.hydrogens_by_carbon.get(carbon_id, [atom_id])
                    if carbon_id is not None
                    else [atom_id]
                )
                row_indices = self._row_indices_for_atoms(hydrogen_ids, "1H")
                selected = next(
                    (idx for idx in row_indices if self.rows[idx].atom_id == atom_id),
                    row_indices[0] if row_indices else None,
                )
                self._focus_rows(row_indices, selected)
                self._set_structure_highlights(atom_id, hydrogen_ids)
                return

        if element == "C":
            row_indices = self._row_indices_for_atom(atom_id, "13C")
            self._clear_table_focus()
            if row_indices:
                self._select_table_row(row_indices[0])
            self._set_structure_highlights(atom_id, ())

    def _on_row_selection_changed(self) -> None:
        row_index = self.table.currentRow()
        if row_index < 0 or row_index >= len(self.rows):
            self._clear_structure_highlights()
            return
        row = self.rows[row_index]
        if self._assignment_mode() == "1H" and row.nucleus == "1H":
            carbon_id = self.carbon_by_hydrogen.get(row.atom_id)
            hydrogen_ids = self.hydrogens_by_carbon.get(carbon_id, []) if carbon_id is not None else [row.atom_id]
            self._focus_rows(self._row_indices_for_atoms(hydrogen_ids, "1H"))
        self._highlight_for_row(row)

    def _on_peak_clicked(self, item: QListWidgetItem, nucleus: str) -> None:
        row_index = self.table.currentRow()
        if row_index < 0 or row_index >= len(self.rows):
            QMessageBox.information(
                self,
                "未选中原子",
                "请先在 3D 结构或表格中选中一个原子，再点击要指派的实测峰。",
            )
            return
        row = self.rows[row_index]
        if row.nucleus != nucleus:
            QMessageBox.information(
                self,
                "核类型不匹配",
                f"当前选中行的核为 {row.nucleus}，无法指派 {nucleus} 实测峰。",
            )
            return
        value = float(item.data(Qt.ItemDataRole.UserRole))
        row.exp_shift_ppm = value
        exp_item = self.table.item(row_index, 4)
        if exp_item is not None:
            self.table.blockSignals(True)
            exp_item.setText(f"{value:.3f}")
            self.table.blockSignals(False)
        self._refresh_error_for_row(row_index)
        self._apply_row_confidence_color(row_index, row)
        for view in self._structure_views():
            view.set_assigned_atoms(self._current_assigned_atoms())

    def _save_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存实测指派 CSV",
            self.default_csv_path or os.path.join(os.getcwd(), "experimental_assignments.csv"),
            "CSV Files (*.csv)",
        )
        if not path:
            return
        try:
            written = write_assignments_csv(path, self.rows)
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        if written == 0:
            QMessageBox.warning(self, "无可保存行", "所有行的实测位移均为空，未写入任何记录。")
            return
        self.saved_csv_path = path
        QMessageBox.information(self, "已保存", f"已写入 {written} 条指派到:\n{path}")
        self.accept()


class PipelineWorker(QThread):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    status = pyqtSignal(str)
    progress = pyqtSignal(int, int)

    def __init__(self, config: DP4Config):
        super().__init__()
        self.config = config

    def run(self) -> None:
        try:
            pipeline = DP4Pipeline(
                self.config,
                logger=self.status.emit,
                progress_callback=self.progress.emit,
            )
            result = pipeline.run()
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


class CandidateCard(QFrame):
    remove_requested = pyqtSignal(object)
    name_changed = pyqtSignal(object)
    directory_changed = pyqtSignal(object)
    details_requested = pyqtSignal(object)
    refresh_requested = pyqtSignal(object)

    def __init__(self, state: CandidateCardState):
        super().__init__()
        self.state = state
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        self.name_edit = QLineEdit(self.state.name)
        self.name_edit.textEdited.connect(self._on_name_edited)
        close_button = QPushButton("X")
        close_button.setFixedWidth(28)
        close_button.clicked.connect(lambda: self.remove_requested.emit(self))
        header.addWidget(self.name_edit)
        header.addWidget(close_button)
        layout.addLayout(header)

        path_row = QHBoxLayout()
        folder_button = QPushButton("Folder")
        folder_button.clicked.connect(self._choose_directory)
        self.path_label = QLabel("")
        self.path_label.setWordWrap(True)
        path_row.addWidget(folder_button)
        path_row.addWidget(self.path_label, 1)
        layout.addLayout(path_row)

        self.summary_label = QLabel("No folder selected")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #c92a2a;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        action_row = QHBoxLayout()
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(lambda: self.refresh_requested.emit(self))
        details_button = QPushButton("Details...")
        details_button.clicked.connect(lambda: self.details_requested.emit(self))
        action_row.addWidget(refresh_button)
        action_row.addWidget(details_button)
        layout.addLayout(action_row)

    def _choose_directory(self) -> None:
        value = _get_existing_directory(self, "Select Candidate Folder", self.state.directory)
        if value:
            self.state.directory = value
            self.refresh()
            self.directory_changed.emit(self)

    def _on_name_edited(self, text: str) -> None:
        self.state.name = text.strip()
        self.name_changed.emit(self)

    def refresh(self) -> None:
        self.path_label.setText(self.state.directory or "No folder selected")
        self.path_label.setToolTip(self.state.directory)

        is_failed = self.state.scan_status == "failed"
        self._apply_failed_styling(is_failed)

        if not self.state.directory:
            self.summary_label.setText("No folder selected")
            self.summary_label.setToolTip("")
            return
        if self.state.scan_status == "scanning":
            self.summary_label.setText("Scanning...")
            self.summary_label.setToolTip(self.state.directory)
            return
        if is_failed:
            self.summary_label.setText("扫描失败")
            self.summary_label.setToolTip(self.state.scan_error)
            error_text = self.state.scan_error or "(no error details)"
            truncated = error_text if len(error_text) <= 120 else error_text[:120] + "…"
            self.error_label.setText(truncated)
            self.error_label.setToolTip(self.state.scan_error)
            return
        if self.state.scan_status == "ready":
            program_text = self.state.detected_program.upper() if self.state.detected_program not in {"unknown", "mixed"} else self.state.detected_program.title()
            prefix = f"{program_text}: " if self.state.detected_program != "unknown" else ""
            self.summary_label.setText(
                f"{prefix}{self.state.detected_count} conformers detected\n"
                f"{self.state.paired_count} paired   {self.state.unpaired_count} unpaired"
            )
            self.summary_label.setToolTip("")
            return
        self.summary_label.setText("Ready to scan")
        self.summary_label.setToolTip("")

    def _apply_failed_styling(self, is_failed: bool) -> None:
        if is_failed:
            self.summary_label.setStyleSheet("color: #c92a2a; font-weight: bold;")
            self.error_label.setVisible(True)
            self.setStyleSheet("CandidateCard { border: 1px solid #c92a2a; }")
        else:
            self.summary_label.setStyleSheet("")
            self.error_label.setVisible(False)
            self.error_label.setText("")
            self.error_label.setToolTip("")
            self.setStyleSheet("")


class PairingDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        candidate_name: str,
        directory: str,
        config: DP4Config,
        overrides: dict[str, str],
        discovered_files: list[OrcaFileInfo],
        pairing_rows_by_strategy: dict[str, list[PairingRow]],
    ):
        super().__init__(parent)
        self.setWindowTitle(f'Pairing for "{candidate_name}"')
        self.resize(860, 520)
        self.directory = directory
        self.base_config = config
        self.current_overrides = dict(overrides)
        self.detected_program = detect_program_from_files(discovered_files)
        self.discovered_files = [
            info for info in discovered_files if self.detected_program in {"unknown", info.program}
        ]
        self.opt_files = sorted([info for info in self.discovered_files if info.role.value == "opt"], key=lambda item: item.path)
        self.nmr_files = sorted([info for info in self.discovered_files if info.role.value == "nmr"], key=lambda item: item.path)
        self.pairing_rows_by_strategy = {
            strategy: clone_pairing_rows(rows) for strategy, rows in pairing_rows_by_strategy.items()
        }
        self.auto_rows_by_strategy, _ = build_pairing_rows_by_strategy(
            self.discovered_files,
            self.base_config,
            {},
            {"conf_id", "filename", self.base_config.auto_pair_strategy},
        )
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Conf", "Opt file", "NMR file", "State"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._build_ui()
        initial_strategy = self.base_config.auto_pair_strategy
        rows = self.pairing_rows_by_strategy.get(initial_strategy) or self.auto_rows_by_strategy.get(initial_strategy, [])
        self._populate_rows(rows)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Folder: {self.directory or '(not selected)'}"))
        layout.addWidget(QLabel(f"Program: {self.detected_program.upper()}"))
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        auto_conf = QPushButton("Auto-pair by conf id")
        auto_name = QPushButton("Auto-pair by filename")
        auto_conf.clicked.connect(lambda: self._reset_to_strategy("conf_id"))
        auto_name.clicked.connect(lambda: self._reset_to_strategy("filename"))
        buttons.addWidget(auto_conf)
        buttons.addWidget(auto_name)
        buttons.addStretch(1)

        cancel = QPushButton("Cancel")
        ok = QPushButton("OK")
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._accept)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        layout.addLayout(buttons)

    def _reset_to_strategy(self, strategy: str) -> None:
        self.current_overrides = {}
        self._populate_rows(self.auto_rows_by_strategy.get(strategy, []))

    def _combo_for_paths(self, paths: list[str], selected: str | None) -> QComboBox:
        combo = QComboBox()
        combo.addItem(NONE_OPTION, None)
        for path in paths:
            combo.addItem(Path(path).name, path)
        index = combo.findData(selected)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.currentIndexChanged.connect(self._refresh_row_states)
        return combo

    def _populate_rows(self, rows: list[PairingRow]) -> None:
        self.table.setRowCount(0)
        opt_paths = [info.path for info in self.opt_files]
        nmr_paths = [info.path for info in self.nmr_files]

        for row_data in rows:
            row_index = self.table.rowCount()
            self.table.insertRow(row_index)
            conf_text = str(row_data.conf_id) if row_data.conf_id is not None else "-"
            conf_item = QTableWidgetItem(conf_text)
            conf_item.setFlags(conf_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row_index, 0, conf_item)

            if row_data.combined_path:
                combined_item = QTableWidgetItem(Path(row_data.combined_path).name)
                combined_item.setFlags(combined_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                state_item = QTableWidgetItem("COMBINED")
                state_item.setFlags(state_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                right_item = QTableWidgetItem("(combined)")
                right_item.setFlags(right_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row_index, 1, combined_item)
                self.table.setItem(row_index, 2, right_item)
                self.table.setItem(row_index, 3, state_item)
                continue

            self.table.setCellWidget(row_index, 1, self._combo_for_paths(opt_paths, row_data.opt_path))
            self.table.setCellWidget(row_index, 2, self._combo_for_paths(nmr_paths, row_data.nmr_path))
            state_item = QTableWidgetItem("")
            state_item.setFlags(state_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row_index, 3, state_item)

        self._refresh_row_states()

    def _row_selection(self, row_index: int) -> tuple[str | None, str | None]:
        opt_combo = self.table.cellWidget(row_index, 1)
        nmr_combo = self.table.cellWidget(row_index, 2)
        opt_path = opt_combo.currentData() if isinstance(opt_combo, QComboBox) else None
        nmr_path = nmr_combo.currentData() if isinstance(nmr_combo, QComboBox) else None
        return opt_path, nmr_path

    def _set_row_color(self, row_index: int, color: QColor) -> None:
        for column in range(4):
            item = self.table.item(row_index, column)
            if item is not None:
                item.setBackground(color)
        for column in (1, 2):
            widget = self.table.cellWidget(row_index, column)
            if isinstance(widget, QComboBox):
                widget.setStyleSheet(f"background-color: {color.name()};")

    def _refresh_row_states(self) -> None:
        used_opt: dict[str, int] = {}
        used_nmr: dict[str, int] = {}
        for row_index in range(self.table.rowCount()):
            state_item = self.table.item(row_index, 3)
            if state_item and state_item.text() == "COMBINED":
                continue
            opt_path, nmr_path = self._row_selection(row_index)
            if opt_path:
                used_opt[opt_path] = used_opt.get(opt_path, 0) + 1
            if nmr_path:
                used_nmr[nmr_path] = used_nmr.get(nmr_path, 0) + 1

        white = QColor("#ffffff")
        yellow = QColor("#fff3bf")
        red = QColor("#ffc9c9")
        for row_index in range(self.table.rowCount()):
            state_item = self.table.item(row_index, 3)
            if state_item is None:
                continue
            if state_item.text() == "COMBINED":
                self._set_row_color(row_index, white)
                continue

            opt_path, nmr_path = self._row_selection(row_index)
            conflict = bool((opt_path and used_opt.get(opt_path, 0) > 1) or (nmr_path and used_nmr.get(nmr_path, 0) > 1))
            if conflict:
                state_item.setText("CONFLICT")
                self._set_row_color(row_index, red)
            elif opt_path and nmr_path:
                state_item.setText("OK")
                self._set_row_color(row_index, white)
            else:
                state_item.setText("UNPAIR")
                self._set_row_color(row_index, yellow)

    def _accept(self) -> None:
        overrides: dict[str, str] = {}
        for row_index in range(self.table.rowCount()):
            state_item = self.table.item(row_index, 3)
            if state_item and state_item.text() == "CONFLICT":
                QMessageBox.warning(self, "Pairing Conflict", "The same file cannot be paired more than once.")
                return
            if state_item and state_item.text() == "COMBINED":
                continue
            opt_path, nmr_path = self._row_selection(row_index)
            if opt_path and nmr_path:
                overrides[opt_path] = nmr_path
        self.current_overrides = overrides
        self.accept()

    @property
    def pairing_overrides(self) -> dict[str, str]:
        return dict(self.current_overrides)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DP4 Platform")
        self.resize(1240, 820)
        self.worker: PipelineWorker | None = None
        self.scan_workers: dict[int, CandidateScanWorker] = {}
        self.cards: list[CandidateCard] = []
        self.candidates: dict[str, CandidateCardState] = {}
        self.project_path: str | None = None
        self._build_ui()
        self._new_project()

    def _set_candidate_area_updates_enabled(self, enabled: bool) -> None:
        self.scroll_area.setUpdatesEnabled(enabled)
        self.scroll_content.setUpdatesEnabled(enabled)

    def _rebuild_candidates_dict(self) -> None:
        self.candidates = {
            card.state.name: card.state
            for card in self.cards
            if card.state.name
        }

    def _add_candidate_state_to_dict(self, state: CandidateCardState) -> None:
        if state.name:
            self.candidates[state.name] = state

    def _remove_candidate_state_from_dict(self, state: CandidateCardState) -> None:
        if state.name and self.candidates.get(state.name) is state:
            self.candidates.pop(state.name, None)

    def _build_ui(self) -> None:
        self._build_menu()

        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        experimental_box = QGroupBox("Experimental")
        experimental_layout = QGridLayout(experimental_box)
        self.ed_exp = QLineEdit()
        self.ed_exp.textChanged.connect(lambda _text: self._refresh_experimental_summary())
        browse_exp = QPushButton("Browse")
        browse_exp.clicked.connect(self._choose_experimental_file)
        auto_assign_btn = QPushButton("从 NMR 文本自动指派")
        auto_assign_btn.clicked.connect(self._open_auto_assign_dialog)
        self.exp_summary = QLabel("Loaded: no file")
        experimental_layout.addWidget(QLabel("Experimental CSV"), 0, 0)
        experimental_layout.addWidget(self.ed_exp, 0, 1)
        experimental_layout.addWidget(browse_exp, 0, 2)
        experimental_layout.addWidget(auto_assign_btn, 0, 3)
        experimental_layout.addWidget(self.exp_summary, 1, 0, 1, 4)
        layout.addWidget(experimental_box)

        candidates_box = QGroupBox("Candidates")
        candidates_layout = QVBoxLayout(candidates_box)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QHBoxLayout(self.scroll_content)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.scroll_area.setWidget(self.scroll_content)
        candidates_layout.addWidget(self.scroll_area)
        layout.addWidget(candidates_box)

        self.add_button = QPushButton("+ Add")
        self.add_button.clicked.connect(lambda: self._add_candidate_card())
        self.scroll_layout.addWidget(self.add_button)

        parameters_box = QGroupBox("Parameters")
        parameters_layout = QGridLayout(parameters_box)

        self.chk_h = QCheckBox("1H")
        self.chk_h.setChecked(True)
        self.chk_h.toggled.connect(self._refresh_experimental_summary)
        self.chk_c = QCheckBox("13C")
        self.chk_c.setChecked(True)
        self.chk_c.toggled.connect(self._refresh_experimental_summary)
        nuclei_row = QHBoxLayout()
        nuclei_row.addWidget(self.chk_h)
        nuclei_row.addWidget(self.chk_c)
        nuclei_widget = QWidget()
        nuclei_widget.setLayout(nuclei_row)

        self.cmb_weighting = QComboBox()
        for strategy in WeightingStrategy:
            self.cmb_weighting.addItem(strategy.value, strategy)

        self.cmb_program_mode = QComboBox()
        self.cmb_program_mode.addItem("Auto", "auto")
        self.cmb_program_mode.addItem("ORCA", "orca")
        self.cmb_program_mode.addItem("Gaussian", "gaussian")
        self.cmb_program_mode.currentIndexChanged.connect(self._handle_program_mode_changed)

        self.spin_temp = QDoubleSpinBox()
        self.spin_temp.setDecimals(2)
        self.spin_temp.setRange(1.0, 5000.0)
        self.spin_temp.setValue(298.15)

        self.ed_output = QLineEdit(os.path.abspath("dp4_results"))
        browse_output = QPushButton("Browse")
        browse_output.clicked.connect(self._choose_output_dir)

        parameters_layout.addWidget(QLabel("Nuclei"), 0, 0)
        parameters_layout.addWidget(nuclei_widget, 0, 1)
        parameters_layout.addWidget(QLabel("Weighting"), 0, 2)
        parameters_layout.addWidget(self.cmb_weighting, 0, 3)
        parameters_layout.addWidget(QLabel("Program"), 0, 4)
        parameters_layout.addWidget(self.cmb_program_mode, 0, 5)
        parameters_layout.addWidget(QLabel("Temperature (K)"), 1, 0)
        parameters_layout.addWidget(self.spin_temp, 1, 1)
        parameters_layout.addWidget(QLabel("Output dir"), 1, 2)
        parameters_layout.addWidget(self.ed_output, 1, 3, 1, 2)
        parameters_layout.addWidget(browse_output, 1, 5)
        layout.addWidget(parameters_box)

        run_row = QHBoxLayout()
        self.btn_run = QPushButton("Run")
        self.btn_run.clicked.connect(self.run_pipeline)
        self.run_hint_label = QLabel("")
        self.run_hint_label.setWordWrap(True)
        self.run_hint_label.setStyleSheet("color: #868e96; font-style: italic;")
        self.run_hint_label.setVisible(False)
        run_row.addWidget(self.btn_run)
        run_row.addWidget(self.run_hint_label, 1)
        layout.addLayout(run_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m")
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Rank", "Name", "Joint P", "1H P", "13C P"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 2)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, 1)

    def _build_menu(self) -> None:
        menu_bar = QMenuBar(self)
        self.setMenuBar(menu_bar)
        file_menu = menu_bar.addMenu("File")
        help_menu = menu_bar.addMenu("Help")

        action_new = QAction("New", self)
        action_open = QAction("Open Project", self)
        action_save = QAction("Save Project", self)
        action_about = QAction("About", self)
        action_new.triggered.connect(self._new_project)
        action_open.triggered.connect(self._open_project)
        action_save.triggered.connect(self._save_project)
        action_about.triggered.connect(lambda: QMessageBox.information(self, "DP4 Platform", "DP4 project manager and runner"))
        file_menu.addAction(action_new)
        file_menu.addAction(action_open)
        file_menu.addAction(action_save)
        help_menu.addAction(action_about)

    def _active_nuclei(self) -> tuple[str, ...]:
        nuclei = []
        if self.chk_h.isChecked():
            nuclei.append("1H")
        if self.chk_c.isChecked():
            nuclei.append("13C")
        return tuple(nuclei)

    def _handle_program_mode_changed(self, _index: int) -> None:
        for card in self.cards:
            if card.state.directory:
                self._request_candidate_scan(card, force=True)
        self._update_run_readiness()

    def _set_program_mode_value(self, value: str) -> None:
        self.cmb_program_mode.blockSignals(True)
        try:
            index = self.cmb_program_mode.findData(value)
            self.cmb_program_mode.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self.cmb_program_mode.blockSignals(False)

    def _base_config(self) -> DP4Config:
        return DP4Config(
            exp_nmr_file=self.ed_exp.text().strip(),
            output_dir=self.ed_output.text().strip() or os.path.abspath("dp4_results"),
            nuclei=self._active_nuclei(),
            weighting=self.cmb_weighting.currentData(),
            temperature=self.spin_temp.value(),
            program_mode=self.cmb_program_mode.currentData(),
        )

    def _apply_summary_to_state(
        self,
        state: CandidateCardState,
        config: DP4Config,
        rows_by_strategy: dict[str, list[PairingRow]],
        summary_by_strategy: dict[str, ScanSummary],
        scan_signature: tuple | None = None,
    ) -> None:
        strategy = config.auto_pair_strategy
        summary = summary_by_strategy.get(strategy, ScanSummary())
        state.detected_count = summary.detected_count
        state.paired_count = summary.paired_count
        state.unpaired_count = summary.unpaired_count
        state.scan_summary = summary
        state.detected_program = detect_program_from_files(state.discovered_files)
        state.pairing_rows_by_strategy = {
            key: clone_pairing_rows(rows) for key, rows in rows_by_strategy.items()
        }
        state.scan_signature = scan_signature or build_scan_signature(state.directory, config, state.pairing_overrides)
        state.scan_status = "ready"
        state.scan_error = ""

    def _reset_candidate_cache(self, state: CandidateCardState) -> None:
        state.detected_count = 0
        state.paired_count = 0
        state.unpaired_count = 0
        state.scan_summary = ScanSummary()
        state.scan_signature = None
        state.discovery_signature = None
        state.detected_program = "unknown"
        state.scan_error = ""
        state.discovered_files = []
        state.pairing_rows_by_strategy = {}
        state.scan_status = "idle"

    def _refresh_experimental_summary(self) -> None:
        path = self.ed_exp.text().strip()
        if not path:
            self.exp_summary.setText("Loaded: no file")
            self._update_run_readiness()
            return
        try:
            assignments = load_experimental_assignments(path, self._active_nuclei())
        except Exception as exc:
            self.exp_summary.setText(f"Loaded: invalid file ({exc})")
            self._update_run_readiness()
            return
        counts = {nucleus: 0 for nucleus in self._active_nuclei()}
        for item in assignments:
            counts[item.nucleus] = counts.get(item.nucleus, 0) + 1
        details = ", ".join(f"{count}x{nucleus}" for nucleus, count in counts.items() if count)
        self.exp_summary.setText(f"Loaded: {len(assignments)} assignments ({details})")
        self._update_run_readiness()

    def _sync_candidate_states(self) -> None:
        for card in self.cards:
            card.state.name = card.name_edit.text().strip()
        self._rebuild_candidates_dict()
        self._update_run_readiness()

    def _refresh_candidate_from_cache(self, card: CandidateCard) -> None:
        config = self._base_config()
        rows_by_strategy, summary_by_strategy = build_pairing_rows_by_strategy(
            card.state.discovered_files,
            config,
            card.state.pairing_overrides,
        )
        self._apply_summary_to_state(card.state, config, rows_by_strategy, summary_by_strategy)
        card.refresh()
        self._sync_candidate_states()

    def _start_candidate_scan(self, card: CandidateCard) -> None:
        config = self._base_config()
        card.state.scan_status = "scanning"
        card.state.scan_error = ""
        card.refresh()
        worker = CandidateScanWorker(
            request_id=card.state.scan_request_id,
            directory=card.state.directory,
            config=config,
            overrides=card.state.pairing_overrides,
        )
        self.scan_workers[id(card)] = worker
        worker.finished.connect(lambda result, target=card: self._handle_candidate_scan_result(target, result))
        worker.start()

    def _request_candidate_scan(self, card: CandidateCard, force: bool = False) -> None:
        state = card.state
        if not state.directory:
            self._reset_candidate_cache(state)
            card.refresh()
            self._sync_candidate_states()
            return

        config = self._base_config()
        if not force and candidate_scan_is_fresh(state, config):
            card.refresh()
            self._sync_candidate_states()
            return

        if not force and candidate_can_reuse_discovered_files(state, config):
            self._refresh_candidate_from_cache(card)
            return

        state.scan_request_id += 1
        worker = self.scan_workers.get(id(card))
        if worker is not None and worker.isRunning():
            state.scan_dirty = True
            state.scan_status = "scanning"
            card.refresh()
            self._sync_candidate_states()
            return

        state.scan_dirty = False
        self._start_candidate_scan(card)
        self._sync_candidate_states()

    def _handle_candidate_scan_result(self, card: CandidateCard, result: CandidateScanResult) -> None:
        worker = self.scan_workers.pop(id(card), None)
        if worker is not None:
            worker.deleteLater()
        if card not in self.cards:
            return

        state = card.state
        if result.request_id != state.scan_request_id:
            if state.scan_dirty and state.directory:
                state.scan_dirty = False
                self._start_candidate_scan(card)
            return

        if result.error:
            state.scan_status = "failed"
            state.scan_error = result.error
            state.detected_program = "unknown"
            state.detected_count = 0
            state.paired_count = 0
            state.unpaired_count = 0
            state.scan_summary = ScanSummary()
            state.scan_signature = result.scan_signature
        else:
            state.discovery_signature = result.discovery_signature
            state.discovered_files = list(result.discovered_files)
            self._apply_summary_to_state(
                state,
                self._base_config(),
                result.pairing_rows_by_strategy,
                result.summary_by_strategy,
                scan_signature=result.scan_signature,
            )

        card.refresh()
        self._sync_candidate_states()

        if state.scan_dirty and state.directory:
            state.scan_dirty = False
            self._request_candidate_scan(card, force=True)

    def _add_candidate_card(self, state: CandidateCardState | None = None) -> None:
        card_state = state or CandidateCardState(name=f"isomer_{len(self.cards) + 1}")
        card = CandidateCard(card_state)
        card.remove_requested.connect(self._remove_candidate_card)
        card.name_changed.connect(self._handle_candidate_name_changed)
        card.directory_changed.connect(self._handle_candidate_directory_changed)
        card.details_requested.connect(self._open_pairing_dialog)
        card.refresh_requested.connect(self._handle_candidate_refresh_requested)
        self._set_candidate_area_updates_enabled(False)
        try:
            self.cards.append(card)
            self.scroll_layout.insertWidget(max(0, self.scroll_layout.count() - 1), card)
            self._add_candidate_state_to_dict(card.state)
        finally:
            self._set_candidate_area_updates_enabled(True)
            self.scroll_content.update()
            self.scroll_area.update()
        if card.state.directory:
            self._request_candidate_scan(card)
        else:
            self._update_run_readiness()

    def _remove_candidate_card(self, card: CandidateCard) -> None:
        self._remove_candidate_state_from_dict(card.state)
        if card in self.cards:
            self.cards.remove(card)
        card.state.scan_request_id += 1
        card.state.scan_dirty = False
        self._set_candidate_area_updates_enabled(False)
        try:
            self.scroll_layout.removeWidget(card)
            card.hide()
            card.setParent(None)
            card.deleteLater()
        finally:
            self._set_candidate_area_updates_enabled(True)
            self.scroll_content.update()
            self.scroll_area.update()
        self._update_run_readiness()

    def _handle_candidate_name_changed(self, card: CandidateCard) -> None:
        card.state.name = card.name_edit.text().strip()
        self._rebuild_candidates_dict()
        self._update_run_readiness()

    def _handle_candidate_directory_changed(self, card: CandidateCard) -> None:
        self._reset_candidate_cache(card.state)
        self._request_candidate_scan(card, force=True)

    def _handle_candidate_refresh_requested(self, card: CandidateCard) -> None:
        self._request_candidate_scan(card, force=True)

    def _choose_experimental_file(self) -> None:
        value, _ = QFileDialog.getOpenFileName(self, "Select Experimental CSV", self.ed_exp.text() or os.getcwd())
        if value:
            self.ed_exp.setText(value)
            self._refresh_experimental_summary()

    def _open_auto_assign_dialog(self) -> None:
        self._sync_candidate_states()
        ready_states = [state for state in self.candidates.values() if state.directory]
        if not ready_states:
            QMessageBox.warning(
                self,
                "缺少候选",
                "请先添加一个候选结构并选择其文件夹，再使用自动指派。",
            )
            return
        default_path = self.ed_exp.text().strip() or os.path.join(os.getcwd(), "experimental_assignments.csv")
        dialog = AutoAssignDialog(self, ready_states, self._base_config(), default_path)
        dialog.setWindowFlag(Qt.WindowType.Window, True)
        dialog.showMaximized()
        if dialog.exec() and dialog.saved_csv_path:
            self.ed_exp.setText(dialog.saved_csv_path)
            self._refresh_experimental_summary()

    def _choose_output_dir(self) -> None:
        value = _get_existing_directory(self, "Select Output Directory", self.ed_output.text())
        if value:
            self.ed_output.setText(value)

    def _open_pairing_dialog(self, card: CandidateCard) -> None:
        if not card.state.directory:
            QMessageBox.warning(self, "Candidate Folder Missing", "Select a candidate folder first.")
            return
        if card.state.scan_status == "scanning":
            QMessageBox.information(self, "Scan In Progress", "Candidate files are still being scanned. Please wait.")
            return
        if not candidate_can_reuse_discovered_files(card.state, self._base_config()):
            self._request_candidate_scan(card, force=True)
            QMessageBox.information(self, "Scan Required", "Candidate files are being rescanned with the latest program settings.")
            return
        if not card.state.discovered_files:
            self._request_candidate_scan(card, force=True)
            QMessageBox.information(self, "Scan Required", "Candidate files are being scanned. Open details again in a moment.")
            return
        try:
            dialog = PairingDialog(
                self,
                card.state.name or "candidate",
                card.state.directory,
                self._base_config(),
                card.state.pairing_overrides,
                card.state.discovered_files,
                card.state.pairing_rows_by_strategy,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Pairing Error", str(exc))
            return
        if dialog.exec():
            card.state.pairing_overrides = dialog.pairing_overrides
            if candidate_can_reuse_discovered_files(card.state, self._base_config()):
                self._refresh_candidate_from_cache(card)
            else:
                self._request_candidate_scan(card)
            self._sync_candidate_states()

    def append_log(self, text: str) -> None:
        self.log.appendPlainText(text)

    def _compute_run_readiness(self) -> tuple[bool, str]:
        if not self._active_nuclei():
            return False, "Select at least one nucleus."
        exp_file = self.ed_exp.text().strip()
        if not exp_file:
            return False, "Select the experimental assignment CSV before running."
        if not os.path.isfile(exp_file):
            return False, f"Experimental CSV not found:\n{exp_file}"
        if not self.cards:
            return False, "Add at least one candidate."

        names = [card.state.name.strip() for card in self.cards]
        if any(not name for name in names):
            return False, "Each candidate card needs a name."
        if len(names) != len(set(names)):
            return False, "Candidate names must be unique."

        config = self._base_config()
        for card in self.cards:
            state = card.state
            display_name = state.name or "(unnamed)"
            if not state.directory:
                return False, f"Candidate '{display_name}': select a folder."
            if not os.path.isdir(state.directory):
                return False, f"Candidate '{display_name}': folder not found."
            if state.scan_status == "scanning":
                return False, f"Candidate '{display_name}': scan in progress."
            if state.scan_status == "failed":
                detail = state.scan_error.splitlines()[0] if state.scan_error else "scan failed"
                return False, f"Candidate '{display_name}': {detail}"
            if state.scan_status != "ready" or not candidate_scan_is_fresh(state, config):
                return False, f"Candidate '{display_name}': awaiting refresh."
        return True, ""

    def _update_run_readiness(self) -> None:
        is_ready, reason = self._compute_run_readiness()
        running = self.worker is not None and self.worker.isRunning()
        self.btn_run.setEnabled(is_ready and not running)
        if is_ready or running:
            self.run_hint_label.setVisible(False)
            self.run_hint_label.setText("")
        else:
            self.run_hint_label.setText(reason)
            self.run_hint_label.setVisible(True)

    def _validate_candidate_cards(self) -> bool:
        names = [card.state.name.strip() for card in self.cards]
        exp_file = self.ed_exp.text().strip()
        if not self._active_nuclei():
            QMessageBox.warning(self, "Missing Nuclei", "Select at least one nucleus.")
            return False
        if not exp_file:
            QMessageBox.warning(self, "Experimental CSV Missing", "Select the experimental assignment CSV before running.")
            return False
        if not os.path.isfile(exp_file):
            QMessageBox.warning(self, "Experimental CSV Missing", f"Experimental CSV not found:\n{exp_file}")
            return False
        if any(not name for name in names):
            QMessageBox.warning(self, "Candidate Name Missing", "Each candidate card needs a name.")
            return False
        if len(names) != len(set(names)):
            QMessageBox.warning(self, "Duplicate Candidate Names", "Candidate names must be unique.")
            return False
        for card in self.cards:
            if not card.state.directory:
                QMessageBox.warning(self, "Candidate Folder Missing", f'Select a folder for "{card.state.name}".')
                return False
            if not os.path.isdir(card.state.directory):
                QMessageBox.warning(
                    self,
                    "Candidate Folder Missing",
                    f'Candidate folder not found for "{card.state.name}":\n{card.state.directory}',
                )
                return False
        return True

    def _collect_config(self) -> DP4Config:
        self._sync_candidate_states()
        return DP4Config(
            candidates_root="",
            candidate_paths={name: state.directory for name, state in self.candidates.items()},
            pairing_overrides={name: dict(state.pairing_overrides) for name, state in self.candidates.items()},
            exp_nmr_file=self.ed_exp.text().strip(),
            nuclei=self._active_nuclei(),
            weighting=self.cmb_weighting.currentData(),
            temperature=self.spin_temp.value(),
            output_dir=self.ed_output.text().strip() or os.path.abspath("dp4_results"),
            program_mode=self.cmb_program_mode.currentData(),
        )

    def run_pipeline(self) -> None:
        if not self._validate_candidate_cards():
            return
        config = self._collect_config()
        self.btn_run.setEnabled(False)
        self.run_hint_label.setVisible(False)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)
        self.table.setRowCount(0)
        self.log.clear()
        self.append_log(f"Starting run for {len(config.candidate_paths)} candidates")
        self.worker = PipelineWorker(config)
        self.worker.status.connect(self.append_log)
        self.worker.progress.connect(self._on_pipeline_progress)
        self.worker.error.connect(self._handle_error)
        self.worker.finished.connect(self._handle_result)
        self.worker.start()

    def _on_pipeline_progress(self, done: int, total: int) -> None:
        if total <= 0:
            return
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(done)

    def _handle_error(self, message: str) -> None:
        self.progress_bar.setVisible(False)
        self.append_log(f"Error: {message}")
        QMessageBox.critical(self, "DP4 Platform", message)
        self._update_run_readiness()

    def _handle_result(self, result) -> None:
        self.progress_bar.setVisible(False)
        self.append_log(f"Finished. Summary: {result.summary_file}")
        self.table.setRowCount(len(result.ranking))
        for row_index, score in enumerate(result.ranking):
            values = [
                str(row_index + 1),
                score.candidate_name,
                f"{score.joint_probability:.6f}",
                f"{score.probabilities.get('1H', 0.0):.6f}",
                f"{score.probabilities.get('13C', 0.0):.6f}",
            ]
            for col_index, value in enumerate(values):
                self.table.setItem(row_index, col_index, QTableWidgetItem(value))
        self._update_run_readiness()

    def _new_project(self) -> None:
        self.project_path = None
        self.ed_exp.setText("")
        self.ed_output.setText(os.path.abspath("dp4_results"))
        self.chk_h.setChecked(True)
        self.chk_c.setChecked(True)
        self.cmb_weighting.setCurrentIndex(self.cmb_weighting.findData(WeightingStrategy.GIBBS))
        self._set_program_mode_value("auto")
        self.spin_temp.setValue(298.15)
        self.log.clear()
        self.table.setRowCount(0)
        for card in list(self.cards):
            self._remove_candidate_card(card)
        self._add_candidate_card(CandidateCardState(name="isomer_A"))
        self._refresh_experimental_summary()
        self._update_run_readiness()

    def _save_project(self) -> None:
        if not self._validate_candidate_cards():
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Project",
            self.project_path or os.path.join(os.getcwd(), "dp4_project.json"),
            "JSON Files (*.json)",
        )
        if not path:
            return
        config = self._collect_config()
        config.to_json(path)
        self.project_path = path
        self.append_log(f"Project saved to {path}")

    def _open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", os.getcwd(), "JSON Files (*.json)")
        if not path:
            return
        try:
            config = DP4Config.from_json(path)
        except Exception as exc:
            QMessageBox.critical(self, "Open Project Failed", str(exc))
            return
        self.project_path = path
        self._load_config(config)
        self.append_log(f"Project loaded from {path}")

    def _load_config(self, config: DP4Config) -> None:
        self.ed_exp.setText(config.exp_nmr_file)
        self.ed_output.setText(config.output_dir)
        self.chk_h.setChecked("1H" in config.nuclei)
        self.chk_c.setChecked("13C" in config.nuclei)
        self.cmb_weighting.setCurrentIndex(self.cmb_weighting.findData(config.weighting))
        self._set_program_mode_value(config.program_mode)
        self.spin_temp.setValue(config.temperature)

        for card in list(self.cards):
            self._remove_candidate_card(card)

        candidate_paths = dict(config.candidate_paths)
        if not candidate_paths and config.candidates_root:
            try:
                candidate_paths = dict(discover_candidate_directories(config.candidates_root))
            except Exception:
                candidate_paths = {}

        for name, directory in candidate_paths.items():
            self._add_candidate_card(
                CandidateCardState(
                    name=name,
                    directory=directory,
                    pairing_overrides=dict(config.pairing_overrides.get(name, {})),
                )
            )
        if not candidate_paths:
            self._add_candidate_card(CandidateCardState(name="isomer_A"))
        self._refresh_experimental_summary()
        self._update_run_readiness()


def main() -> int:  # pragma: no cover
    app = QApplication(sys.argv)
    window = MainWindow()
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
