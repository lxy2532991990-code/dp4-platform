"""3D molecular structure viewer widget backed by pyvistaqt."""

from __future__ import annotations

from typing import Iterable

import numpy as np

import pyvista as pv
from pyvistaqt import QtInteractor

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget


ELEMENT_COLORS: dict[str, tuple[float, float, float]] = {
    "H": (0.90, 0.90, 0.90),
    "C": (0.25, 0.25, 0.25),
    "N": (0.19, 0.31, 0.97),
    "O": (0.94, 0.16, 0.16),
    "F": (0.56, 0.88, 0.31),
    "P": (1.00, 0.50, 0.00),
    "S": (1.00, 1.00, 0.19),
    "Cl": (0.12, 0.94, 0.12),
    "Br": (0.65, 0.16, 0.16),
    "I": (0.58, 0.00, 0.58),
}
DEFAULT_COLOR = (0.55, 0.55, 0.55)

DISPLAY_RADIUS: dict[str, float] = {
    "H": 0.22,
    "C": 0.35,
    "N": 0.34,
    "O": 0.33,
    "F": 0.32,
    "P": 0.42,
    "S": 0.42,
    "Cl": 0.40,
    "Br": 0.45,
    "I": 0.50,
}
DEFAULT_RADIUS = 0.32

COVALENT_RADIUS: dict[str, float] = {
    "H": 0.31,
    "C": 0.76,
    "N": 0.71,
    "O": 0.66,
    "F": 0.57,
    "P": 1.07,
    "S": 1.05,
    "Cl": 1.02,
    "Br": 1.20,
    "I": 1.39,
}
DEFAULT_COVALENT = 0.80
BOND_TOLERANCE = 0.40

HIGHLIGHT_COLOR = (1.00, 0.85, 0.10)
ASSIGNED_COLOR = (0.25, 0.75, 0.35)


class StructureView(QWidget):
    """Embeddable 3D viewer that renders atoms as pickable spheres.

    Emits `atom_clicked(atom_id)` on left-click of a C/H atom when that nucleus
    is active. `set_highlighted_atom` and `set_assigned_atoms` update colors
    without rebuilding the scene.
    """

    atom_clicked = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.plotter = QtInteractor(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plotter.interactor)
        try:
            self.plotter.set_background("white")
            self.plotter.render()
        except Exception:
            pass

        self._coordinates: dict[int, tuple[float, float, float]] = {}
        self._elements: dict[int, str] = {}
        self._active_nuclei: tuple[str, ...] = ("1H", "13C")
        self._actor_by_atom: dict[int, object] = {}
        self._atom_by_actor_id: dict[int, int] = {}
        self._highlighted_atom: int | None = None
        self._assigned_atoms: set[int] = set()
        self._closed: bool = False

    def close_plotter(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.plotter.disable_picking()
        except Exception:
            pass
        try:
            self.plotter.close()
        except Exception:
            pass

    def clear(self) -> None:
        if self._closed:
            return
        try:
            self.plotter.disable_picking()
        except Exception:
            pass
        self.plotter.clear()
        self._actor_by_atom.clear()
        self._atom_by_actor_id.clear()
        self._highlighted_atom = None
        self._assigned_atoms = set()

    def set_structure(
        self,
        coordinates: dict[int, tuple[float, float, float]],
        elements: dict[int, str],
        active_nuclei: Iterable[str],
    ) -> None:
        if self._closed:
            return
        self.clear()
        self._coordinates = dict(coordinates)
        self._elements = dict(elements)
        self._active_nuclei = tuple(active_nuclei)

        if not self._coordinates:
            self.plotter.add_text(
                "No coordinates available in parsed calculation output",
                font_size=10,
                color="black",
                name="empty_hint",
            )
            self.plotter.reset_camera()
            return

        for atom_id, coord in self._coordinates.items():
            element = self._elements.get(atom_id, "C")
            sphere = pv.Sphere(
                radius=DISPLAY_RADIUS.get(element, DEFAULT_RADIUS),
                center=coord,
                theta_resolution=20,
                phi_resolution=20,
            )
            actor = self.plotter.add_mesh(
                sphere,
                color=ELEMENT_COLORS.get(element, DEFAULT_COLOR),
                name=f"atom_{atom_id}",
                pickable=self._is_pickable(element),
                smooth_shading=True,
                reset_camera=False,
            )
            self._actor_by_atom[atom_id] = actor
            self._atom_by_actor_id[id(actor)] = atom_id

        self._draw_bonds()
        self._draw_labels()

        self.plotter.set_background("white")
        try:
            self.plotter.disable_picking()
        except Exception:
            pass
        try:
            self.plotter.enable_mesh_picking(
                callback=self._on_pick,
                show=False,
                show_message=False,
                left_clicking=True,
                use_actor=True,
            )
        except TypeError:
            self.plotter.enable_mesh_picking(
                callback=self._on_pick,
                show=False,
                use_actor=True,
            )
        self.plotter.reset_camera()

    def set_active_nuclei(self, active_nuclei: Iterable[str]) -> None:
        if self._closed:
            return
        self._active_nuclei = tuple(active_nuclei)
        for atom_id, actor in self._actor_by_atom.items():
            element = self._elements.get(atom_id, "")
            try:
                actor.SetPickable(self._is_pickable(element))
            except Exception:
                pass

    def set_highlighted_atom(self, atom_id: int | None) -> None:
        if self._closed:
            return
        if atom_id == self._highlighted_atom:
            return
        previous = self._highlighted_atom
        self._highlighted_atom = atom_id
        if previous is not None:
            self._apply_color(previous)
        if atom_id is not None:
            self._apply_color(atom_id)
        self._safe_render()

    def set_assigned_atoms(self, atom_ids: Iterable[int]) -> None:
        if self._closed:
            return
        new_set = set(atom_ids)
        changed = new_set.symmetric_difference(self._assigned_atoms)
        self._assigned_atoms = new_set
        for atom_id in changed:
            self._apply_color(atom_id)
        if changed:
            self._safe_render()

    def _safe_render(self) -> None:
        if self._closed:
            return
        try:
            self.plotter.render()
        except Exception:
            pass

    def _is_pickable(self, element: str) -> bool:
        if element == "C":
            return "13C" in self._active_nuclei
        if element == "H":
            return "1H" in self._active_nuclei
        return False

    def _apply_color(self, atom_id: int) -> None:
        actor = self._actor_by_atom.get(atom_id)
        if actor is None:
            return
        element = self._elements.get(atom_id, "")
        if atom_id == self._highlighted_atom:
            color = HIGHLIGHT_COLOR
        elif atom_id in self._assigned_atoms:
            color = ASSIGNED_COLOR
        else:
            color = ELEMENT_COLORS.get(element, DEFAULT_COLOR)
        try:
            actor.GetProperty().SetColor(*color)
        except Exception:
            pass

    def _draw_bonds(self) -> None:
        atom_ids = list(self._coordinates.keys())
        points = np.array([self._coordinates[aid] for aid in atom_ids])
        n = len(atom_ids)
        if n < 2:
            return
        lines: list[list[int]] = []
        point_index: dict[int, int] = {aid: idx for idx, aid in enumerate(atom_ids)}
        for i in range(n):
            for j in range(i + 1, n):
                ei = self._elements.get(atom_ids[i], "C")
                ej = self._elements.get(atom_ids[j], "C")
                ri = COVALENT_RADIUS.get(ei, DEFAULT_COVALENT)
                rj = COVALENT_RADIUS.get(ej, DEFAULT_COVALENT)
                max_bond = ri + rj + BOND_TOLERANCE
                dist = float(np.linalg.norm(points[i] - points[j]))
                if 0.4 < dist < max_bond:
                    lines.append([2, point_index[atom_ids[i]], point_index[atom_ids[j]]])
        if not lines:
            return
        poly = pv.PolyData(points)
        poly.lines = np.array(lines, dtype=np.int32).ravel()
        self.plotter.add_mesh(
            poly,
            color=(0.35, 0.35, 0.35),
            line_width=3,
            pickable=False,
            name="bonds",
            reset_camera=False,
        )

    def _draw_labels(self) -> None:
        points = []
        labels = []
        for atom_id, coord in self._coordinates.items():
            element = self._elements.get(atom_id, "")
            if element not in ("C", "H"):
                continue
            points.append(coord)
            labels.append(f"{element}{atom_id}")
        if not points:
            return
        self.plotter.add_point_labels(
            np.array(points),
            labels,
            font_size=11,
            text_color="black",
            point_size=1,
            render_points_as_spheres=False,
            shape_opacity=0.55,
            shape_color="white",
            name="atom_labels",
            always_visible=True,
            pickable=False,
            reset_camera=False,
        )

    def _on_pick(self, actor) -> None:
        if actor is None:
            return
        atom_id = self._atom_by_actor_id.get(id(actor))
        if atom_id is None:
            for aid, cached in self._actor_by_atom.items():
                if cached is actor:
                    atom_id = aid
                    break
        if atom_id is None:
            return
        element = self._elements.get(atom_id, "")
        if not self._is_pickable(element):
            return
        self.atom_clicked.emit(atom_id)
