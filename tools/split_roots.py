#!/usr/bin/env python3
"""
split_roots.py — divide skel_roots_skeleton.json into 4 spatial zones.

Zones (based on depth Y and radial spread from trunk axis):

  G1  shallow horizontal branches  Y > -2.0  AND  spread > 1.2 m
  G2  upper trunk                  Y > -2.8  AND  spread ≤ 1.2 m
  G3  lower trunk                  Y ≤ -2.8  AND  spread ≤ 1.2 m
  G4  deep horizontal branches     Y ≤ -2.0  AND  spread > 1.2 m

Each zone is written as a skeleton JSON compatible with graph_builder.py.
Edges are kept only when both endpoints belong to the same zone.
Node IDs are re-indexed from 0 within each zone.

Usage:
    python tools/split_roots.py \\
        --input  assets_src/skel_roots_skeleton.json \\
        --outdir assets_src/zones/

    Then for each zone:
        python tools/graph_builder.py \\
            --input  assets_src/zones/skel_roots_zone_g1.json \\
            --out    data/root_graph_g1.json \\
            --root-at-top --tour tsp_2opt
"""

import argparse
import json
import math
import sys
from pathlib import Path


DEPTH_TRUNK_MID  = -2.786   # Y midpoint — splits upper/lower trunk
DEPTH_HORIZ_CUTOFF = -2.0   # Y cutoff — above this = shallow horizontal zone
SPREAD_THRESH    = 1.2      # radial distance from trunk axis (metres)

ZONES = {
    "g1": "shallow horizontal branches  (Y > -2.0,  spread > 1.2 m)",
    "g2": "upper trunk                  (Y > -2.8,  spread ≤ 1.2 m)",
    "g3": "lower trunk                  (Y ≤ -2.8,  spread ≤ 1.2 m)",
    "g4": "deep horizontal branches     (Y ≤ -2.0,  spread > 1.2 m)",
}


def classify(x: float, y: float, z: float) -> str:
    spread = math.sqrt(x ** 2 + z ** 2)
    if y > DEPTH_HORIZ_CUTOFF and spread > SPREAD_THRESH:
        return "g1"
    if y > DEPTH_TRUNK_MID and spread <= SPREAD_THRESH:
        return "g2"
    if y <= DEPTH_TRUNK_MID and spread <= SPREAD_THRESH:
        return "g3"
    # y <= DEPTH_HORIZ_CUTOFF and spread > SPREAD_THRESH
    return "g4"


def build_zone_skeleton(
    all_nodes: list[dict],
    all_edges: list[dict],
    zone: str,
    source_meta: dict,
) -> dict:
    """Return a skeleton JSON for a single zone, with re-indexed node IDs."""
    # Select nodes belonging to this zone
    old_to_new: dict[int, int] = {}
    new_nodes: list[dict] = []
    for node in all_nodes:
        x, y, z = node["position"]
        if classify(x, y, z) == zone:
            new_id = len(new_nodes)
            old_to_new[node["id"]] = new_id
            new_nodes.append({
                "id":       new_id,
                "position": node["position"],
                "radius":   node["radius"],
            })

    # Keep edges where both endpoints are in this zone
    new_edges: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for edge in all_edges:
        src, tgt = edge["source"], edge["target"]
        if src in old_to_new and tgt in old_to_new:
            a, b = old_to_new[src], old_to_new[tgt]
            key = (min(a, b), max(a, b))
            if key not in seen:
                seen.add(key)
                new_edges.append({"source": a, "target": b})

    return {
        "source":           "blender_native",
        "object":           f"roots_skeleton_{zone}",
        "source_mesh":      source_meta.get("source_mesh", "skel_roots_main"),
        "coordinate_space": "unity_y_up",
        "nodes":            new_nodes,
        "edges":            new_edges,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input",  required=True,
                    help="Path to skel_roots_skeleton.json")
    ap.add_argument("--outdir", required=True,
                    help="Directory to write the four zone skeleton JSONs")
    args = ap.parse_args()

    in_path  = Path(args.input)
    out_dir  = Path(args.outdir)

    if not in_path.exists():
        print(f"ERROR: input file not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(in_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: JSON parse error: {exc}", file=sys.stderr)
        sys.exit(1)

    if data.get("coordinate_space") != "unity_y_up":
        print("ERROR: coordinate_space must be 'unity_y_up'", file=sys.stderr)
        sys.exit(1)

    all_nodes = data["nodes"]
    all_edges = data.get("edges", [])
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Input: {in_path}  ({len(all_nodes)} nodes, {len(all_edges)} edges)")
    print(f"Thresholds: depth_mid={DEPTH_TRUNK_MID}  horiz_cutoff={DEPTH_HORIZ_CUTOFF}"
          f"  spread={SPREAD_THRESH}m")
    print()

    for zone, description in ZONES.items():
        skeleton = build_zone_skeleton(all_nodes, all_edges, zone, data)
        n_nodes = len(skeleton["nodes"])
        n_edges = len(skeleton["edges"])

        out_path = out_dir / f"skel_roots_{zone}.json"
        out_path.write_text(json.dumps(skeleton, indent=2), encoding="utf-8")

        print(f"[{zone.upper()}] {description}")
        print(f"       {n_nodes:3d} nodes  {n_edges:3d} edges  → {out_path}")

    print()
    print("Next steps — run for each zone:")
    print("  python tools/graph_builder.py \\")
    print("      --input  assets_src/zones/skel_roots_<zone>.json \\")
    print("      --out    data/root_graph_<zone>.json \\")
    print("      --root-at-top --tour tsp_2opt")


if __name__ == "__main__":
    main()
