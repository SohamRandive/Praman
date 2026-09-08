"""The landing page's WebGL contract, enforced as a source check.

`test_chamber.py` guards the console's chamber this way already, and the
reasoning carries over unchanged: every item here fails *silently*. A refactor
that drops `invalidate()` under `frameloop="demand"` produces a scene that
renders one frame and then freezes. One that drops the WebGL2 gate shows a
blank rectangle to anyone without a GPU. One that drops `g.dispose()` leaks a
geometry per mount, which costs nothing visible until the browser hits its
live-context ceiling and kills an unrelated canvas.

The landing scenes differ from the chamber in one deliberate way: they are
DECORATIVE. Both set `raycast={null}` and neither carries a pointer handler,
because interaction with the graph belongs in the console, where a cluster can
be selected and its cohesion read against the threshold. So the picking rules
in the reference - `stopPropagation`, throttled raycasting, a separate
highlight object - do not apply here, and this file asserts the absence of
picking rather than its correctness. If a pointer handler is ever added, the
test that guarantees raycasting stays off the edges will start failing, which
is the point.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / "web" / "src" / "landing"


def src(name: str) -> str:
    path = LANDING / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    return path.read_text(encoding="utf-8")


def test_the_ring_reuses_the_chamber_worker_rather_than_laying_out_on_the_main_thread():
    """Force layout is CPU-bound and iterative; on the main thread it destroys
    frame rate. The landing page does not get its own copy of that problem - it
    imports the hook the chamber already proved, so there is one layout
    implementation and one worker lifecycle to get right."""
    scene = src("RingScene.jsx")
    assert "useGraphLayout" in scene, "the ring lays out without the worker hook"
    assert "../chamber/useGraphLayout" in scene, "a second layout implementation appeared"


def test_invalidate_is_called_on_every_position_update():
    """Under frameloop="demand" nothing repaints without it, so a buffer that is
    updated but never invalidated is data written to a frame nobody draws."""
    for name in ("RingScene.jsx", "Constellation.jsx"):
        assert "invalidate" in src(name), f"{name} updates buffers that never repaint"


def test_nodes_are_instanced_and_edges_are_a_single_linesegments():
    """Above roughly 500 individual meshes per-object rendering stops being
    viable, and this graph carries 869 nodes."""
    scene = src("RingScene.jsx")
    assert scene.count("<instancedMesh") >= 1, "nodes are not instanced"
    assert "<lineSegments" in scene, "edges are not a single LineSegments"
    assert "SphereGeometry(2.6, 12, 12)" in scene or "12, 12" in scene, (
        "sphere segment count drifted; 12x12 is indistinguishable from 32x32 at "
        "graph scale and costs a fraction"
    )


def test_geometries_built_outside_the_tree_are_disposed_by_hand():
    """R3F disposes what it created declaratively. It does not own a geometry
    built in a `useMemo`, and that one leaks per mount until the browser starts
    killing WebGL contexts belonging to other canvases."""
    scene = src("RingScene.jsx")
    assert "new THREE." in scene and "Geometry(" in scene, "test is checking the wrong file"
    assert "dispose()" in scene, "geometries created outside the tree are never released"


def test_the_decorative_scenes_take_themselves_off_the_raycaster():
    """These scenes are not interactive, so every pointer move that tests them is
    wasted work on a page that must scroll at 60fps. Raycasting is disabled
    rather than merely unused."""
    for name in ("RingScene.jsx", "Constellation.jsx"):
        body = src(name)
        assert "raycast={null}" in body, f"{name} is still raycast on every pointer move"
        # If picking is ever added, the reference's rules kick in and this
        # assertion is the reminder to apply them.
        assert "onPointerMove" not in body and "onClick" not in body, (
            f"{name} added a pointer handler - it now needs stopPropagation and "
            "raycast throttling per the graph-visualization reference"
        )


def test_at_most_one_post_processing_effect():
    """Bloom on everything reads as a screensaver."""
    scene = src("RingScene.jsx")
    effects = [e for e in ("Bloom", "DepthOfField", "Noise", "Vignette", "ChromaticAberration",
                           "SSAO", "Glitch", "Scanline") if f"<{e}" in scene]
    assert len(effects) <= 1, f"more than one post-processing effect: {effects}"


def test_risk_state_is_carried_by_colour_and_never_by_colour_alone_for_kind():
    """Colour carries the detector's verdict, so node KIND has to be carried by
    geometry - otherwise the view dies in greyscale and for a colour-blind
    reader, and the two meanings collide."""
    scene = src("RingScene.jsx")
    assert scene.count("Geometry(") >= 2, "every node kind renders as the same shape"


def test_a_2d_fallback_exists_for_a_machine_with_no_webgl():
    """Non-optional. A blank rectangle where the showpiece should be is worse
    than never having built it."""
    ring = src("Ring.jsx")
    assert "useWebGL2" in ring or "webgl2" in ring, "no GPU capability check"
    assert "lp-fallback" in ring, "no fallback view when WebGL is absent"


def test_reduced_motion_is_respected_by_every_animated_surface():
    """`prefers-reduced-motion` is an accessibility setting, not a preference to
    consult when convenient. Under it the scenes hold still."""
    for name in ("RingScene.jsx", "Constellation.jsx", "Ring.jsx"):
        assert "educed" in src(name), f"{name} animates regardless of the motion setting"


def test_the_landing_page_never_prints_a_figure_it_did_not_measure():
    """The console is held to this and the landing page is louder, so it is held
    to it harder. Every figure resolves through `metrics.json`; a rupee amount
    typed into a component is a number that goes stale the next time
    `make eval` runs and says nothing when it does."""
    import re

    money = re.compile(r"₹\s?\d")
    # Comments are stripped rather than skipped by prefix: the rule is explained
    # in prose that quotes the very figures it forbids, and a continuation line
    # inside a block comment starts with none of the usual markers.
    block = re.compile(r"/\*.*?\*/", re.S)
    line_comment = re.compile(r"//[^\n]*")

    for path in sorted(LANDING.glob("*.jsx")) + sorted(LANDING.glob("*.js")):
        source = line_comment.sub("", block.sub("", path.read_text(encoding="utf-8")))
        for i, line in enumerate(source.splitlines(), 1):
            assert not money.search(line), (
                f"{path.name}:{i} hard-codes a rupee figure: {line.strip()[:70]}"
            )
