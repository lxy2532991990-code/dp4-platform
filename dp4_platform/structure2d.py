"""2D molecular viewer — ChemDraw-like output via RDKit CoordGen + ACS 1996.

Pipeline: 3D (xyz) coordinates -> rdDetermineBonds (bond orders, aromaticity)
-> optimized 2D layout (CoordGen / RDKit sampled cleanup / optional mimic-3D)
-> ACS 1996 style SVG via MolDraw2DSVG. A transparent hit overlay keeps atom
picking working on top of the rendered SVG.
"""

from __future__ import annotations

import math
from itertools import combinations
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

from .structure_model import infer_bonds

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
LABEL_DIRECTION_EPSILON = 0.10
DEPiction_SAMPLE_SEED = 0xC0FFEE
DEFAULT_LAYOUT_ENGINE = "cleanup"


def _rgb(color: tuple[float, float, float]) -> tuple[float, float, float]:
    return color


def _hydrogen_neighbors(atom: "Chem.Atom") -> list["Chem.Atom"]:
    return [n for n in atom.GetNeighbors() if n.GetAtomicNum() == 1]


def _heavy_neighbors(atom: "Chem.Atom") -> list["Chem.Atom"]:
    return [n for n in atom.GetNeighbors() if n.GetAtomicNum() != 1]


def _vec2(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return (b[0] - a[0], b[1] - a[1])


def _norm2(v: tuple[float, float]) -> float:
    return math.hypot(v[0], v[1])


def _unit2(v: tuple[float, float]) -> tuple[float, float]:
    n = _norm2(v)
    if n <= 1e-12:
        return (0.0, 0.0)
    return (v[0] / n, v[1] / n)


def _dot2(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _distance2(a: tuple[float, float], b: tuple[float, float]) -> float:
    return _norm2(_vec2(a, b))


def _angle_deg(
    center: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    va = _unit2(_vec2(center, a))
    vb = _unit2(_vec2(center, b))
    dot = max(-1.0, min(1.0, _dot2(va, vb)))
    return math.degrees(math.acos(dot))


def _cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _segments_intersect(
    p1: tuple[float, float],
    p2: tuple[float, float],
    q1: tuple[float, float],
    q2: tuple[float, float],
) -> bool:
    """Proper segment intersection test used for bond-crossing penalties."""
    eps = 1e-9
    d1 = _cross(p1, p2, q1)
    d2 = _cross(p1, p2, q2)
    d3 = _cross(q1, q2, p1)
    d4 = _cross(q1, q2, p2)

    return (
        ((d1 > eps and d2 < -eps) or (d1 < -eps and d2 > eps))
        and ((d3 > eps and d4 < -eps) or (d3 < -eps and d4 > eps))
    )


def _local_crowding_score(
    conf: "Chem.Conformer",
    atom_idx: int,
    bond_partner_idx: int,
) -> float:
    """Estimate how crowded the left/right side of a terminal label is.

    Positive score means the +x side is more crowded; negative score means the
    -x side is more crowded. This is used only to choose between e.g. OH and HO.
    """
    atom_pos = conf.GetAtomPosition(atom_idx)
    partner_pos = conf.GetAtomPosition(bond_partner_idx)
    origin = (float(atom_pos.x), float(atom_pos.y))
    bond_vec = _unit2((float(partner_pos.x - atom_pos.x), float(partner_pos.y - atom_pos.y)))
    if bond_vec == (0.0, 0.0):
        return 0.0

    # Use a horizontal proxy first because text runs left-to-right; then add a
    # small crowding term from nearby atoms to avoid obvious collisions.
    balance = bond_vec[0]
    score = balance * 1.6
    mol = conf.GetOwningMol()
    for other_idx in range(mol.GetNumAtoms()):
        if other_idx in {atom_idx, bond_partner_idx}:
            continue
        other_pos = conf.GetAtomPosition(other_idx)
        other_xy = (float(other_pos.x), float(other_pos.y))
        dx = other_xy[0] - origin[0]
        dy = other_xy[1] - origin[1]
        dist = math.hypot(dx, dy)
        if dist < 1e-6 or dist > 2.2:
            continue
        score += (dx / dist) / max(dist, 0.25)
    return score


def _oriented_group_label(
    mol: "Chem.Mol",
    atom: "Chem.Atom",
    attachment_neighbor: "Chem.Atom",
    default_label: str,
    reversed_label: str,
) -> str:
    """Flip condensed formulas so the attachment atom stays nearest the bond."""
    if mol.GetNumConformers() == 0:
        return default_label

    try:
        conf = mol.GetConformer()
        score = _local_crowding_score(conf, atom.GetIdx(), attachment_neighbor.GetIdx())
    except Exception:
        return default_label

    if score > LABEL_DIRECTION_EPSILON:
        return reversed_label
    return default_label


def _terminal_group_label(
    mol: "Chem.Mol",
    atom: "Chem.Atom",
    default_label: str,
    reversed_label: str,
) -> str:
    heavy_neighbors = _heavy_neighbors(atom)
    if len(heavy_neighbors) != 1:
        return default_label
    return _oriented_group_label(mol, atom, heavy_neighbors[0], default_label, reversed_label)


def _is_neutral_methyl(atom: "Chem.Atom") -> bool:
    return (
        atom.GetAtomicNum() == 6
        and len(_hydrogen_neighbors(atom)) == 3
        and len(_heavy_neighbors(atom)) == 1
        and atom.GetFormalCharge() == 0
    )


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


def _safe_set_prefer_coordgen(prefer: bool) -> None:
    try:
        if rdDepictor is not None and rdDepictor.IsCoordGenSupportAvailable():
            rdDepictor.SetPreferCoordGen(bool(prefer))
    except Exception:
        pass


def _cleanup_depiction(draw_mol: "Chem.Mol", passes: int = 2) -> None:
    for _ in range(max(1, passes)):
        try:
            rdDepictor.NormalizeDepiction(draw_mol)
        except Exception:
            pass
        try:
            rdDepictor.StraightenDepiction(draw_mol)
        except Exception:
            pass


def _compute_2d_coords_coordgen(draw_mol: "Chem.Mol") -> None:
    _safe_set_prefer_coordgen(True)
    try:
        rdDepictor.LoadDefaultRingSystemTemplates()
    except Exception:
        pass
    try:
        rdDepictor.Compute2DCoords(draw_mol, useRingTemplates=True)
    except TypeError:
        rdDepictor.Compute2DCoords(draw_mol)


def _compute_2d_coords_sampled(draw_mol: "Chem.Mol") -> None:
    _safe_set_prefer_coordgen(False)
    try:
        rdDepictor.LoadDefaultRingSystemTemplates()
    except Exception:
        pass

    # This mode lets RDKit sample branch flips / permutations, which often
    # gives cleaner ChemDraw-like bond angles for flexible side chains.
    try:
        rdDepictor.Compute2DCoords(
            draw_mol,
            canonOrient=True,
            clearConfs=True,
            nFlipsPerSample=3,
            nSample=120,
            sampleSeed=DEPiction_SAMPLE_SEED,
            permuteDeg4Nodes=True,
            useRingTemplates=True,
        )
        return
    except TypeError:
        pass
    except Exception:
        pass

    try:
        rdDepictor.Compute2DCoords(
            draw_mol,
            nFlipsPerSample=3,
            nSample=120,
            sampleSeed=DEPiction_SAMPLE_SEED,
            permuteDeg4Nodes=True,
            useRingTemplates=True,
        )
        return
    except TypeError:
        pass
    except Exception:
        pass

    try:
        rdDepictor.Compute2DCoords(draw_mol, useRingTemplates=True)
    except TypeError:
        rdDepictor.Compute2DCoords(draw_mol)


def _compute_2d_coords_mimic_3d(draw_mol: "Chem.Mol", source_mol: "Chem.Mol") -> None:
    _safe_set_prefer_coordgen(True)
    try:
        rdDepictor.LoadDefaultRingSystemTemplates()
    except Exception:
        pass
    rdDepictor.GenerateDepictionMatching3DStructure(draw_mol, source_mol)


def _depiction_positions(draw_mol: "Chem.Mol") -> dict[int, tuple[float, float]]:
    conf = draw_mol.GetConformer()
    return {
        atom.GetIdx(): (
            float(conf.GetAtomPosition(atom.GetIdx()).x),
            float(conf.GetAtomPosition(atom.GetIdx()).y),
        )
        for atom in draw_mol.GetAtoms()
    }


def _depiction_score(draw_mol: "Chem.Mol") -> float:
    """Lower is better.

    Penalties target exactly the ugly cases users notice in 2D depictions:
    bond crossings, non-bonded overlaps, and overly acute external angles.
    """
    try:
        coords = _depiction_positions(draw_mol)
    except Exception:
        return float("inf")

    try:
        mean_bond = float(rdMolDraw2D.MeanBondLength(draw_mol)) or DEFAULT_MEAN_BOND_LEN
    except Exception:
        mean_bond = DEFAULT_MEAN_BOND_LEN

    score = 0.0
    atoms = list(draw_mol.GetAtoms())
    bonds = list(draw_mol.GetBonds())

    # 1) Penalize close non-bonded heavy atoms.
    for atom_i, atom_j in combinations(atoms, 2):
        if atom_i.GetAtomicNum() == 1 or atom_j.GetAtomicNum() == 1:
            continue
        if draw_mol.GetBondBetweenAtoms(atom_i.GetIdx(), atom_j.GetIdx()) is not None:
            continue
        d = _distance2(coords[atom_i.GetIdx()], coords[atom_j.GetIdx()])
        if d < 0.60 * mean_bond:
            score += 220.0 * (0.60 * mean_bond - d)
        elif d < 0.82 * mean_bond:
            score += 45.0 * (0.82 * mean_bond - d)

    # 2) Penalize bond crossings.
    for bond_a, bond_b in combinations(bonds, 2):
        a = {bond_a.GetBeginAtomIdx(), bond_a.GetEndAtomIdx()}
        b = {bond_b.GetBeginAtomIdx(), bond_b.GetEndAtomIdx()}
        if a & b:
            continue
        p1 = coords[bond_a.GetBeginAtomIdx()]
        p2 = coords[bond_a.GetEndAtomIdx()]
        q1 = coords[bond_b.GetBeginAtomIdx()]
        q2 = coords[bond_b.GetEndAtomIdx()]
        if _segments_intersect(p1, p2, q1, q2):
            score += 1500.0

    # 3) Penalize very acute / collapsed external angles on non-ring atoms.
    for atom in atoms:
        if atom.GetDegree() < 2 or atom.IsInRing():
            continue
        center = coords[atom.GetIdx()]
        neighbor_indices = [n.GetIdx() for n in atom.GetNeighbors()]
        for ni, nj in combinations(neighbor_indices, 2):
            bond_i = draw_mol.GetBondBetweenAtoms(atom.GetIdx(), ni)
            bond_j = draw_mol.GetBondBetweenAtoms(atom.GetIdx(), nj)
            if bond_i is None or bond_j is None:
                continue
            if bond_i.IsInRing() and bond_j.IsInRing():
                continue
            ang = _angle_deg(center, coords[ni], coords[nj])
            if ang < 38.0:
                score += 28.0 * (38.0 - ang)
            elif ang < 52.0:
                score += 4.0 * (52.0 - ang)

    # 4) Mild penalty for extreme aspect ratios; compact drawings are usually nicer.
    xs = [xy[0] for xy in coords.values()]
    ys = [xy[1] for xy in coords.values()]
    width = max(xs) - min(xs) if xs else 1.0
    height = max(ys) - min(ys) if ys else 1.0
    ratio = max(width / max(height, 1e-6), height / max(width, 1e-6))
    if ratio > 4.2:
        score += 12.0 * (ratio - 4.2)

    return score


def _make_candidate_draw_mol(
    source_mol: "Chem.Mol",
    generator_name: str,
) -> "Chem.Mol | None":
    draw_mol = Chem.Mol(source_mol)
    draw_mol.RemoveAllConformers()

    try:
        if generator_name == "coordgen":
            _compute_2d_coords_coordgen(draw_mol)
            _cleanup_depiction(draw_mol, passes=2)
        elif generator_name == "sampled":
            _compute_2d_coords_sampled(draw_mol)
            _cleanup_depiction(draw_mol, passes=2)
        elif generator_name == "mimic3d":
            _compute_2d_coords_mimic_3d(draw_mol, source_mol)
            _cleanup_depiction(draw_mol, passes=1)
        else:
            return None
    except Exception:
        return None
    return draw_mol


def _choose_best_cleanup_candidate(
    source_mol: "Chem.Mol",
    prefer_coordgen: bool,
) -> tuple["Chem.Mol", str]:
    candidate_order = ["coordgen", "sampled"] if prefer_coordgen else ["sampled", "coordgen"]
    best_mol: "Chem.Mol | None" = None
    best_score = float("inf")
    best_engine = candidate_order[0]

    for rank, engine in enumerate(candidate_order):
        cand = _make_candidate_draw_mol(source_mol, engine)
        if cand is None:
            continue
        score = _depiction_score(cand) + rank * 1e-3
        if score < best_score:
            best_mol = cand
            best_score = score
            best_engine = engine

    if best_mol is None:
        fallback = Chem.Mol(source_mol)
        fallback.RemoveAllConformers()
        try:
            _compute_2d_coords_coordgen(fallback)
        except Exception:
            try:
                _compute_2d_coords_sampled(fallback)
            except Exception:
                rdDepictor.Compute2DCoords(fallback)
        _cleanup_depiction(fallback, passes=1)
        return fallback, "fallback"

    return best_mol, best_engine


def _make_draw_mol(
    source_mol: "Chem.Mol",
    mimic_3d: bool,
    prefer_coordgen: bool,
) -> tuple["Chem.Mol", str]:
    """Return a clean 2D conformer ready for drawing plus its layout engine."""
    if mimic_3d and source_mol.GetNumConformers() > 0:
        mimic = _make_candidate_draw_mol(source_mol, "mimic3d")
        if mimic is not None:
            return mimic, "mimic3d"
    return _choose_best_cleanup_candidate(source_mol, prefer_coordgen=prefer_coordgen)


def compute_rdkit_2d_coordinates(
    coordinates: dict[int, tuple[float, float, float]],
    elements: dict[int, str],
    charge: int = 0,
    mimic_3d: bool = False,
    prefer_coordgen: bool = True,
) -> dict[int, tuple[float, float]]:
    """Return optimized 2D coordinates keyed by atom id.

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

    draw_mol, _engine = _make_draw_mol(mol, mimic_3d=mimic_3d, prefer_coordgen=prefer_coordgen)
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
        self._layout_engine: str = DEFAULT_LAYOUT_ENGINE
        self._bond_perception_fallback_used: bool = False

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

    def layout_engine(self) -> str:
        return self._layout_engine

    def used_bond_perception_fallback(self) -> bool:
        return self._bond_perception_fallback_used

    def set_total_charge(self, charge: int) -> None:
        """Change the assumed net charge; re-runs bond perception."""
        if charge == self._total_charge:
            return
        self._total_charge = int(charge)
        self._rebuild_from_scratch()

    def set_mimic_3d(self, mimic_3d: bool) -> None:
        """Anchor the 2D layout to the 3D geometry instead of pure cleanup."""
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
        self._layout_engine = DEFAULT_LAYOUT_ENGINE
        self._bond_perception_fallback_used = False

        if not self._coordinates:
            self._draw_message("No coordinates available in parsed calculation output")
            return

        if Chem is None or rdMolDraw2D is None or rdDepictor is None:
            self._draw_message("RDKit 未安装，无法生成二维结构。")
            return

        try:
            mol, atom_index_by_id = _build_mol_with_conformer(self._coordinates, self._elements)
            if not _perceive_bond_orders(mol, self._total_charge):
                self._bond_perception_fallback_used = True
                _add_fallback_single_bonds(
                    mol, self._coordinates, self._elements, atom_index_by_id
                )
            draw_mol, layout_engine = _make_draw_mol(
                mol,
                mimic_3d=self._mimic_3d,
                prefer_coordgen=self._prefer_coordgen,
            )
        except Exception as exc:
            self._draw_message(str(exc) or "无法生成二维结构。")
            return

        self._mol = draw_mol
        self._layout_engine = layout_engine
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
        display_mol, orig_to_draw, custom_labels, hidden_atom_parents = (
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
            hidden_atom_parents,
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
                # Atom was collapsed into a condensed label. Anchor its hit
                # disc at the parent atom so NMR picking still works.
                parent_orig = hidden_atom_parents.get(orig_idx)
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
        """Return a drawing-only molecule with terminal hydrogens collapsed.

        The returned tuple contains:
        - display_mol: a copy of ``source_mol`` with explicit Hs removed
        - orig_to_draw: original atom idx -> display_mol atom idx
        - custom_labels: original heavy-atom idx -> condensed formula label
        - hidden_atom_parents: hidden original idx -> visible original parent idx
        """
        work = Chem.Mol(source_mol)
        for atom in work.GetAtoms():
            atom.SetAtomMapNum(atom.GetIdx() + 1)

        custom_labels: dict[int, str] = {}
        hidden_atom_parents: dict[int, int] = {}

        for atom in work.GetAtoms():
            if atom.GetAtomicNum() != 1 or atom.GetDegree() != 1:
                continue
            parent = atom.GetNeighbors()[0]
            parent_idx = parent.GetIdx()
            h_idx = atom.GetIdx()

            if parent_idx in custom_labels:
                hidden_atom_parents[h_idx] = parent_idx
                continue

            h_on_parent = len(_hydrogen_neighbors(parent))

            if _is_neutral_methyl(parent):
                hidden_atom_parents[h_idx] = parent_idx
            elif (
                parent.GetAtomicNum() == 8
                and h_on_parent == 1
                and parent.GetFormalCharge() == 0
            ):
                custom_labels[parent_idx] = _terminal_group_label(
                    work, parent, "OH", "HO"
                )
                hidden_atom_parents[h_idx] = parent_idx

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

        return display_mol, orig_to_draw, custom_labels, hidden_atom_parents

    def _build_highlight_maps(
        self,
        orig_to_draw: dict[int, int],
        hidden_atom_parents: dict[int, int],
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
                parent_orig = hidden_atom_parents.get(orig_idx)
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
            apply_color(atom_id=self._highlighted_atom, color=PRIMARY_HIGHLIGHT_2D, radius=PRIMARY_HIGHLIGHT_RADIUS)
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
