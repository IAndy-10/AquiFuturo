"""
validate_assets.py — AquiFuturo AR asset validator (SPEC.md §5.4)

Checks performed:
  1. root_graph.json schema_version matches SUPPORTED_SCHEMA_VERSION
  2. root_graph.json node/edge referential integrity
  3. All node positions fall inside declared bounds
  4. audio_manifest.json schema_version matches SUPPORTED_SCHEMA_VERSION
  5. Every manifest track file exists in unity/Assets/Audio/Tracks/
  6. Every interaction sample file exists in unity/Assets/Audio/Interaction/
  7. All four tracks are 48 kHz stereo and identical in sample length
  8. Every node.class present in the graph has >= 1 matching interaction sample
  9. tree_full.glb exists and contains exactly Trunk, Branches, Roots top-level nodes

Run:
    python tools/validate_assets.py
    python tools/validate_assets.py --root /path/to/repo

Exit codes: 0 = pass, 1 = one or more failures, 2 = usage/dependency error.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

SUPPORTED_SCHEMA_VERSION = "1.1"

REQUIRED_NODE_CLASSES = {"trunk_base", "primary", "lateral", "fine", "terminal"}
EXPECTED_TRACK_IDS = {"root_rave", "soil", "canopy", "drone"}
EXPECTED_SAMPLE_RATE = 48_000
EXPECTED_CHANNELS = 2  # stereo
GLB_REQUIRED_CHILDREN = {"Trunk", "Branches", "Roots"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict[str, Any]:
    """Load and parse a JSON file, raising ValueError on failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError(f"Required file not found: {path}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON parse error in {path}: {exc}") from exc


def _check_schema_version(data: dict[str, Any], path: Path) -> None:
    version = data.get("schema_version")
    if version != SUPPORTED_SCHEMA_VERSION:
        raise ValueError(
            f"schema_version mismatch in {path.name}: "
            f"got '{version}', expected '{SUPPORTED_SCHEMA_VERSION}' "
            f"(SPEC §5.1 — unknown versions must be rejected, not silently accepted)"
        )


# ---------------------------------------------------------------------------
# Check 1+2+3: root_graph.json
# ---------------------------------------------------------------------------

def validate_root_graph(graph_path: Path) -> list[str]:
    """
    Returns a list of error strings. Empty list = pass.
    Checks: schema_version, node/edge referential integrity, positions in bounds.
    """
    errors: list[str] = []

    if not graph_path.exists():
        # TODO: once data/root_graph.json is produced by the pipeline this
        # should be a hard failure. For now, report clearly and skip the rest
        # of the graph checks rather than silently passing.
        errors.append(
            f"TODO (no asset yet): {graph_path} does not exist. "
            "Run tools/skeletonize.py to produce it. "
            "This check MUST pass before any Unity import."
        )
        return errors

    try:
        graph = _load_json(graph_path)
    except (FileNotFoundError, ValueError) as exc:
        errors.append(str(exc))
        return errors

    # schema_version
    try:
        _check_schema_version(graph, graph_path)
    except ValueError as exc:
        errors.append(str(exc))

    nodes: list[dict[str, Any]] = graph.get("nodes", [])
    edges: list[dict[str, Any]] = graph.get("edges", [])
    node_ids = {n["id"] for n in nodes if "id" in n}

    # node integrity
    for i, node in enumerate(nodes):
        if "id" not in node:
            errors.append(f"root_graph.json node[{i}] missing 'id' field")
        if "position" not in node:
            errors.append(f"root_graph.json node id={node.get('id', i)} missing 'position'")
        if "class" not in node:
            errors.append(f"root_graph.json node id={node.get('id', i)} missing 'class'")
        elif node["class"] not in REQUIRED_NODE_CLASSES:
            errors.append(
                f"root_graph.json node id={node.get('id', i)} has unknown class "
                f"'{node['class']}'. Expected one of {sorted(REQUIRED_NODE_CLASSES)}."
            )

    # edge integrity — both endpoints must exist
    for i, edge in enumerate(edges):
        src = edge.get("source")
        tgt = edge.get("target")
        if src not in node_ids:
            errors.append(
                f"root_graph.json edge[{i}] source={src} references non-existent node"
            )
        if tgt not in node_ids:
            errors.append(
                f"root_graph.json edge[{i}] target={tgt} references non-existent node"
            )

    # positions inside bounds
    bounds = graph.get("bounds")
    if bounds:
        bmin = bounds.get("min", [None, None, None])
        bmax = bounds.get("max", [None, None, None])
        for node in nodes:
            pos = node.get("position")
            if pos is None or len(pos) != 3:
                continue
            for axis, (p, lo, hi) in enumerate(zip(pos, bmin, bmax)):
                if lo is None or hi is None:
                    continue
                if not (lo <= p <= hi):
                    errors.append(
                        f"root_graph.json node id={node.get('id','?')} position axis {axis} "
                        f"value {p} is outside declared bounds [{lo}, {hi}]"
                    )
    else:
        errors.append("root_graph.json missing 'bounds' field")

    return errors


# ---------------------------------------------------------------------------
# Check 4+5+6+7+8: audio_manifest.json and audio files
# ---------------------------------------------------------------------------

def validate_audio_manifest(
    manifest_path: Path,
    tracks_dir: Path,
    interaction_dir: Path,
) -> list[str]:
    """
    Returns a list of error strings. Empty list = pass.
    Checks: schema_version, file existence, 48 kHz / stereo / identical sample length,
    node class coverage.
    """
    errors: list[str] = []

    if not manifest_path.exists():
        errors.append(
            f"TODO (no asset yet): {manifest_path} does not exist. "
            "Produce it alongside the audio files (SPEC §5.2). "
            "This check MUST pass before any Unity import."
        )
        return errors

    try:
        manifest = _load_json(manifest_path)
    except (FileNotFoundError, ValueError) as exc:
        errors.append(str(exc))
        return errors

    try:
        _check_schema_version(manifest, manifest_path)
    except ValueError as exc:
        errors.append(str(exc))

    tracks: list[dict[str, Any]] = manifest.get("tracks", [])
    interaction_entries: list[dict[str, Any]] = manifest.get("interaction", [])

    # Check all four expected track ids are present
    found_ids = {t.get("id") for t in tracks}
    for expected_id in EXPECTED_TRACK_IDS:
        if expected_id not in found_ids:
            errors.append(f"audio_manifest.json missing expected track id '{expected_id}'")

    # File existence and audio format checks
    try:
        import soundfile as sf  # type: ignore[import]
        have_soundfile = True
    except ImportError:
        log.warning(
            "soundfile not installed — skipping sample-rate, channel, and length checks. "
            "Install with: pip install soundfile"
        )
        have_soundfile = False

    track_sample_lengths: dict[str, int] = {}

    for track in tracks:
        track_id = track.get("id", "<unknown>")
        filename = track.get("file")
        if not filename:
            errors.append(f"audio_manifest.json track '{track_id}' missing 'file' field")
            continue

        wav_path = tracks_dir / filename
        if not wav_path.exists():
            errors.append(
                f"Track file not found: {wav_path}  "
                f"(manifest track id='{track_id}'). "
                "TODO: produce the audio files and commit via Git LFS."
            )
            continue

        if have_soundfile:
            try:
                info = sf.info(str(wav_path))
                if info.samplerate != EXPECTED_SAMPLE_RATE:
                    errors.append(
                        f"Track '{filename}' sample rate is {info.samplerate} Hz, "
                        f"expected {EXPECTED_SAMPLE_RATE} Hz (SPEC §6.5)"
                    )
                if info.channels != EXPECTED_CHANNELS:
                    errors.append(
                        f"Track '{filename}' has {info.channels} channels, "
                        f"expected {EXPECTED_CHANNELS} (stereo) (SPEC §6.5)"
                    )
                track_sample_lengths[filename] = info.frames
            except Exception as exc:
                errors.append(f"Could not read audio info from '{filename}': {exc}")

    # All tracks must have identical sample length
    if have_soundfile and len(track_sample_lengths) > 1:
        lengths = list(track_sample_lengths.values())
        if len(set(lengths)) != 1:
            detail = ", ".join(
                f"{fn}={frames} samples" for fn, frames in track_sample_lengths.items()
            )
            errors.append(
                f"Track sample lengths are not identical — phase lock impossible (SPEC §5.2, §9.2). "
                f"Lengths: {detail}"
            )

    # Interaction sample existence
    for entry in interaction_entries:
        filename = entry.get("file")
        if not filename:
            errors.append("audio_manifest.json interaction entry missing 'file' field")
            continue
        sample_path = interaction_dir / filename
        if not sample_path.exists():
            errors.append(
                f"Interaction sample not found: {sample_path}. "
                "TODO: produce and commit the one-shot samples (SPEC §6.5)."
            )

    # Every node.class in the graph must have >= 1 matching interaction sample
    # We check by node_class field in interaction entries
    covered_classes = {e.get("node_class") for e in interaction_entries if e.get("node_class")}
    # We can only check graph node classes if the graph exists
    graph_path = manifest_path.parent.parent / "data" / "root_graph.json"
    if graph_path.exists():
        try:
            graph = _load_json(graph_path)
            graph_classes = {n.get("class") for n in graph.get("nodes", []) if n.get("class")}
            for cls in graph_classes:
                if cls not in covered_classes:
                    errors.append(
                        f"Node class '{cls}' appears in root_graph.json but has no "
                        "matching interaction sample in audio_manifest.json (SPEC §5.4). "
                        "TODO: add one-shot samples for this class."
                    )
        except (ValueError, KeyError):
            pass  # graph errors already reported in validate_root_graph

    return errors


# ---------------------------------------------------------------------------
# Check 9: tree_full.glb
# ---------------------------------------------------------------------------

def validate_glb(glb_path: Path) -> list[str]:
    """
    Returns a list of error strings. Empty list = pass.
    Checks: file existence, top-level children named exactly Trunk/Branches/Roots.
    """
    errors: list[str] = []

    if not glb_path.exists():
        errors.append(
            f"TODO (no asset yet): {glb_path} does not exist. "
            "Run the Blender session (docs/blender_session.md) to produce it. "
            "This check MUST pass before any Unity import."
        )
        return errors

    try:
        import pygltflib  # type: ignore[import]
        have_pygltflib = True
    except ImportError:
        log.warning(
            "pygltflib not installed — skipping GLB child-name check. "
            "Install with: pip install pygltflib"
        )
        have_pygltflib = False

    if not have_pygltflib:
        log.info(f"GLB file exists at {glb_path} (child structure not verified — install pygltflib)")
        return errors

    try:
        gltf = pygltflib.GLTF2().load(str(glb_path))
    except Exception as exc:
        errors.append(f"Failed to parse {glb_path}: {exc}")
        return errors

    # Find scene root nodes
    scene_index = gltf.scene if gltf.scene is not None else 0
    if not gltf.scenes or scene_index >= len(gltf.scenes):
        errors.append(f"{glb_path.name}: no scenes found in GLB")
        return errors

    scene = gltf.scenes[scene_index]
    top_level_names: set[str] = set()
    for node_index in (scene.nodes or []):
        if node_index < len(gltf.nodes):
            name = gltf.nodes[node_index].name
            if name:
                top_level_names.add(name)

    missing = GLB_REQUIRED_CHILDREN - top_level_names
    extra = top_level_names - GLB_REQUIRED_CHILDREN

    if missing:
        errors.append(
            f"{glb_path.name}: missing required top-level children: {sorted(missing)} "
            f"(SPEC §5.3). Found: {sorted(top_level_names)}"
        )
    if extra:
        errors.append(
            f"{glb_path.name}: unexpected top-level children: {sorted(extra)} "
            f"(SPEC §5.3 requires exactly Trunk, Branches, Roots)"
        )

    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_validation(repo_root: Path) -> int:
    """Run all checks. Returns 0 on full pass, 1 on any failure."""
    all_errors: list[str] = []
    all_warnings: list[str] = []

    graph_path = repo_root / "data" / "root_graph.json"
    manifest_path = repo_root / "data" / "audio_manifest.json"
    tracks_dir = repo_root / "unity" / "Assets" / "Audio" / "Tracks"
    interaction_dir = repo_root / "unity" / "Assets" / "Audio" / "Interaction"
    glb_path = repo_root / "unity" / "Assets" / "Art" / "Models" / "tree_full.glb"

    log.info("=== AquiFuturo asset validator ===")
    log.info(f"Repo root: {repo_root}")

    # --- root_graph.json ---
    log.info("[1/3] Validating root_graph.json …")
    graph_errors = validate_root_graph(graph_path)
    for e in graph_errors:
        if e.startswith("TODO"):
            all_warnings.append(e)
            log.warning(e)
        else:
            all_errors.append(e)
            log.error(e)

    # --- audio_manifest.json ---
    log.info("[2/3] Validating audio_manifest.json and audio files …")
    audio_errors = validate_audio_manifest(manifest_path, tracks_dir, interaction_dir)
    for e in audio_errors:
        if e.startswith("TODO"):
            all_warnings.append(e)
            log.warning(e)
        else:
            all_errors.append(e)
            log.error(e)

    # --- tree_full.glb ---
    log.info("[3/3] Validating tree_full.glb …")
    glb_errors = validate_glb(glb_path)
    for e in glb_errors:
        if e.startswith("TODO"):
            all_warnings.append(e)
            log.warning(e)
        else:
            all_errors.append(e)
            log.error(e)

    # --- Summary ---
    log.info("=== Summary ===")
    if all_warnings:
        log.warning(f"{len(all_warnings)} TODO(s) — assets not yet produced (expected at M0):")
        for w in all_warnings:
            log.warning(f"  • {w[:120]}")
    if all_errors:
        log.error(f"{len(all_errors)} FAILURE(s):")
        for e in all_errors:
            log.error(f"  ✗ {e}")
        log.error("RESULT: FAIL")
        return 1

    if all_warnings and not all_errors:
        log.info("RESULT: PASS (with TODOs — re-run once assets exist)")
    else:
        log.info("RESULT: PASS")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate AquiFuturo AR assets against SPEC.md §5.4."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Path to repo root (default: two directories above this script)",
    )
    args = parser.parse_args()

    repo_root = args.root.resolve()
    if not repo_root.is_dir():
        log.error(f"Repo root does not exist or is not a directory: {repo_root}")
        sys.exit(2)

    sys.exit(run_validation(repo_root))


if __name__ == "__main__":
    main()
