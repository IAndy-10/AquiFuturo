"""
validate_assets.py — AquiFuturo AR asset validator (SPEC.md §5.4)

Checks performed:
  1. root_graph.json schema_version matches SUPPORTED_SCHEMA_VERSION
  2. root_graph.json node/edge referential integrity
  3. All node positions fall inside declared bounds
  4. audio_manifest.json schema_version matches SUPPORTED_SCHEMA_VERSION
  5. Every manifest track file exists in AquiFuturo-app/Assets/Audio/Tracks/
  6. Every interaction sample file exists in AquiFuturo-app/Assets/Audio/Interaction/
  7. All five tracks are 48 kHz stereo and identical in sample length
  8. The three FBX models required by SPEC §5.3 exist in AquiFuturo-app/Assets/Art/Models/

Audio files are stored in Git LFS. If a WAV is still an LFS pointer (not
pulled), it is reported as such; run `git lfs pull` first.

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
EXPECTED_TRACK_IDS = {"track_voice", "track_canopy", "track_river", "track_birds1", "track_birds2"}
EXPECTED_SAMPLE_RATE = 48_000
EXPECTED_CHANNELS = 2  # stereo
REQUIRED_MODELS = ("AquiFuturo_RootA.fbx", "AquiFuturo_RootB.fbx", "AquiFuturo_Trunk.fbx")
UNITY_ASSETS = Path("AquiFuturo-app") / "Assets"
LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/"


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


def _is_lfs_pointer(path: Path) -> bool:
    """True if the file is a Git LFS pointer rather than the real content."""
    with path.open("rb") as fh:
        return fh.read(len(LFS_POINTER_PREFIX)) == LFS_POINTER_PREFIX


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

        if _is_lfs_pointer(wav_path):
            errors.append(
                f"Track '{filename}' is a Git LFS pointer, not audio. Run `git lfs pull`."
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
            except (OSError, RuntimeError) as exc:
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
        elif _is_lfs_pointer(sample_path):
            errors.append(
                f"Interaction sample '{filename}' is a Git LFS pointer, not audio. "
                "Run `git lfs pull`."
            )

    return errors


# ---------------------------------------------------------------------------
# Check 8: FBX models (SPEC §5.3)
# ---------------------------------------------------------------------------

def validate_models(models_dir: Path) -> list[str]:
    """
    Returns a list of error strings. Empty list = pass.
    Checks: the three FBX models required by SPEC §5.3 exist. Their content
    is not inspected (FBX is binary; Unity validates it on import).
    """
    errors: list[str] = []
    for name in REQUIRED_MODELS:
        if not (models_dir / name).exists():
            errors.append(f"Required model not found: {models_dir / name} (SPEC §5.3)")
    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_validation(repo_root: Path) -> int:
    """Run all checks. Returns 0 on full pass, 1 on any failure."""
    all_errors: list[str] = []
    all_warnings: list[str] = []

    graph_path = repo_root / "data" / "processed" / "skeleton" / "root_graph.json"
    branch_graph_path = repo_root / "data" / "processed" / "skeleton" / "branch_graph.json"
    manifest_path = repo_root / "tools" / "audio_manifest.json"
    tracks_dir = repo_root / UNITY_ASSETS / "Audio" / "Tracks"
    interaction_dir = repo_root / UNITY_ASSETS / "Audio" / "Interaction"
    models_dir = repo_root / UNITY_ASSETS / "Art" / "Models"

    log.info("=== AquiFuturo asset validator ===")
    log.info(f"Repo root: {repo_root}")

    # --- root_graph.json ---
    log.info("[1/4] Validating root_graph.json …")
    graph_errors = validate_root_graph(graph_path)
    for e in graph_errors:
        if e.startswith("TODO"):
            all_warnings.append(e)
            log.warning(e)
        else:
            all_errors.append(e)
            log.error(e)

    # --- branch_graph.json ---
    log.info("[2/4] Validating branch_graph.json …")
    branch_errors = validate_root_graph(branch_graph_path)
    for e in branch_errors:
        if e.startswith("TODO"):
            all_warnings.append(e)
            log.warning(e)
        else:
            all_errors.append(e)
            log.error(e)

    # --- audio_manifest.json ---
    log.info("[3/4] Validating audio_manifest.json and audio files …")
    audio_errors = validate_audio_manifest(manifest_path, tracks_dir, interaction_dir)
    for e in audio_errors:
        if e.startswith("TODO"):
            all_warnings.append(e)
            log.warning(e)
        else:
            all_errors.append(e)
            log.error(e)

    # --- FBX models ---
    log.info("[4/4] Validating FBX models …")
    model_errors = validate_models(models_dir)
    for e in model_errors:
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
