"""The chamber's performance contract, enforced as a source check.

Every item below is cheap to write and cheap to lose. A refactor that drops
`invalidate()` under `frameloop="demand"` produces a view that renders once and
then freezes on interaction; one that drops `stopPropagation` fires every
instance behind the cursor; one that drops `worker.terminate()` leaks a
simulation per mount. None of these fail loudly, so they are checked here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHAMBER = ROOT / "web" / "src" / "chamber"
GRAPH = ROOT / "web" / "src" / "graph.json"


def src(name: str) -> str:
    path = CHAMBER / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    return path.read_text(encoding="utf-8")


def test_layout_runs_in_a_worker_and_transfers_a_float32array():
    worker = src("layout.worker.js")
    assert "d3-force-3d" in worker, "layout is not using the 3D force simulation"
    assert "new Float32Array" in worker
    # Transferred, not copied: structured-cloning thousands of {x,y,z} objects
    # per tick costs more than the layout.
    assert "[positions.buffer]" in worker, "positions are copied, not transferred"


def test_the_worker_is_disposed_and_terminated_on_unmount():
    hook = src("useGraphLayout.js")
    assert "worker.terminate()" in hook, "the worker leaks on unmount"
    assert "'dispose'" in hook or '"dispose"' in hook


def test_invalidate_is_called_on_every_position_update():
    """Under frameloop="demand" nothing repaints without it."""
    hook = src("useGraphLayout.js")
    assert "invalidate()" in hook
    scene = src("Chamber.jsx")
    assert 'frameloop="demand"' in scene
    # Every buffer-writing effect must invalidate, or the scrubber silently
    # updates data that is never painted.
    assert scene.count("invalidate()") >= 3, "a position update path never repaints"


def test_nodes_are_instanced_and_edges_are_a_single_linesegments():
    scene = src("Chamber.jsx")
    assert "instancedMesh" in scene
    assert "lineSegments" in scene
    assert "setMatrixAt" in scene and "instanceMatrix.needsUpdate" in scene
    # 12x12 is indistinguishable from 32x32 at graph scale and costs a fraction.
    assert "SphereGeometry(1.7, 12, 12)" in scene


def test_node_kind_is_geometry_and_risk_is_colour():
    """Colour alone must never carry kind: it has to stay free for state, and a
    colour-blind reader has to be able to tell an identity from a device."""
    scene = src("Chamber.jsx")
    for geom in ("SphereGeometry", "BoxGeometry", "OctahedronGeometry", "TetrahedronGeometry"):
        assert geom in scene, f"{geom} missing - kinds are not distinguished by shape"
    assert "RISK = {" in scene and "flagged" in scene and "cleared" in scene


def test_pointer_handlers_stop_propagation_and_raycasting_is_throttled():
    scene = src("Chamber.jsx")
    assert scene.count("e.stopPropagation()") >= 2, "instances behind the cursor will fire"
    assert "performance.now()" in scene and "< 30" in scene, "raycasting is unthrottled"
    assert "raycast={null}" in scene, "edges are being raycast against"


def test_the_highlight_is_a_separate_object_under_exactly_one_effect():
    scene = src("Chamber.jsx")
    assert "function HighlightPath" in scene, "the highlight mutates the shared buffer"
    assert scene.count("<Bloom") == 1, "more than one post-processing effect"
    assert "<Select" in scene and "<Selection>" in scene


def test_a_usable_2d_fallback_exists_for_all_three_reasons():
    scene = src("Chamber.jsx")
    fallback = src("Adjacency.jsx")
    assert "prefers-reduced-motion" in scene
    assert "webgl2" in scene, "no GPU capability check"
    assert "force2D" in scene, "the flat view cannot be chosen deliberately"
    # Genuinely usable, not a stub: same selection model, sortable, and it says
    # what it is better at than the 3D view.
    assert "onSelect" in fallback and "setSort" in fallback
    assert len(fallback.split()) > 250, "the fallback is too thin to be usable"


def test_reduced_motion_disables_camera_motion():
    scene = src("Chamber.jsx")
    assert "autoRotate={false}" in scene
    assert "enableDamping={!reduced}" in scene


def test_geometries_created_outside_the_tree_are_disposed():
    scene = src("Chamber.jsx")
    assert "g.dispose()" in scene, "geometries leak across mount/unmount cycles"


def test_the_graph_export_matches_the_measured_ring_metrics():
    if not GRAPH.exists():
        pytest.skip("graph not generated; run `make chamber-data`")
    with open(GRAPH, encoding="utf-8") as fh:
        g = json.load(fh)
    s = g["summary"]
    assert s["rings"] + s["decoys"] == s["clusters"]
    # The chamber shows the DETECTOR's verdict, never ground truth recoloured to
    # look correct - so its errors must be present and visible.
    assert s["false_rings"] >= 1, "no false ring in view; errors are being hidden"
    assert s["missed"] >= 1, "no missed ring in view; errors are being hidden"
    assert all(n["kind"] in (0, 1, 2, 3) for n in g["nodes"])
    assert all("t" in n for n in g["nodes"]), "no time field; the scrubber cannot work"
    assert g["window_days"] > 100


def test_the_chamber_states_its_own_monetary_value():
    """The view is a communication surface, not where the money is. A demo that
    implies otherwise puts the ablation on one slide and contradicts it on the
    next."""
    scene = src("Chamber.jsx")
    assert "8,176" in scene and "94,04,449" in scene
