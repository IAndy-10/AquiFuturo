"""
graph_builder.py — AquiFuturo skeleton graph → root_graph.json  (SPEC §5.1)

Reads a Blender-exported skeleton JSON (assets_src/skel_*_skeleton.json),
runs graph analysis, and writes root_graph.json / branch_graph.json
conforming to schema_version "1.1".

Dependencies: stdlib + numpy only.  No trimesh, networkx, or scipy.
Importable from Blender's Python environment.

Usage:
  python tools/graph_builder.py \\
      --input  assets_src/skel_roots_skeleton.json \\
      --out    data/root_graph.json \\
      --root-at-top \\
      --tree-id sbcast_oak_01 \\
      --tour   tsp_2opt

  python tools/graph_builder.py \\
      --input  assets_src/skel_branches_skeleton.json \\
      --out    data/branch_graph.json \\
      --tree-id sbcast_oak_01 \\
      --tour   tsp_2opt

Exit codes: 0 = success, 1 = I/O failure, 2 = usage / bad input.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

SUPPORTED_SCHEMA_VERSION = "1.1"


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def _build_adjacency(n_nodes: int, edges: np.ndarray) -> dict[int, list[int]]:
    """Build an undirected adjacency list from a (E, 2) edge array."""
    adj: dict[int, list[int]] = {i: [] for i in range(n_nodes)}
    for u, v in edges:
        u, v = int(u), int(v)
        adj[u].append(v)
        adj[v].append(u)
    return adj


def _find_root_node(positions: np.ndarray, root_at_top: bool) -> int:
    """Return the index of the collar/base node.

    root_at_top=True  → highest Y (downward-growing roots: collar is at top).
    root_at_top=False → lowest Y  (upward-growing branches: base is at bottom).
    """
    if root_at_top:
        return int(np.argmax(positions[:, 1]))
    return int(np.argmin(positions[:, 1]))


# ---------------------------------------------------------------------------
# BFS spanning tree — replaces networkx bfs_tree + topological_sort
# ---------------------------------------------------------------------------

def _bfs_spanning_tree(
    adj: dict[int, list[int]],
    root: int,
    n_nodes: int,
) -> tuple[list[int], dict[int, list[int]]]:
    """Return (bfs_order, children) for the BFS spanning tree rooted at root.

    bfs_order  — nodes in breadth-first discovery order.
    children   — dict[node] = list of tree children (directed away from root).
    Disconnected nodes are not reachable from root and appear in neither list.
    """
    children: dict[int, list[int]] = {i: [] for i in range(n_nodes)}
    visited = [False] * n_nodes
    visited[root] = True
    queue: deque[int] = deque([root])
    bfs_order: list[int] = []

    while queue:
        node = queue.popleft()
        bfs_order.append(node)
        for nb in adj[node]:
            if not visited[nb]:
                visited[nb] = True
                children[node].append(nb)
                queue.append(nb)

    return bfs_order, children


# ---------------------------------------------------------------------------
# Graph metric computation
# ---------------------------------------------------------------------------

def _compute_depth_orders(
    bfs_order: list[int],
    children: dict[int, list[int]],
    root: int,
    n_nodes: int,
) -> dict[int, int]:
    """BFS hop count from root to every reachable node."""
    depths: dict[int, int] = {root: 0}
    for node in bfs_order:
        for child in children[node]:
            depths[child] = depths[node] + 1
    for i in range(n_nodes):
        depths.setdefault(i, 0)
    return depths


def _compute_branch_orders(
    bfs_order: list[int],
    children: dict[int, list[int]],
    root: int,
    n_nodes: int,
) -> dict[int, int]:
    """Count bifurcation nodes on the path from root (botanical branching order).

    trunk_base = 0.  Each time the path passes through a node with ≥2 children,
    the order increments by 1.
    """
    orders: dict[int, int] = {root: 0}
    for node in bfs_order:
        is_bifurcation = len(children[node]) >= 2
        for child in children[node]:
            orders[child] = orders[node] + (1 if is_bifurcation else 0)
    for i in range(n_nodes):
        orders.setdefault(i, 0)
    return orders


def _compute_strahler_orders(
    bfs_order: list[int],
    children: dict[int, list[int]],
    n_nodes: int,
) -> dict[int, int]:
    """Strahler stream order over the BFS spanning tree.

    Computed in reverse BFS order (leaves → root):
      Leaf node   → Strahler = 1
      Internal node → max child order; +1 when two or more children tie.
    """
    strahler: dict[int, int] = {}
    for node in reversed(bfs_order):
        node_children = children[node]
        if not node_children:
            strahler[node] = 1
        else:
            child_orders = sorted(
                [strahler[c] for c in node_children], reverse=True
            )
            if len(child_orders) >= 2 and child_orders[0] == child_orders[1]:
                strahler[node] = child_orders[0] + 1
            else:
                strahler[node] = child_orders[0]
    for i in range(n_nodes):
        strahler.setdefault(i, 1)
    return strahler


def _classify_node(
    node: int,
    root: int,
    degree: int,
    strahler: int,
    max_strahler: int,
) -> str:
    """Map a node to one of {trunk_base, primary, lateral, fine, terminal}.

    Based on Strahler order relative to graph maximum (SPEC §6.4):
      ≥ 75 % → primary   (thick structural roots / main branches)
      ≥ 40 % → lateral   (secondary branching)
      < 40 % → fine      (thin distal tips)
      degree 1 → terminal  (leaf nodes)
      root → trunk_base
    """
    if node == root:
        return "trunk_base"
    if degree == 1:
        return "terminal"
    ratio = strahler / max(max_strahler, 1)
    if ratio >= 0.75:
        return "primary"
    if ratio >= 0.40:
        return "lateral"
    return "fine"


# ---------------------------------------------------------------------------
# TSP tour  (stdlib + numpy — no scipy KDTree)
# ---------------------------------------------------------------------------

def _nearest_neighbor_tour(positions: np.ndarray, start: int) -> list[int]:
    """Greedy nearest-neighbor tour from start.

    Uses vectorised np.linalg.norm instead of scipy KDTree; fast enough for
    the skeleton sizes used in this project (< 600 nodes).
    """
    n = len(positions)
    visited = np.zeros(n, dtype=bool)
    tour = [start]
    visited[start] = True

    for _ in range(n - 1):
        current = tour[-1]
        dists = np.linalg.norm(positions - positions[current], axis=1)
        dists[visited] = np.inf
        nearest = int(np.argmin(dists))
        tour.append(nearest)
        visited[nearest] = True

    return tour


def _tour_length(positions: np.ndarray, tour: list[int]) -> float:
    """Sum of Euclidean distances for a closed tour (last → first included)."""
    n = len(tour)
    total = 0.0
    for i in range(n):
        total += float(
            np.linalg.norm(positions[tour[(i + 1) % n]] - positions[tour[i]])
        )
    return total


def _tsp_2opt(
    positions: np.ndarray,
    tour: list[int],
    max_passes: int = 30,
) -> list[int]:
    """Improve a closed tour with 2-opt edge swaps (SPEC §6.5)."""
    n = len(tour)
    if n < 4:
        return tour
    for _ in range(max_passes):
        improved = False
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                prev_i = tour[i - 1]
                curr_i = tour[i]
                curr_j = tour[j]
                next_j = tour[(j + 1) % n]
                d_old = float(
                    np.linalg.norm(positions[prev_i] - positions[curr_i])
                    + np.linalg.norm(positions[curr_j] - positions[next_j])
                )
                d_new = float(
                    np.linalg.norm(positions[prev_i] - positions[curr_j])
                    + np.linalg.norm(positions[curr_i] - positions[next_j])
                )
                if d_new < d_old - 1e-10:
                    tour[i: j + 1] = tour[i: j + 1][::-1]
                    improved = True
        if not improved:
            break
    return tour


def _compute_tsp_tour(
    positions: np.ndarray,
    root: int,
    method: str,
) -> list[int]:
    """Compute a closed TSP tour starting from root.

    The tour is closed: positions[tour[-1]] → positions[tour[0]] closes
    the loop, required for the RAVE latent trajectory to loop seamlessly
    (SPEC §6.5).
    """
    if method != "tsp_2opt":
        raise ValueError(
            f"Unsupported tour method '{method}'. Only 'tsp_2opt' is supported."
        )
    tour = _nearest_neighbor_tour(positions, root)
    return _tsp_2opt(positions, tour)


# ---------------------------------------------------------------------------
# Core: assemble SPEC §5.1 JSON
# ---------------------------------------------------------------------------

def build_graph(
    positions: np.ndarray,
    edges: np.ndarray,
    radii: np.ndarray,
    root_node: int,
    tree_id: str,
    source_mesh: str,
    tour_method: str,
) -> dict[str, Any]:
    """Assemble the SPEC §5.1 root_graph.json data structure.

    Parameters
    ----------
    positions   : (K, 3) node positions in Unity Y-up space (metres).
    edges       : (E, 2) undirected edge index pairs.
    radii       : (K,) per-node tube radius in metres (from Blender export).
    root_node   : index of the trunk_base / collar node.
    tree_id     : written to the tree_id field.
    source_mesh : name of the Blender source object (provenance).
    tour_method : must be 'tsp_2opt'.
    """
    n_nodes = len(positions)
    adj = _build_adjacency(n_nodes, edges)
    bfs_order, children = _bfs_spanning_tree(adj, root_node, n_nodes)

    depth_orders  = _compute_depth_orders(bfs_order, children, root_node, n_nodes)
    branch_orders = _compute_branch_orders(bfs_order, children, root_node, n_nodes)
    strahler      = _compute_strahler_orders(bfs_order, children, n_nodes)
    max_strahler  = max(strahler.values()) if strahler else 1

    bmin = positions.min(axis=0).tolist()
    bmax = positions.max(axis=0).tolist()

    # Nodes
    nodes_out: list[dict[str, Any]] = []
    for i in range(n_nodes):
        degree = len(adj[i])
        cls = _classify_node(i, root_node, degree, strahler[i], max_strahler)
        nodes_out.append({
            "id":           i,
            "position":     [round(float(v), 6) for v in positions[i]],
            "radius":       round(float(radii[i]), 6),
            "depth_order":  int(depth_orders[i]),
            "branch_order": int(branch_orders[i]),
            "is_terminal":  bool(degree == 1 and i != root_node),
            "class":        cls,
        })

    # Edges (deduplicated, length in Unity space)
    edges_out: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for u, v in edges:
        key = (min(int(u), int(v)), max(int(u), int(v)))
        if key in seen:
            continue
        seen.add(key)
        length = float(np.linalg.norm(positions[u] - positions[v]))
        edges_out.append({
            "source": int(u),
            "target": int(v),
            "length": round(length, 6),
        })

    # TSP tour
    log.info("Computing %s tour over %d nodes …", tour_method, n_nodes)
    tour_seq = _compute_tsp_tour(positions, root_node, tour_method)
    tour_len = _tour_length(positions, tour_seq)

    return {
        "schema_version":   SUPPORTED_SCHEMA_VERSION,
        "tree_id":          tree_id,
        "generated_utc":    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_mesh":      source_mesh,
        "units":            "meters",
        "coordinate_space": "unity_y_up",
        "bounds": {
            "min": [round(v, 6) for v in bmin],
            "max": [round(v, 6) for v in bmax],
        },
        "nodes":    nodes_out,
        "edges":    edges_out,
        "emitters": [],   # reserved — SPEC §3.3
        "tours": [{
            "name":          "tsp_primary",
            "method":        tour_method,
            "node_sequence": tour_seq,
            "total_length":  round(tour_len, 4),
            "rendered_stem": "track_root_rave.wav",
        }],
    }


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------

def load_skeleton_json(
    path: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    """Load a Blender-exported skeleton JSON from assets_src/.

    Returns
    -------
    positions   : (K, 3) float64, Unity Y-up metres.
    edges       : (E, 2) int64.
    radii       : (K,)  float64, metres.
    source_mesh : name of the Blender source object.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        log.error("Cannot read %s: %s", path, exc)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        log.error("Invalid JSON in %s: %s", path, exc)
        sys.exit(1)

    if data.get("coordinate_space") != "unity_y_up":
        log.error(
            "%s has coordinate_space=%r — expected 'unity_y_up'. "
            "Re-export from Blender with the Unity coordinate conversion.",
            path, data.get("coordinate_space"),
        )
        sys.exit(2)

    raw_nodes = data["nodes"]
    positions = np.array([n["position"] for n in raw_nodes], dtype=np.float64)
    radii     = np.array([n["radius"]   for n in raw_nodes], dtype=np.float64)
    raw_edges = data["edges"]
    edges     = np.array([[e["source"], e["target"]] for e in raw_edges], dtype=np.int64)

    source_mesh = data.get("source_mesh", data.get("object", path.stem))
    return positions, edges, radii, source_mesh


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build SPEC §5.1 root_graph.json from a Blender-exported skeleton JSON. "
            "Pure stdlib + numpy — no trimesh, networkx, or scipy required."
        )
    )
    parser.add_argument(
        "--input", required=True, metavar="JSON",
        help="Path to assets_src/skel_*_skeleton.json (exported from Blender).",
    )
    parser.add_argument(
        "--out", required=True, metavar="JSON",
        help="Output path for root_graph.json or branch_graph.json.",
    )
    parser.add_argument(
        "--tree-id", default="sbcast_oak_01",
        help="Value for the tree_id field (default: sbcast_oak_01).",
    )
    parser.add_argument(
        "--root-at-top", action="store_true",
        help=(
            "Pick the highest-Y node as root. "
            "Use for downward-growing roots whose collar is at the top of the "
            "mesh in Unity Y-up space."
        ),
    )
    parser.add_argument(
        "--tour", default="tsp_2opt",
        help="TSP tour method (default: tsp_2opt).",
    )

    args = parser.parse_args()
    in_path  = Path(args.input)
    out_path = Path(args.out)

    if not in_path.exists():
        log.error("Input file not found: %s", in_path)
        sys.exit(2)

    positions, edges, radii, source_mesh = load_skeleton_json(in_path)

    root_node = _find_root_node(positions, args.root_at_top)
    log.info(
        "Loaded: %d nodes, %d edges  |  root=%d  pos=%s",
        len(positions), len(edges), root_node,
        [round(float(v), 3) for v in positions[root_node]],
    )

    graph = build_graph(
        positions=positions,
        edges=edges,
        radii=radii,
        root_node=root_node,
        tree_id=args.tree_id,
        source_mesh=source_mesh,
        tour_method=args.tour,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        out_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    except IOError as exc:
        log.error("Failed to write %s: %s", out_path, exc)
        sys.exit(1)

    n_nodes  = len(graph["nodes"])
    n_edges  = len(graph["edges"])
    tour_len = graph["tours"][0]["total_length"]
    node_classes: dict[str, int] = {}
    for nd in graph["nodes"]:
        node_classes[nd["class"]] = node_classes.get(nd["class"], 0) + 1

    log.info("Written:      %s", out_path)
    log.info("Nodes: %d  Edges: %d  Tour: %.3f m", n_nodes, n_edges, tour_len)
    log.info("Classes:      %s", node_classes)
    log.info("schema_version: %s  coordinate_space: unity_y_up", SUPPORTED_SCHEMA_VERSION)
    log.info("Done. Run `python tools/validate_assets.py` to verify.")


if __name__ == "__main__":
    main()
