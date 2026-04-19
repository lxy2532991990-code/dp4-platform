"""2D molecular structure viewer widget backed by RDKit coordinates."""

from __future__ import annotations

from typing import Iterable

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QVBoxLayout,
    QWidget,
)

from .structure_model import (
    ASSIGNED_COLOR,
    DEFAULT_COLOR,
    ELEMENT_COLORS,
    HIGHLIGHT_COLOR,
    infer_bonds,
)

try:  # pragma: no cover - exercised when RDKit is installed in the environment
    from rdkit import Chem
    from rdkit.Chem import AllChem
except ImportError as exc:  # pragma: no cover - depends on optional runtime state
    Chem = None  # type: ignore[assignment]
    AllChem = None  # type: ignore[assignment]
    RDKIT_IMPORT_ERROR = exc
else:
    RDKIT_IMPORT_ERROR = None


ATOM_RADIUS = 15.0
BOND_WIDTH = 2.2
COORDINATE_SCALE = 70.0
SCENE_PADDING = 36.0


def _rgb_tuple_to_qcolor(color: tuple[float, float, float]) -> QColor:
    return QColor(*(round(channel * 255) for channel in color))


def compute_rdkit_2d_coordinates(
    coordinates: dict[int, tuple[float, float, float]],
    elements: dict[int, str],
) -> dict[int, tuple[float, float]]:
    """Build an RDKit molecule from inferred single bonds and return 2D coords."""
    if Chem is None or AllChem is None:
        raise RuntimeError("RDKit 未安装，无法生成二维结构。")
    if not coordinates:
        return {}

    atom_ids = list(coordinates.keys())
    atom_index_by_id: dict[int, int] = {}
    molecule = Chem.RWMol()

    for atom_id in atom_ids:
        element = elements.get(atom_id, "C") or "C"
        try:
            atom_index_by_id[atom_id] = molecule.AddAtom(Chem.Atom(element))
        except Exception as exc:
            raise ValueError(f"无法创建 RDKit 原子 {element}{atom_id}") from exc

    for atom_a, atom_b in infer_bonds(coordinates, elements):
        molecule.AddBond(
            atom_index_by_id[atom_a],
            atom_index_by_id[atom_b],
            Chem.BondType.SINGLE,
        )

    mol = molecule.GetMol()
    try:
        Chem.SanitizeMol(mol)
    except Exception:
        mol.UpdatePropertyCache(strict=False)

    AllChem.Compute2DCoords(mol)
    conformer = mol.GetConformer()
    return {
        atom_id: (
            float(conformer.GetAtomPosition(rdkit_index).x),
            float(conformer.GetAtomPosition(rdkit_index).y),
        )
        for atom_id, rdkit_index in atom_index_by_id.items()
    }


class _FittingGraphicsView(QGraphicsView):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self.fit_scene()

    def fit_scene(self) -> None:
        scene = self.scene()
        if scene is None:
            return
        rect = scene.itemsBoundingRect().adjusted(
            -SCENE_PADDING,
            -SCENE_PADDING,
            SCENE_PADDING,
            SCENE_PADDING,
        )
        if rect.isNull():
            return
        scene.setSceneRect(rect)
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)


class _AtomItem(QGraphicsEllipseItem):
    def __init__(
        self,
        owner: "Structure2DView",
        atom_id: int,
        pickable: bool,
        rect: QRectF,
    ) -> None:
        super().__init__(rect)
        self._owner = owner
        self._atom_id = atom_id
        self._pickable = pickable
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton if pickable else Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(pickable)
        self.setZValue(2)

    def set_pickable(self, pickable: bool) -> None:
        self._pickable = pickable
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton if pickable else Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(pickable)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self._pickable and event.button() == Qt.MouseButton.LeftButton:
            self._owner.atom_clicked.emit(self._atom_id)
            event.accept()
            return
        super().mousePressEvent(event)


class Structure2DView(QWidget):
    """Embeddable 2D viewer that renders RDKit-generated atom coordinates."""

    atom_clicked = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.graphics_view = _FittingGraphicsView(self)
        self.graphics_view.setScene(self.scene)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.graphics_view)

        self._coordinates: dict[int, tuple[float, float, float]] = {}
        self._elements: dict[int, str] = {}
        self._active_nuclei: tuple[str, ...] = ("1H", "13C")
        self._atom_items: dict[int, _AtomItem] = {}
        self._highlighted_atom: int | None = None
        self._assigned_atoms: set[int] = set()
        self._draw_message("No coordinates available in parsed calculation output")

    def clear(self) -> None:
        self.scene.clear()
        self._atom_items.clear()
        self._highlighted_atom = None
        self._assigned_atoms = set()

    def set_structure(
        self,
        coordinates: dict[int, tuple[float, float, float]],
        elements: dict[int, str],
        active_nuclei: Iterable[str],
    ) -> None:
        self.clear()
        self._coordinates = dict(coordinates)
        self._elements = dict(elements)
        self._active_nuclei = tuple(active_nuclei)

        if not self._coordinates:
            self._draw_message("No coordinates available in parsed calculation output")
            return

        try:
            coordinates_2d = compute_rdkit_2d_coordinates(self._coordinates, self._elements)
        except Exception as exc:
            self._draw_message(str(exc) or "无法生成二维结构。")
            return

        points = self._scaled_points(coordinates_2d)
        self._draw_bonds(points)
        self._draw_atoms(points)
        self.graphics_view.fit_scene()

    def set_active_nuclei(self, active_nuclei: Iterable[str]) -> None:
        self._active_nuclei = tuple(active_nuclei)
        for atom_id, item in self._atom_items.items():
            item.set_pickable(self._is_pickable(self._elements.get(atom_id, "")))
            self._apply_style(atom_id)

    def set_highlighted_atom(self, atom_id: int | None) -> None:
        if atom_id == self._highlighted_atom:
            return
        previous = self._highlighted_atom
        self._highlighted_atom = atom_id
        if previous is not None:
            self._apply_style(previous)
        if atom_id is not None:
            self._apply_style(atom_id)

    def set_assigned_atoms(self, atom_ids: Iterable[int]) -> None:
        new_set = set(atom_ids)
        changed = new_set.symmetric_difference(self._assigned_atoms)
        self._assigned_atoms = new_set
        for atom_id in changed:
            self._apply_style(atom_id)

    def _scaled_points(self, coordinates_2d: dict[int, tuple[float, float]]) -> dict[int, tuple[float, float]]:
        if not coordinates_2d:
            return {}
        xs = [point[0] for point in coordinates_2d.values()]
        ys = [point[1] for point in coordinates_2d.values()]
        center_x = (min(xs) + max(xs)) / 2.0
        center_y = (min(ys) + max(ys)) / 2.0
        return {
            atom_id: ((x - center_x) * COORDINATE_SCALE, -(y - center_y) * COORDINATE_SCALE)
            for atom_id, (x, y) in coordinates_2d.items()
        }

    def _draw_bonds(self, points: dict[int, tuple[float, float]]) -> None:
        pen = QPen(QColor("#555555"), BOND_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        for atom_a, atom_b in infer_bonds(self._coordinates, self._elements):
            if atom_a not in points or atom_b not in points:
                continue
            x1, y1 = points[atom_a]
            x2, y2 = points[atom_b]
            line = self.scene.addLine(x1, y1, x2, y2, pen)
            line.setZValue(0)

    def _draw_atoms(self, points: dict[int, tuple[float, float]]) -> None:
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        for atom_id, (x, y) in points.items():
            element = self._elements.get(atom_id, "C")
            rect = QRectF(x - ATOM_RADIUS, y - ATOM_RADIUS, ATOM_RADIUS * 2, ATOM_RADIUS * 2)
            item = _AtomItem(self, atom_id, self._is_pickable(element), rect)
            self.scene.addItem(item)
            self._atom_items[atom_id] = item

            label = QGraphicsTextItem(f"{element}{atom_id}")
            label.setFont(font)
            label.setDefaultTextColor(QColor("#111111"))
            label_rect = label.boundingRect()
            label.setPos(x - label_rect.width() / 2.0, y - label_rect.height() / 2.0)
            label.setZValue(3)
            self.scene.addItem(label)
            self._apply_style(atom_id)

    def _draw_message(self, text: str) -> None:
        self.scene.clear()
        message = self.scene.addText(text)
        message.setDefaultTextColor(QColor("#333333"))
        message.setTextWidth(360)
        message.setPos(-180, -20)
        self.graphics_view.fit_scene()

    def _is_pickable(self, element: str) -> bool:
        if element == "C":
            return "13C" in self._active_nuclei
        if element == "H":
            return "1H" in self._active_nuclei
        return False

    def _apply_style(self, atom_id: int) -> None:
        item = self._atom_items.get(atom_id)
        if item is None:
            return
        element = self._elements.get(atom_id, "")
        if atom_id == self._highlighted_atom:
            color = _rgb_tuple_to_qcolor(HIGHLIGHT_COLOR)
            pen = QPen(QColor("#6b5600"), 2.2)
        elif atom_id in self._assigned_atoms:
            color = _rgb_tuple_to_qcolor(ASSIGNED_COLOR)
            pen = QPen(QColor("#1d5d2e"), 1.8)
        else:
            color = _rgb_tuple_to_qcolor(ELEMENT_COLORS.get(element, DEFAULT_COLOR))
            pen = QPen(QColor("#444444"), 1.3)
        if not self._is_pickable(element):
            color.setAlpha(185)
        item.setBrush(QBrush(color))
        item.setPen(pen)
