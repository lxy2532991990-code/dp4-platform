# Animation Demo Sandbox

Self-contained PyQt6 showcase of interaction-animation patterns for the
DP4 / ECD GUI. **Touches no existing project files** — copy the patterns
you like into `dp4_platform/gui.py` (or `ecd_platform/gui.py`) at your own pace.

## Run

```powershell
.\run.ps1
```

Or directly with the project venv:
```powershell
"..\..\.venv\Scripts\python.exe" demo.py
```

## What's inside

All four widgets share the project's QSS palette
(`#f4f5f8` shell, `#4A7BF7` accent, 18 px / 12 px radii, pill inputs).

| Demo | What you get | Where it fits in DP4 |
|---|---|---|
| **Page transitions** | `SlidingStackedWidget` — a `QStackedWidget` subclass that slides horizontally; call `slideTo(index, "forward"/"backward")` instead of `setCurrentIndex` | The home → workflow navigation, or a wizard-style stepper across "discover → configure → run" |
| **Collapsible sections** | `CollapsibleSection(title)` — clickable header with chevron; `add_content(widget)` fills it; smooth `maximumHeight` tween + chevron rotation | "Advanced overrides" panel, per-candidate detail rows, ECD parameter groups |
| **Status badges** | `AnimatedStatusBadge(state)` — pill that color-tweens between `pending / running / success / failed` with a scale pulse | Per-candidate status column in the candidates table; pipeline phase indicators |
| **Loading indicators** | `CircularSpinner` — looping rotation (`QPropertyAnimation` on a custom `angle` property); `ShimmerProgressBar` — paintEvent-driven progress + shimmer overlay | Compute / scan worker phases (`CandidateScanWorker`, `AutoAssignWorker`) |

## Animation primitives used (cheatsheet)

- **`QPropertyAnimation`** — tween a Qt property over time. Targets either built-in properties (`pos`, `geometry`, `maximumHeight`, `windowOpacity`) or `pyqtProperty` declarations on your custom widget.
- **`QParallelAnimationGroup`** — run multiple animations together (e.g. fade + slide).
- **`QSequentialAnimationGroup`** — chain animations (e.g. scale-up then scale-down for the badge pulse).
- **`QEasingCurve.OutCubic`** — the curve already used by your existing `ModuleCard` hover. Stick with it for visual consistency.
- **`pyqtProperty`** — declares a Python attribute as a Qt property so `QPropertyAnimation` can drive it. Custom-painted widgets use this for `rotation`, `scale`, custom colors etc.

## Porting a pattern back into the real project

1. Copy the relevant class(es) from `demo.py` into a new module, e.g. `dp4_platform/animations.py`.
2. Import where needed: `from dp4_platform.animations import SlidingStackedWidget`.
3. The QSS rules under `APP_QSS` are scoped via object names (`#PrimaryButton`, `#CollapsibleHeader`) — append the relevant blocks into your existing stylesheet in `gui.py:_apply_app_style()`.
4. Run `bun run`-style smoke test: launch the GUI, exercise the new animation, watch for jank or layout-thrash.

## Honest scope

- These are **interaction animations** (#2 from the original Remotion plan). Splash screens (#1) and data-result video reports (#4) are separate work and would actually use Remotion.
- Production-grade additions to consider: respect "reduced motion" accessibility setting, skip animation when the widget isn't visible, throttle on slow systems. Out of scope for the demo.
