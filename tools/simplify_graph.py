#!/usr/bin/env python3
"""
simplify_graph.py — AquiFuturo tree graph simplification
branch_graph.json → simplified_graph.json

Method: Ramer-Douglas-Peucker in 3D along each branch path.
  - Branch points (degree ≥ 3), terminals, and trunk_base are always kept.
  - Runs of degree-2 nodes between branch points are the candidates for removal.
  - RDP in 3D removes collinear intermediate nodes below --tolerance distance.
  - Class-based floor: any node of class ≥ --keep-class is always kept.

Usage:
    python3 tools/simplify_graph.py \\
        --graph data/branch_graph.json \\
        --out physical-modelling/branch_graph_simplified.json \\
        --tolerance 0.02

    # Keep all lateral+ nodes regardless of collinearity:
    python3 tools/simplify_graph.py \\
        --graph data/branch_graph.json \\
        --out physical-modelling/branch_graph_simplified_coarse.json \\
        --tolerance 0.05 --keep-class lateral

Deps: pip install numpy
"""

import argparse
import json
import logging
from collections import defaultdict
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SUPPORTED_SCHEMA_VERSION = "1.1"

# Class rank for floor enforcement (higher = more important)
CLASS_RANK: dict[str, int] = {
    "terminal":   0,
    "fine":       1,
    "lateral":    2,
    "primary":    3,
    "trunk_base": 4,
}


# ---------------------------------------------------------------- graph loading

def load_graph(path: Path) -> dict:
    data = json.loads(path.read_text())
    if data.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported schema_version '{data.get('schema_version')}'. "
            f"Expected '{SUPPORTED_SCHEMA_VERSION}'."
        )
    return data


# ---------------------------------------------------------------- adjacency

def build_adjacency(nodes: list[dict], edges: list[dict]) -> dict[int, list[int]]:
    """Build neighbour list from edge list."""
    adj: dict[int, list[int]] = defaultdict(list)
    for e in edges:
        adj[e["source"]].append(e["target"])
        adj[e["target"]].append(e["source"])
    return dict(adj)


# ---------------------------------------------------------------- branch extraction

def extract_branches(
    nodes: list[dict],
    adj: dict[int, list[int]],
    always_keep: set[int],
) -> list[list[int]]:
    """Decompose the tree into linear branch segments between junction nodes.

    A junction node is: degree != 2 OR in always_keep.
    Each returned branch is a list of node IDs: [junction_A, ..., junction_B].
    """
    node_ids = {n["id"] for n in nodes}
    junction = {
        nid for nid in node_ids
        if len(adj.get(nid, [])) != 2 or nid in always_keep
    }

    visited_edges: set[frozenset] = set()
    branches: list[list[int]] = []

    for start in junction:
        for neighbor in adj.get(start, []):
            edge_key = frozenset([start, neighbor])
            if edge_key in visited_edges:
                continue
            visited_edges.add(edge_key)

            # Walk along the chain until the next junction
            path = [start, neighbor]
            prev, cur = start, neighbor

            while cur not in junction:
                nexts = [n for n in adj.get(cur, []) if n != prev]
                if not nexts:
                    break
                nxt = nexts[0]
                edge_key2 = frozenset([cur, nxt])
                visited_edges.add(edge_key2)
                path.append(nxt)
                prev, cur = cur, nxt

            branches.append(path)

    return branches


# ---------------------------------------------------------------- RDP in 3D

def rdp_3d(
    points: np.ndarray,
    node_ids: list[int],
    tolerance: float,
) -> list[int]:
    """Ramer-Douglas-Peucker simplification in 3D.

    Args:
        points    (N, 3) array of XYZ positions
        node_ids  list of N node IDs corresponding to points
        tolerance distance threshold in the same units as points

    Returns:
        list of node IDs to keep (always includes first and last)
    """
    if len(points) <= 2:
        return list(node_ids)

    def _rdp(start: int, end: int) -> set[int]:
        """Recursive RDP — returns indices of points to keep."""
        if end - start <= 1:
            return set()

        # Vector from start to end
        seg = points[end] - points[start]
        seg_len = np.linalg.norm(seg)

        if seg_len < 1e-10:
            # Degenerate segment — keep all
            return set(range(start + 1, end))

        seg_unit = seg / seg_len

        # Perpendicular distance of each intermediate point to the segment
        diffs = points[start + 1:end] - points[start]      # (n, 3)
        proj = (diffs @ seg_unit)[:, None] * seg_unit       # (n, 3) projections
        perp = diffs - proj                                  # (n, 3) perpendicular
        dists = np.linalg.norm(perp, axis=1)                # (n,)

        max_idx_local = int(np.argmax(dists))
        max_dist = dists[max_idx_local]
        max_idx = start + 1 + max_idx_local

        if max_dist > tolerance:
            left = _rdp(start, max_idx)
            right = _rdp(max_idx, end)
            return {max_idx} | left | right
        else:
            return set()

    keep_local = {0, len(points) - 1} | _rdp(0, len(points) - 1)
    sorted_keep = sorted(keep_local)
    return [node_ids[i] for i in sorted_keep]


# ---------------------------------------------------------------- graph rebuild

def rebuild_graph(
    original: dict,
    keep_ids: set[int],
    nodes_by_id: dict[int, dict],
) -> dict:
    """Reconstruct a valid graph dict from the set of kept node IDs.

    Edges are rebuilt along the original tree paths — if intermediate nodes
    were removed, a direct edge is added between the surviving endpoints.
    """
    # Remap IDs to contiguous 0-based indices
    sorted_keep = sorted(keep_ids)
    id_map: dict[int, int] = {old: new for new, old in enumerate(sorted_keep)}

    new_nodes = []
    for old_id in sorted_keep:
        n = dict(nodes_by_id[old_id])
        n["id"] = id_map[old_id]
        new_nodes.append(n)

    # Rebuild edges: walk original edge list, chain-compress removed nodes
    original_adj: dict[int, list[int]] = defaultdict(list)
    for e in original["edges"]:
        original_adj[e["source"]].append(e["target"])
        original_adj[e["target"]].append(e["source"])

    seen_edges: set[frozenset] = set()
    new_edges = []

    def _find_kept_neighbor(from_id: int, prev_id: int) -> int | None:
        """Follow chain until a kept node is found."""
        cur, prev = from_id, prev_id
        while cur not in keep_ids:
            nexts = [n for n in original_adj.get(cur, []) if n != prev]
            if not nexts:
                return None
            prev, cur = cur, nexts[0]
        return cur

    for nid in sorted_keep:
        for neighbor in original_adj.get(nid, []):
            target = neighbor if neighbor in keep_ids else _find_kept_neighbor(neighbor, nid)
            if target is None or target == nid:
                continue
            key = frozenset([nid, target])
            if key in seen_edges:
                continue
            seen_edges.add(key)

            # Compute direct Euclidean length between kept nodes
            p1 = np.array(nodes_by_id[nid]["position"])
            p2 = np.array(nodes_by_id[target]["position"])
            length = float(np.linalg.norm(p2 - p1))

            new_edges.append({
                "source": id_map[nid],
                "target": id_map[target],
                "length": round(length, 6),
            })

    return {
        **{k: v for k, v in original.items() if k not in ("nodes", "edges", "tours")},
        "simplified": True,
        "original_node_count": len(original["nodes"]),
        "nodes": new_nodes,
        "edges": new_edges,
        **({"tours": _remap_tours(original.get("tours", []), id_map, keep_ids)}
           if original.get("tours") else {}),
    }


def _remap_tours(
    tours: list[dict],
    id_map: dict[int, int],
    keep_ids: set[int],
) -> list[dict]:
    """Remap tour node sequences to new IDs, dropping removed nodes."""
    result = []
    for t in tours:
        new_seq = [id_map[nid] for nid in t["node_sequence"] if nid in keep_ids]
        result.append({**t, "node_sequence": new_seq})
    return result


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Simplify branch_graph.json using RDP in 3D",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--graph", required=True, type=Path, help="branch_graph.json")
    ap.add_argument("--out", required=True, type=Path,
                    help="output simplified JSON path")
    ap.add_argument("--tolerance", type=float, default=0.02,
                    help="RDP perpendicular distance threshold in meters. "
                         "Lower = keep more nodes. Try 0.01–0.05.")
    ap.add_argument("--keep-class",
                    choices=list(CLASS_RANK.keys()),
                    default="lateral",
                    help="Always keep nodes of this class rank or higher "
                         "(trunk_base > primary > lateral > fine > terminal)")
    args = ap.parse_args()

    # ---- load
    graph = load_graph(args.graph)
    nodes = graph["nodes"]
    edges = graph["edges"]
    log.info(f"Loaded: {len(nodes)} nodes, {len(edges)} edges")

    nodes_by_id: dict[int, dict] = {n["id"]: n for n in nodes}

    # ---- always-keep set: structural nodes + class floor
    keep_floor_rank = CLASS_RANK.get(args.keep_class, 2)
    always_keep: set[int] = {
        n["id"] for n in nodes
        if CLASS_RANK.get(n["class"], 0) >= keep_floor_rank
    }
    log.info(f"Always-keep: {len(always_keep)} nodes "
             f"(class ≥ {args.keep_class}, rank ≥ {keep_floor_rank})")

    # ---- adjacency
    adj = build_adjacency(nodes, edges)

    # ---- extract branch paths
    branches = extract_branches(nodes, adj, always_keep)
    log.info(f"Extracted {len(branches)} branch segments")

    # ---- RDP per branch
    keep_ids: set[int] = set(always_keep)

    rdp_stats: dict[str, int] = {"branches": 0, "removed": 0}
    for branch in branches:
        if len(branch) <= 2:
            keep_ids.update(branch)
            continue

        points = np.array([nodes_by_id[nid]["position"] for nid in branch])
        kept = rdp_3d(points, branch, args.tolerance)
        keep_ids.update(kept)

        removed = len(branch) - len(kept)
        rdp_stats["branches"] += 1
        rdp_stats["removed"] += removed

    log.info(
        f"RDP: processed {rdp_stats['branches']} segments, "
        f"removed {rdp_stats['removed']} intermediate nodes"
    )
    log.info(f"Result: {len(keep_ids)} / {len(nodes)} nodes kept "
             f"({100*len(keep_ids)/len(nodes):.1f}%)")

    # ---- rebuild
    simplified = rebuild_graph(graph, keep_ids, nodes_by_id)
    log.info(f"Rebuilt: {len(simplified['nodes'])} nodes, "
             f"{len(simplified['edges'])} edges")

    # ---- write
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(simplified, indent=2))
    log.info(f"Wrote {args.out}")

    # Summary
    reduction = 1.0 - len(simplified["nodes"]) / len(nodes)
    log.info(f"Node reduction: {len(nodes)} → {len(simplified['nodes'])} "
             f"({reduction*100:.1f}% fewer nodes)")


if __name__ == "__main__":
    main()
