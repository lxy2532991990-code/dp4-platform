"""2D molecular viewer — ChemDraw-like output via RDKit CoordGen + ACS 1996.

Pipeline: 3D (xyz) coordinates -> rdDetermineBonds (bond orders, aromaticity)
-> CoordGen 2D layout (optionally anchored to the 3D geometry) -> ACS 1996
style SVG via MolDraw2DSVG. A transparent hit overlay keeps atom picking
working on top of the rendered SVG.
"""

from __future__ import annotations

from typing import Iterable

from PyQt6.QtCore import QByteArray, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtSvgWidgets import QGraphicsSvgItem
from PyQt6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsScene,
    QGraphicsView,
    QVBoxLayout,
    QWidget,
)

from .structure_model import (
    infer_bonds,
)

try:  # pragma: no cover - exercised when RDKit is installed in the environment
    from rdkit import Chem
    from rdkit.Chem import AllChem, rdDepictor, rdDetermineBonds
    from rdkit.Chem.Draw import rdMolDraw2D
    from rdkit.Geometry import Point3D
except ImportError as exc:  # pragma: no cover - depends on optional runtime state
    Chem = None  # type: ignore[assignment]
    AllChem = None  # type: ignore[assignment]
    rdDepictor = None  # type: ignore[assignment]
    rdDetermineBonds = None  # type: ignore[assignment]
    rdMolDraw2D = None  # type: ignore[assignment]
    Point3D = None  # type: ignore[assignment]
    RDKIT_IMPORT_ERROR = exc
else:
    RDKIT_IMPORT_ERROR = None


SCENE_PADDING = 12.0
CLICK_RADIUS_FRACTION = 0.55  # hit-circle radius as a fraction of mean bond length
MIN_CLICK_RADIUS = 8.0
DEFAULT_MEAN_BOND_LEN = 1.0
PRIMARY_HIGHLIGHT_2D = (1.00, 0.70, 0.32)  # warm amber
RELATED_HIGHLIGHT_2D = (0.62, 0.78, 1.00)  # soft blue
ASSIGNED_HIGHLIGHT_2D = (0.63, 0.86, 0.74)  # muted mint
PRIMARY_HIGHLIGHT_RADIUS = 0.24
RELATED_HIGHLIGHT_RADIUS = 0.19
ASSIGNED_HIGHLIGHT_RADIUS = 0.16


def _rgb(color: tuple[float, float, float]) -> tuple[float, float, float]:
    return color


def _build_mol_with_conformer(
    coordinates: dict[int, tuple[float, float, float]],
    elements: dict[int, str],
) -> tuple["Chem.RWMol", dict[int, int]]:
    mol = Chem.RWMol()
    atom_index_by_id: dict[int, int] = {}
    for atom_id in coordinates:
        element = elements.get(atom_id, "C") or "C"
        atom_index_by_id[atom_id] = mol.AddAtom(Chem.Atom(element))
    conf = Chem.Conformer(mol.GetNumAtoms())
    for atom_id, idx in atom_index_by_id.items():
        x, y, z = coordinates[atom_id]
        conf.SetAtomPosition(idx, Point3D(float(x), float(y), float(z)))
    mol.AddConformer(conf, assignId=True)
    return mol, atom_index_by_id


def _perceive_bond_orders(mol: "Chem.RWMol", charge: int) -> bool:
    """Run rdDetermineBonds (xyz2mol) + sanitize. Returns True on success."""
    try:
        rdDetermineBonds.DetermineBonds(mol, charge=charge)
        Chem.SanitizeMol(mol)
        return True
    except Exception:
        return False


def _add_fallback_single_bonds(
    mol: "Chem.RWMol",
    coordinates: dict[int, tuple[float, float, float]],
    elements: dict[int, str],
    atom_index_by_id: dict[int, int],
) -> None:
    """Distance-based single-bond fallback when DetermineBonds fails."""
    for atom_a, atom_b in infer_bonds(coordinates, elements):
        ia = atom_index_by_id[atom_a]
        ib = atom_index_by_id[atom_b]
        if mol.GetBondBetweenAtoms(ia, ib) is None:
            mol.AddBond(ia, ib, Chem.BondType.SINGLE)
    try:
        Chem.SanitizeMol(mol)
    except Exception:
        mol.UpdatePropertyCache(strict=False)


def _make_draw_mol(
    source_mol: "Chem.Mol",
    mimic_3d: bool,
    prefer_coordgen: bool,
) -> "Chem.Mol":
    """Return a copy with a clean 2D conformer ready for drawing."""
    draw_mol = Chem.Mol(source_mol)
    draw_mol.RemoveAllConformers()

    if prefer_coordgen and rdDepictor.IsCoordGenSupportAvailable():
        rdDepictor.SetPreferCoordGen(True)
        try:
            rdDepictor.LoadDefaultRingSystemTemplates()
        except Exception:
            pass

    used_3d_ref = False
    if mimic_3d and source_mol.GetNumConformers() > 0:
        try:
            rdDepictor.GenerateDepictionMatching3DStructure(draw_mol, source_mol)
            used_3d_ref = True
        except Exception:
            used_3d_ref = False

    if not used_3d_ref:
        try:
            rdDepictor.Compute2DCoords(draw_mol, useRingTemplates=True)
        except TypeError:
            rdDepictor.Compute2DCoords(draw_mol)

    try:
        rdDepictor.NormalizeDepiction(draw_mol)
        rdDepictor.StraightenDepiction(draw_mol)
    except Exception:
        pass
    return draw_mol


def compute_rdkit_2d_coordinates(
    coordinates: dict[int, tuple[float, float, float]],
    elements: dict[int, str],
    charge: int = 0,
    mimic_3d: bool = False,
    prefer_coordgen: bool = True,
) -> dict[int, tuple[float, float]]:
    """Return CoordGen 2D coordinates keyed by atom id.

    Bond orders and aromaticity are recovered via ``rdDetermineBonds``; if that
    fails the function falls back to distance-based single bonds so a depiction
    is always produced.
    """
    if Chem is None or AllChem is None or rdDepictor is None:
        raise RuntimeError("RDKit 未安装，无法生成二维结构。")
    if not coordinates:
        return {}

    mol, atom_index_by_id = _build_mol_with_conformer(coordinates, elements)
    if not _perceive_bond_orders(mol, charge):
        _add_fallback_single_bonds(mol, coordinates, elements, atom_index_by_id)

    draw_mol = _make_draw_mol(mol, mimic_3d=mimic_3d, prefer_coordgen=prefer_coordgen)
    conf = draw_mol.GetConformer()
    return {
        atom_id: (float(conf.GetAtomPosition(idx).x), float(conf.GetAtomPosition(idx).y))
        for atom_id, idx in atom_index_by_id.items()
    }


class _FittingGraphicsView(QGraphicsView):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(QColor("#ffffff")))

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


class _AtomHitItem(QGraphicsEllipseItem):
    """Invisible clickable disc placed over each atom in the SVG."""

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
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setBrush(QBrush(Qt.GlobalColor.transparent))
        self.setAcceptedMouseButtons(
            Qt.MouseButton.LeftButton if pickable else Qt.MouseButton.NoButton
        )
        self.setAcceptHoverEvents(pickable)
        self.setZValue(5)

    def set_pickable(self, pickable: bool) -> None:
        self._pickable = pickable
        self.setAcceptedMouseButtons(
            Qt.MouseButton.LeftButton if pickable else Qt.MouseButton.NoButton
        )
        self.setAcceptHoverEvents(pickable)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self._pickable and event.button() == Qt.MouseButton.LeftButton:
            self._owner.atom_clicked.emit(self._atom_id)
            event.accept()
            return
        super().mousePressEvent(event)


class Structure2DView(QWidget):
    """Embeddable ChemDraw-style 2D viewer driven by RDKit."""

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
        self._atom_items: dict[int, _AtomHitItem] = {}
        self._draw_positions: dict[int, tuple[float, float]] = {}
        self._mol: "Chem.Mol | None" = None
        self._atom_index_by_id: dict[int, int] = {}
        self._svg_renderer: QSvgRenderer | None = None
        self._svg_item: QGraphicsSvgItem | None = None
        self._mean_bond_len: float = DEFAULT_MEAN_BOND_LEN
        self._highlighted_atom: int | None = None
        self._related_atoms: set[int] = set()
        self._assigned_atoms: set[int] = set()
        self._total_charge: int = 0
        self._mimic_3d: bool = False
        self._prefer_coordgen: bool = True
        self._monochrome: bool = False

        self._draw_message("No coordinates available in parsed calculation output")

    # ------------------------------------------------------------------ API

    def clear(self) -> None:
        self.scene.clear()
        self._atom_items.clear()
        self._draw_positions.clear()
        self._svg_item = None
        self._svg_renderer = None
        self._mol = None
        self._atom_index_by_id = {}
        self._highlighted_atom = None
        self._related_atoms = set()
        self._assigned_atoms = set()

    def set_total_charge(self, charge: int) -> None:
        """Change the assumed net charge; re-runs bond perception."""
        if charge == self._total_charge:
            return
        self._total_charge = int(charge)
        self._rebuild_from_scratch()

    def set_mimic_3d(self, mimic_3d: bool) -> None:
        """Anchor the 2D layout to the 3D geometry instead of pure CoordGen."""
        if mimic_3d == self._mimic_3d:
            return
        self._mimic_3d = bool(mimic_3d)
        self._rebuild_from_scratch()

    def set_prefer_coordgen(self, prefer: bool) -> None:
        if prefer == self._prefer_coordgen:
            return
        self._prefer_coordgen = bool(prefer)
        self._rebuild_from_scratch()

    def set_monochrome(self, monochrome: bool) -> None:
        """Toggle black-and-white ACS 1996 rendering."""
        if monochrome == self._monochrome:
            return
        self._monochrome = bool(monochrome)
        if self._mol is not None:
            self._rerender_svg()

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

        if Chem is None or rdMolDraw2D is None or rdDepictor is None:
            self._draw_message("RDKit 未安装，无法生成二维结构。")
            return

        try:
            mol, atom_index_by_id = _build_mol_with_conformer(self._coordinates, self._elements)
            if not _perceive_bond_orders(mol, self._total_charge):
                _add_fallback_single_bonds(
                    mol, self._coordinates, self._elements, atom_index_by_id
                )
            draw_mol = _make_draw_mol(
                mol, mimic_3d=self._mimic_3d, prefer_coordgen=self._prefer_coordgen
            )
        except Exception as exc:
            self._draw_message(str(exc) or "无法生成二维结构。")
            return

        self._mol = draw_mol
        self._atom_index_by_id = atom_index_by_id
        try:
            self._mean_bond_len = float(rdMolDraw2D.MeanBondLength(draw_mol)) or DEFAULT_MEAN_BOND_LEN
        except Exception:
            self._mean_bond_len = DEFAULT_MEAN_BOND_LEN

        self._render_svg_and_overlay()
        self.graphics_view.fit_scene()

    def set_active_nuclei(self, active_nuclei: Iterable[str]) -> None:
        self._active_nuclei = tuple(active_nuclei)
        for atom_id, item in self._atom_items.items():
            item.set_pickable(self._is_pickable(self._elements.get(atom_id, "")))

    def set_highlighted_atom(self, atom_id: int | None) -> None:
        if atom_id == self._highlighted_atom:
            return
        self._highlighted_atom = atom_id
        if self._mol is not None:
            self._rerender_svg()

    def set_related_atoms(self, atom_ids: Iterable[int]) -> None:
        new_set = set(atom_ids)
        if new_set == self._related_atoms:
            return
        self._related_atoms = new_set
        if self._mol is not None:
            self._rerender_svg()

    def set_assigned_atoms(self, atom_ids: Iterable[int]) -> None:
        new_set = set(atom_ids)
        if new_set == self._assigned_atoms:
            return
        self._assigned_atoms = new_set
        if self._mol is not None:
            self._rerender_svg()

    # ------------------------------------------------------------- internal

    def _rebuild_from_scratch(self) -> None:
        if not self._coordinates:
            return
        self.set_structure(self._coordinates, self._elements, self._active_nuclei)

    def _render_svg_and_overlay(self) -> None:
        svg_text, draw_positions, canvas = self._render_svg_text()
        self._draw_positions = draw_positions
        self._install_svg(svg_text, canvas)
        self._install_hit_items()

    def _rerender_svg(self) -> None:
        if self._svg_item is None:
            self._render_svg_and_overlay()
            self.graphics_view.fit_scene()
            return
        svg_text, draw_positions, _canvas = self._render_svg_text()
        # ACS 1996 uses a fixed scaling factor, so the atom pixel positions are
        # stable across re-renders for the same molecule. Refresh them anyway
        # to stay correct if options ever change the scale.
        self._draw_positions = draw_positions
        renderer = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
        self._svg_renderer = renderer
        self._svg_item.setSharedRenderer(renderer)
        self._svg_item.update()
        self._reposition_hit_items()

    def _render_svg_text(self) -> tuple[str, dict[int, tuple[float, float]], tuple[int, int]]:
        assert self._mol is not None
        display_mol, orig_to_draw, custom_labels, hidden_h_parents = (
            self._build_display_mol_and_maps(self._mol)
        )

        # Flexi-canvas: ACS 1996 proportions drive the intrinsic SVG size; we
        # then scale it in the view so the structure fills the widget.
        drawer = rdMolDraw2D.MolDraw2DSVG(-1, -1)
        opts = drawer.drawOptions()
        try:
            rdMolDraw2D.SetACS1996Mode(opts, self._mean_bond_len)
        except Exception:
            pass
        if not self._monochrome:
            try:
                opts.useDefaultAtomPalette()
            except Exception:
                pass
        opts.addStereoAnnotation = True
        opts.padding = 0.06
        opts.atomHighlightsAreCircles = True
        opts.fillHighlights = True
        opts.continuousHighlight = False
        opts.highlightBondWidthMultiplier = 1
        opts.scaleHighlightBondWidth = False

        for orig_idx, label in custom_labels.items():
            draw_idx = orig_to_draw.get(orig_idx)
            if draw_idx is not None:
                opts.atomLabels[draw_idx] = label

        try:
            prepared = rdMolDraw2D.PrepareMolForDrawing(
                display_mol, kekulize=True, addChiralHs=False, wedgeBonds=True
            )
        except Exception:
            prepared = display_mol

        highlight_atoms, highlight_colors, highlight_radii = self._build_highlight_maps(
            orig_to_draw,
            hidden_h_parents,
        )

        try:
            drawer.DrawMolecule(
                prepared,
                highlight_atoms,
                [],
                highlight_colors,
                {},
                highlight_radii,
            )
        except Exception:
            drawer.DrawMolecule(prepared)
        drawer.FinishDrawing()
        svg_text = drawer.GetDrawingText()

        draw_positions: dict[int, tuple[float, float]] = {}
        for atom_id, orig_idx in self._atom_index_by_id.items():
            draw_idx = orig_to_draw.get(orig_idx)
            if draw_idx is None:
                # Atom was collapsed (hidden H). Anchor its hit disc at the
                # parent heavy atom so NMR picking on CH3/OH still works.
                parent_orig = hidden_h_parents.get(orig_idx)
                if parent_orig is None:
                    continue
                draw_idx = orig_to_draw.get(parent_orig)
                if draw_idx is None:
                    continue
            try:
                point = drawer.GetDrawCoords(draw_idx)
            except Exception:
                continue
            draw_positions[atom_id] = (float(point.x), float(point.y))

        canvas = (int(drawer.Width()), int(drawer.Height()))
        return svg_text, draw_positions, canvas

    def _build_display_mol_and_maps(
        self, source_mol: "Chem.Mol"
    ) -> tuple["Chem.Mol", dict[int, int], dict[int, str], dict[int, int]]:
        """Return a drawing-only molecule with CH3/OH hydrogens collapsed.

        The returned tuple contains:
        - display_mol: a copy of ``source_mol`` with explicit Hs removed
        - orig_to_draw: original atom idx -> display_mol atom idx
        - custom_labels: original heavy-atom idx -> "CH3" or "OH"
        - hidden_h_parents: original H idx -> original parent heavy-atom idx
        """
        work = Chem.Mol(source_mol)
        for atom in work.GetAtoms():
            atom.SetAtomMapNum(atom.GetIdx() + 1)

        custom_labels: dict[int, str] = {}
        hidden_h_parents: dict[int, int] = {}

        for atom in work.GetAtoms():
            if atom.GetAtomicNum() != 1 or atom.GetDegree() != 1:
                continue
            parent = atom.GetNeighbors()[0]
            parent_idx = parent.GetIdx()
            h_idx = atom.GetIdx()

            if parent_idx in custom_labels:
                hidden_h_parents[h_idx] = parent_idx
                continue

            h_on_parent = sum(
                1 for n in parent.GetNeighbors() if n.GetAtomicNum() == 1
            )
            heavy_on_parent = sum(
                1 for n in parent.GetNeighbors() if n.GetAtomicNum() != 1
            )

            if (
                parent.GetAtomicNum() == 6
                and h_on_parent == 3
                and heavy_on_parent == 1
                and parent.GetFormalCharge() == 0
            ):
                custom_labels[parent_idx] = "CH3"
                hidden_h_parents[h_idx] = parent_idx
            elif (
                parent.GetAtomicNum() == 8
                and h_on_parent == 1
                and parent.GetFormalCharge() == 0
            ):
                custom_labels[parent_idx] = "OH"
                hidden_h_parents[h_idx] = parent_idx

        try:
            display_mol = Chem.RemoveHs(work)
        except Exception:
            display_mol = work

        orig_to_draw: dict[int, int] = {}
        for atom in display_mol.GetAtoms():
            map_num = atom.GetAtomMapNum()
            if map_num <= 0:
                continue
            orig_to_draw[map_num - 1] = atom.GetIdx()
            atom.SetAtomMapNum(0)

        return display_mol, orig_to_draw, custom_labels, hidden_h_parents

    def _build_highlight_maps(
        self,
        orig_to_draw: dict[int, int],
        hidden_h_parents: dict[int, int],
    ) -> tuple[
        list[int],
        dict[int, tuple[float, float, float]],
        dict[int, float],
    ]:
        atoms: list[int] = []
        colors: dict[int, tuple[float, float, float]] = {}
        radii: dict[int, float] = {}

        def draw_index_for_atom(atom_id: int) -> int | None:
            orig_idx = self._atom_index_by_id.get(atom_id)
            if orig_idx is None:
                return None
            draw_idx = orig_to_draw.get(orig_idx)
            if draw_idx is None:
                parent_orig = hidden_h_parents.get(orig_idx)
                if parent_orig is not None:
                    draw_idx = orig_to_draw.get(parent_orig)
            return draw_idx

        def apply_color(
            atom_id: int,
            color: tuple[float, float, float],
            radius: float,
        ) -> None:
            draw_idx = draw_index_for_atom(atom_id)
            if draw_idx is None:
                return
            if draw_idx not in atoms:
                atoms.append(draw_idx)
            colors[draw_idx] = _rgb(color)
            radii[draw_idx] = radius

        for atom_id in self._assigned_atoms:
            apply_color(atom_id, ASSIGNED_HIGHLIGHT_2D, ASSIGNED_HIGHLIGHT_RADIUS)
        for atom_id in self._related_atoms:
            if atom_id != self._highlighted_atom:
                apply_color(atom_id, RELATED_HIGHLIGHT_2D, RELATED_HIGHLIGHT_RADIUS)
        if self._highlighted_atom is not None:
            apply_color(self._highlighted_atom, PRIMARY_HIGHLIGHT_2D, PRIMARY_HIGHLIGHT_RADIUS)
        return atoms, colors, radii

    def _install_svg(self, svg_text: str, canvas: tuple[int, int]) -> None:
        renderer = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
        item = QGraphicsSvgItem()
        item.setSharedRenderer(renderer)
        item.setPos(0.0, 0.0)
        item.setZValue(0)
        self.scene.addItem(item)
        self._svg_renderer = renderer
        self._svg_item = item

        width, height = canvas
        if width > 0 and height > 0:
            # Make sure the scene rect always contains the canvas even before
            # the first fitInView pass.
            self.scene.setSceneRect(0.0, 0.0, float(width), float(height))

    def _install_hit_items(self) -> None:
        self._atom_items.clear()
        radius = max(MIN_CLICK_RADIUS, CLICK_RADIUS_FRACTION * self._scaled_bond_pixels())
        for atom_id, (x, y) in self._draw_positions.items():
            element = self._elements.get(atom_id, "")
            rect = QRectF(x - radius, y - radius, radius * 2, radius * 2)
            item = _AtomHitItem(self, atom_id, self._is_pickable(element), rect)
            self.scene.addItem(item)
            self._atom_items[atom_id] = item

    def _reposition_hit_items(self) -> None:
        radius = max(MIN_CLICK_RADIUS, CLICK_RADIUS_FRACTION * self._scaled_bond_pixels())
        for atom_id, item in self._atom_items.items():
            point = self._draw_positions.get(atom_id)
            if point is None:
                continue
            x, y = point
            item.setRect(QRectF(x - radius, y - radius, radius * 2, radius * 2))

    def _scaled_bond_pixels(self) -> float:
        # ACS 1996 sets scalingFactor = 14.4 / meanBondLength; a bond therefore
        # renders at ~14.4 pixels. We use that to size the hit discs.
        return 14.4

    def _draw_message(self, text: str) -> None:
        self.scene.clear()
        self._atom_items.clear()
        self._svg_item = None
        self._svg_renderer = None
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
