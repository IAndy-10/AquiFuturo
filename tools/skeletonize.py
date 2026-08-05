"""
skeletonize.py — AquiFuturo root skeleton → root_graph.json  (SPEC §6.4 / §5.1)

Reads a mesh file (PLY, GLB, OBJ …), extracts a curve skeleton, classifies
nodes, computes a closed TSP 2-opt tour, converts to Unity Y-up coordinates,
and writes root_graph.json conforming to schema_version "1.1".

Adapted from:
  Real 3D/mesh to skeleton/main.py
  Real 3D/mesh to skeleton/skeleton/extractor.py

Usage:
  python tools/skeletonize.py \\
      --mesh assets_src/skel_roots_main.ply \\
      --out  data/root_graph.json \\
      --tour tsp_2opt \\
      --coordinate-space unity_y_up \\
      --root-at-top

  # Branches skeleton (collar at bottom, tips at top)
  python tools/skeletonize.py \\
      --mesh assets_src/skel_branches.ply \\
      --out  data/branch_graph.json \\
      --tour tsp_2opt \\
      --coordinate-space unity_y_up

Exit codes: 0 = success, 1 = extraction/export failure, 2 = usage/dependency error.
"""

from __future__ import annotations

import argparse
import heapq
import json
import logging
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
import trimesh
from scipy.spatial import KDTree

logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

SUPPORTED_SCHEMA_VERSION = "1.1"
FRAGMENTED_THRESHOLD = 100
DOMINANT_COMPONENT_RATIO = 0.20


# ---------------------------------------------------------------------------
# Mesh loading  (adapted from Real 3D/mesh to skeleton/main.py)
# ---------------------------------------------------------------------------

def load_mesh(path: str) -> trimesh.Trimesh:
    """Load a mesh or scene file and merge all geometries into one mesh.

    Supports .glb, .gltf, .obj, .ply, .stl, and .fbx (via ufbx).
    """
    if path.lower().endswith(".fbx"):
        return _load_fbx(path)

    loaded = trimesh.load(path, force="mesh")

    if isinstance(loaded, trimesh.Scene):
        meshes = [g for g in loaded.geometry.values()
                  if isinstance(g, trimesh.Trimesh)]
        if not meshes:
            log.error("No triangle meshes found in scene.")
            sys.exit(1)
        loaded = trimesh.util.concatenate(meshes)

    if not isinstance(loaded, trimesh.Trimesh):
        log.error("Could not load a triangle mesh from the file.")
        sys.exit(1)

    return loaded


def _load_fbx(path: str) -> trimesh.Trimesh:
    """Load FBX using ufbx in an isolated subprocess to avoid GC crash.

    ufbx 0.0.5 segfaults during Python GC teardown.  Running in a child
    that calls os._exit(0) skips teardown entirely.
    """
    import os
    import subprocess
    import tempfile

    _CONVERTER = """
import ufbx, numpy as np, os, sys

fbx_path   = sys.argv[1]
verts_path = sys.argv[2]
faces_path = sys.argv[3]

scene = ufbx.load_file(fbx_path)
if not scene.meshes:
    sys.stderr.write("No meshes in FBX\\n")
    os._exit(1)

all_verts, all_faces, offset = [], [], 0
for m in scene.meshes:
    v = np.array([[x.x, x.y, x.z] for x in m.vertices], dtype=float)
    idx = np.array(m.vertex_indices)
    f = []
    for face in m.faces:
        b, n = face.index_begin, face.num_indices
        fv = idx[b : b + n].tolist()
        for i in range(1, n - 1):
            f.append([fv[0], fv[i], fv[i + 1]])
    all_verts.append(v)
    all_faces.append(np.array(f, dtype=int) + offset)
    offset += len(v)

np.save(verts_path, np.concatenate(all_verts))
np.save(faces_path, np.concatenate(all_faces))
os._exit(0)
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        verts_path = os.path.join(tmpdir, "verts.npy")
        faces_path = os.path.join(tmpdir, "faces.npy")

        result = subprocess.run(
            [sys.executable, "-c", _CONVERTER, path, verts_path, faces_path],
            capture_output=True,
            timeout=120,
        )

        if not os.path.exists(verts_path):
            stderr = result.stderr.decode(errors="replace")
            log.error("FBX conversion failed (exit %d):\n%s",
                      result.returncode, stderr)
            sys.exit(1)

        vertices = np.load(verts_path)
        faces = np.load(faces_path)

    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def decimate_mesh(mesh: trimesh.Trimesh, target_faces: int) -> trimesh.Trimesh:
    """Reduce triangle count. Falls back gracefully if simplification stalls."""
    if len(mesh.faces) <= target_faces:
        return mesh
    ratio = 1.0 - (target_faces / len(mesh.faces))
    try:
        import fast_simplification as fs
        v, f = fs.simplify(
            mesh.vertices.astype(float),
            mesh.faces.astype(int),
            target_reduction=max(0.0, min(ratio, 0.999)),
        )
        return trimesh.Trimesh(vertices=v, faces=f, process=False)
    except Exception as exc:
        log.warning("Decimation failed (%s) — using original mesh.", exc)
        return mesh


def component_centers(mesh: trimesh.Trimesh, min_faces: int = 3) -> np.ndarray:
    """Return one center-of-mass per connected component (fragmented mesh mode)."""
    comps = mesh.split(only_watertight=False)
    comps = [c for c in comps if len(c.faces) >= min_faces]
    if not comps:
        return np.zeros((0, 3), dtype=float)
    return np.array([c.vertices.mean(axis=0) for c in comps], dtype=float)


# ---------------------------------------------------------------------------
# Skeleton extraction  (adapted from Real 3D/mesh to skeleton/skeleton/extractor.py)
#
# Algorithm: Jiang et al. "Curve skeleton extraction by coupled graph
# contraction and surface clustering", Graphical Models 75 (2013) 137-148.
# ---------------------------------------------------------------------------

class SkeletonExtractor:
    """Extract a curve skeleton from a triangular mesh or point cloud.

    Three construction paths:
      * __init__          — surface contraction on a connected mesh.
      * from_geodesic()   — geodesic-shell slicing (recommended for tube/branch
                            meshes with complex non-convex branching).
      * from_point_cloud()— k-NN graph over a point cloud (fragmented meshes).

    After construction, call extract() then skeleton_arrays().
    """

    def __init__(
        self,
        vertices: np.ndarray,
        faces: np.ndarray,
        n_seeds_initial: int = 200,
        reduction_ratio: float = 0.7,
        eccentricity_strength: float = 0.1,
        min_nodes: int = 10,
    ) -> None:
        self.verts = np.asarray(vertices, dtype=float)
        self.faces = np.asarray(faces, dtype=int)
        self.n_seeds_initial = n_seeds_initial
        self.r = reduction_ratio
        self.ecc = eccentricity_strength
        self.min_nodes = min_nodes

        self._precompute_vertex_weights()
        self.G = self._build_initial_graph()
        self.clusters: dict[int, np.ndarray] = {
            n: np.array([n], dtype=int) for n in self.G.nodes()
        }
        self._surface_kdtree = KDTree(self.verts)
        self._node_kdtree: KDTree | None = None

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _precompute_vertex_weights(self) -> None:
        v0 = self.verts[self.faces[:, 0]]
        v1 = self.verts[self.faces[:, 1]]
        v2 = self.verts[self.faces[:, 2]]
        areas = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)

        area_sum = np.zeros(len(self.verts))
        np.add.at(area_sum, self.faces[:, 0], areas)
        np.add.at(area_sum, self.faces[:, 1], areas)
        np.add.at(area_sum, self.faces[:, 2], areas)

        with np.errstate(divide="ignore"):
            self.vert_weights = np.where(area_sum > 1e-10, 1.0 / area_sum, 1e-6)

    def _build_initial_graph(self) -> nx.Graph:
        G: nx.Graph = nx.Graph()
        for i in range(len(self.verts)):
            G.add_node(i, pos=self.verts[i].copy(),
                       weight=float(self.vert_weights[i]))
        edges: set[tuple[int, int]] = set()
        for f in self.faces:
            a, b, c = int(f[0]), int(f[1]), int(f[2])
            edges.add((min(a, b), max(a, b)))
            edges.add((min(b, c), max(b, c)))
            edges.add((min(a, c), max(a, c)))
        G.add_edges_from(edges)
        return G

    # ------------------------------------------------------------------
    # Seed selection
    # ------------------------------------------------------------------

    def _select_seeds(self, n_seeds: int) -> list[int]:
        nodes = list(self.G.nodes())
        if len(nodes) <= n_seeds:
            return nodes

        seeds: set[int] = set()

        # Extremities (degree <= 2) are always seeds
        for nd in nodes:
            if self.G.degree(nd) <= 2:
                seeds.add(nd)

        if len(seeds) >= n_seeds:
            return list(seeds)[:n_seeds]

        # Greedy by degree
        remaining = [nd for nd in nodes if nd not in seeds]
        pq = [(-self.G.degree(nd), nd) for nd in remaining]
        heapq.heapify(pq)
        excluded: set[int] = set()
        while pq and len(seeds) < n_seeds:
            _, nd = heapq.heappop(pq)
            if nd in excluded:
                continue
            seeds.add(nd)
            for nb in self.G.neighbors(nd):
                excluded.add(nb)

        # Random fill
        if len(seeds) < n_seeds:
            candidates = [nd for nd in nodes if nd not in seeds]
            if candidates:
                rng = np.random.default_rng(0)
                extra = rng.choice(
                    candidates,
                    size=min(n_seeds - len(seeds), len(candidates)),
                    replace=False,
                )
                seeds.update(int(e) for e in extra)

        return list(seeds)

    # ------------------------------------------------------------------
    # Grassfire + Euclidean fallback
    # ------------------------------------------------------------------

    def _assign_nodes_to_seeds(self, seeds: list[int]) -> dict[int, int]:
        assignment: dict[int, int] = {}
        queue: deque[int] = deque()
        for s in seeds:
            if self.G.has_node(s):
                assignment[s] = s
                queue.append(s)
        while queue:
            nd = queue.popleft()
            seed = assignment[nd]
            for nb in self.G.neighbors(nd):
                if nb not in assignment:
                    assignment[nb] = seed
                    queue.append(nb)

        unassigned = [nd for nd in self.G.nodes() if nd not in assignment]
        if unassigned and self._node_kdtree is not None:
            unassigned_pos = np.array([self.G.nodes[nd]["pos"]
                                       for nd in unassigned])
            _, nearest_idx = self._node_kdtree.query(unassigned_pos)
            seed_list = list(seeds)
            for nd, idx in zip(unassigned, nearest_idx):
                assignment[nd] = seed_list[idx % len(seed_list)]

        for nd in self.G.nodes():
            if nd not in assignment:
                assignment[nd] = nd
        return assignment

    def _rebuild_node_kdtree(self, seeds: list[int]) -> None:
        seed_positions = np.array([
            self.G.nodes[s]["pos"] for s in seeds if self.G.has_node(s)
        ])
        if len(seed_positions) > 0:
            self._node_kdtree = KDTree(seed_positions)

    # ------------------------------------------------------------------
    # Cluster center
    # ------------------------------------------------------------------

    def _cluster_center(self, vert_indices: np.ndarray) -> np.ndarray:
        verts = self.verts[vert_indices]
        w = self.vert_weights[vert_indices]
        total_w = w.sum()
        center = (
            (verts * w[:, None]).sum(axis=0) / total_w
            if total_w > 1e-10
            else verts.mean(axis=0)
        )
        if self.ecc > 0:
            _, idx = self._surface_kdtree.query(center)
            nearest = self.verts[idx]
            direction = center - nearest
            dist = np.linalg.norm(direction)
            if dist > 1e-8:
                center = center + self.ecc * direction
        return center

    # ------------------------------------------------------------------
    # One iteration
    # ------------------------------------------------------------------

    def _iteration(self, n_seeds: int) -> int:
        seeds = self._select_seeds(n_seeds)
        self._rebuild_node_kdtree(seeds)
        assignment = self._assign_nodes_to_seeds(seeds)

        new_clusters: dict[int, list[int]] = {}
        for nd, seed in assignment.items():
            if seed not in new_clusters:
                new_clusters[seed] = []
            if nd in self.clusters:
                new_clusters[seed].extend(self.clusters[nd].tolist())

        self.clusters = {
            s: np.array(vs, dtype=int)
            for s, vs in new_clusters.items()
            if vs
        }

        new_G: nx.Graph = nx.Graph()
        for seed, vert_indices in self.clusters.items():
            pos = self._cluster_center(vert_indices)
            w = float(self.vert_weights[vert_indices].sum())
            new_G.add_node(seed, pos=pos, weight=w)
        for u, v in self.G.edges():
            su = assignment.get(u)
            sv = assignment.get(v)
            if su is not None and sv is not None and su != sv:
                if new_G.has_node(su) and new_G.has_node(sv):
                    new_G.add_edge(su, sv)

        self.G = new_G
        return len(self.G.nodes())

    # ------------------------------------------------------------------
    # Public: extract()
    # ------------------------------------------------------------------

    def _is_forest(self) -> bool:
        n = self.G.number_of_nodes()
        e = self.G.number_of_edges()
        c = nx.number_connected_components(self.G)
        return e <= n - c

    def extract(self) -> tuple[nx.Graph, dict[int, np.ndarray]]:
        """Run skeleton extraction. No-op for geodesic / MST instances."""
        if getattr(self, "_skip_extraction", False):
            return self.G, self.clusters

        n_seeds = self.n_seeds_initial
        print(f"[Skeleton] Start: {len(self.G.nodes()):,} nodes, "
              f"{self.G.number_of_edges():,} edges")

        for iteration in range(50):
            if self._is_forest():
                print("[Skeleton] G is a forest — done.")
                break
            n_seeds = max(int(self.r * n_seeds), self.min_nodes)
            current_n = len(self.G.nodes())
            if n_seeds >= current_n:
                print(f"[Skeleton] Seeds ({n_seeds}) >= nodes ({current_n}) — done.")
                break
            new_n = self._iteration(n_seeds)
            print(f"[Skeleton] Iter {iteration + 1:2d}: "
                  f"{new_n:4d} nodes, {self.G.number_of_edges():4d} edges")
            if new_n <= self.min_nodes:
                print(f"[Skeleton] Reached min_nodes ({self.min_nodes}).")
                break

        self._connect_components()
        return self.G, self.clusters

    def _connect_components(self) -> None:
        components = list(nx.connected_components(self.G))
        if len(components) <= 1:
            return
        while len(components) > 1:
            best_dist = float("inf")
            best_edge: tuple[int, int] | None = None
            for i in range(len(components)):
                pos_i = np.array([self.G.nodes[n]["pos"] for n in components[i]])
                nodes_i = list(components[i])
                for j in range(i + 1, len(components)):
                    pos_j = np.array([self.G.nodes[n]["pos"]
                                      for n in components[j]])
                    nodes_j = list(components[j])
                    tree = KDTree(pos_j)
                    dists, idxs = tree.query(pos_i)
                    k = int(np.argmin(dists))
                    if dists[k] < best_dist:
                        best_dist = dists[k]
                        best_edge = (nodes_i[k], nodes_j[idxs[k]])
            if best_edge is not None:
                self.G.add_edge(*best_edge)
            components = list(nx.connected_components(self.G))
        print(f"[Skeleton] Components bridged → "
              f"{len(self.G.nodes())} nodes, {self.G.number_of_edges()} edges")

    # ------------------------------------------------------------------
    # Alternative constructor: geodesic shells
    # ------------------------------------------------------------------

    @classmethod
    def from_geodesic(
        cls,
        mesh: trimesh.Trimesh,
        n_shells: int = 60,
        cluster_eps_factor: float = 0.07,
        root_at_top: bool = False,
    ) -> "SkeletonExtractor":
        """Extract skeleton by geodesic distance shells from the mesh base.

        Recommended for tube/branch meshes where the standard contraction
        algorithm collapses complex non-convex structures to a star-burst hub.

        Parameters
        ----------
        mesh              : input mesh
        n_shells          : number of geodesic shells (more = finer skeleton)
        cluster_eps_factor: spatial clustering radius as fraction of mesh extent
        root_at_top       : if True, start from the highest-Y vertex (use for
                            downward-growing roots whose collar is at the top
                            of the mesh in Y-up space)
        """
        verts = np.asarray(mesh.vertices, dtype=float)
        faces = np.asarray(mesh.faces, dtype=int)
        n = len(verts)

        # Weighted adjacency list (unique edges only)
        adj: list[list[tuple[float, int]]] = [[] for _ in range(n)]
        seen: set[tuple[int, int]] = set()
        for f in faces:
            for i in range(3):
                a, b = int(f[i]), int(f[(i + 1) % 3])
                key = (min(a, b), max(a, b))
                if key not in seen:
                    seen.add(key)
                    d = float(np.linalg.norm(verts[a] - verts[b]))
                    adj[a].append((d, b))
                    adj[b].append((d, a))

        # Root vertex: lowest Y (tree base) or highest Y (root collar)
        root = int(np.argmax(verts[:, 1]) if root_at_top
                   else np.argmin(verts[:, 1]))

        # Dijkstra from root
        geo_dist = np.full(n, np.inf)
        geo_dist[root] = 0.0
        pq: list[tuple[float, int]] = [(0.0, root)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > geo_dist[u]:
                continue
            for w, v in adj[u]:
                nd = d + w
                if nd < geo_dist[v]:
                    geo_dist[v] = nd
                    heapq.heappush(pq, (nd, v))

        reachable = geo_dist < np.inf
        max_geo = float(geo_dist[reachable].max())
        cluster_eps = float(np.asarray(mesh.extents).max()) * cluster_eps_factor

        print(f"[Geodesic] root Y={verts[root, 1]:.3f}  "
              f"max_geo={max_geo:.3f}  cluster_eps={cluster_eps:.4f}")

        # Shell-by-shell skeleton build
        skel_G: nx.Graph = nx.Graph()
        skel_pos: list[np.ndarray] = []
        prev_shell: list[tuple[int, np.ndarray]] = []

        for shell_idx in range(n_shells):
            d_lo = max_geo * shell_idx / n_shells
            d_hi = max_geo * (shell_idx + 1) / n_shells

            mask = reachable & (geo_dist >= d_lo) & (geo_dist < d_hi)
            idx = np.where(mask)[0]
            if len(idx) == 0:
                continue

            pts = verts[idx]
            kd_s = KDTree(pts)
            pairs = kd_s.query_pairs(cluster_eps)
            G_s: nx.Graph = nx.Graph()
            G_s.add_nodes_from(range(len(pts)))
            G_s.add_edges_from(pairs)

            curr_shell: list[tuple[int, np.ndarray]] = []
            for comp in nx.connected_components(G_s):
                centroid = pts[list(comp)].mean(axis=0)
                nid = len(skel_pos)
                skel_pos.append(centroid)
                skel_G.add_node(nid, pos=centroid, weight=1.0)
                curr_shell.append((nid, centroid))

            if prev_shell and curr_shell:
                prev_centers = np.array([c for _, c in prev_shell])
                prev_ids = [nid for nid, _ in prev_shell]
                kd_prev = KDTree(prev_centers)
                for cid, cc in curr_shell:
                    _, idx2 = kd_prev.query(cc)
                    skel_G.add_edge(cid, prev_ids[int(idx2)])

            prev_shell = curr_shell

        n_skel = len(skel_pos)
        print(f"[Geodesic] {n_skel} skeleton nodes, "
              f"{skel_G.number_of_edges()} edges, "
              f"{nx.number_connected_components(skel_G)} component(s)")

        instance = cls.__new__(cls)
        instance.verts = verts
        instance.faces = faces
        instance.n_seeds_initial = 200
        instance.r = 0.7
        instance.min_nodes = 5
        instance.ecc = 0.0
        instance.vert_weights = np.ones(n, dtype=float)
        instance.G = skel_G
        instance.clusters = {i: np.array([i], dtype=int) for i in range(n_skel)}
        instance._surface_kdtree = KDTree(verts)
        instance._node_kdtree = None
        instance._skip_extraction = True
        return instance

    # ------------------------------------------------------------------
    # Alternative constructor: point cloud / k-NN
    # ------------------------------------------------------------------

    @classmethod
    def from_point_cloud(
        cls,
        positions: np.ndarray,
        k_neighbors: int = 6,
        n_seeds_initial: int = 200,
        reduction_ratio: float = 0.7,
        min_nodes: int = 10,
    ) -> "SkeletonExtractor":
        """Build extractor from a point cloud using a k-NN graph."""
        positions = np.asarray(positions, dtype=float)
        n = len(positions)

        instance = cls.__new__(cls)
        instance.verts = positions
        instance.faces = np.zeros((0, 3), dtype=int)
        instance.n_seeds_initial = n_seeds_initial
        instance.r = reduction_ratio
        instance.min_nodes = min_nodes
        instance.ecc = 0.0
        instance.vert_weights = np.ones(n, dtype=float)

        kd = KDTree(positions)
        k = min(k_neighbors + 1, n)
        _, indices = kd.query(positions, k=k)

        G: nx.Graph = nx.Graph()
        for i in range(n):
            G.add_node(i, pos=positions[i].copy(), weight=1.0)
        edges: set[tuple[int, int]] = set()
        for i in range(n):
            for j in indices[i, 1:]:
                a, b = int(i), int(j)
                edges.add((min(a, b), max(a, b)))
        G.add_edges_from(edges)

        instance.G = G
        instance.clusters = {i: np.array([i], dtype=int) for i in range(n)}
        instance._surface_kdtree = KDTree(positions)
        instance._node_kdtree = None
        return instance

    # ------------------------------------------------------------------
    # Output arrays
    # ------------------------------------------------------------------

    def skeleton_arrays(self) -> tuple[np.ndarray, np.ndarray]:
        """Return (positions, edges) arrays with nodes re-indexed 0..K-1."""
        node_list = list(self.G.nodes())
        node_index = {n: i for i, n in enumerate(node_list)}
        positions = np.array([self.G.nodes[n]["pos"] for n in node_list])
        edges = np.array(
            [[node_index[u], node_index[v]] for u, v in self.G.edges()],
            dtype=int,
        )
        return positions, edges


# ---------------------------------------------------------------------------
# Graph analysis  (new — not in main.py)
# ---------------------------------------------------------------------------

def _rebuild_graph(
    skel_positions: np.ndarray, skel_edges: np.ndarray
) -> nx.Graph:
    """Build a plain 0-indexed nx.Graph from skeleton arrays."""
    G: nx.Graph = nx.Graph()
    G.add_nodes_from(range(len(skel_positions)))
    for u, v in skel_edges:
        G.add_edge(int(u), int(v))
    return G


def _find_root_node(skel_positions: np.ndarray, root_at_top: bool) -> int:
    """Return the index of the collar/base node.

    root_at_top=True  → highest Y (use for downward-growing roots in Y-up space).
    root_at_top=False → lowest Y (use for upward-growing branches).
    """
    if root_at_top:
        return int(np.argmax(skel_positions[:, 1]))
    return int(np.argmin(skel_positions[:, 1]))


def _compute_depth_orders(G: nx.Graph, root: int) -> dict[int, int]:
    """BFS hop count from root to every node."""
    depths: dict[int, int] = {root: 0}
    queue: deque[int] = deque([root])
    while queue:
        node = queue.popleft()
        for nb in G.neighbors(node):
            if nb not in depths:
                depths[nb] = depths[node] + 1
                queue.append(nb)
    for n in G.nodes():
        if n not in depths:
            depths[n] = 0
    return depths


def _compute_branch_orders(G: nx.Graph, root: int) -> dict[int, int]:
    """Count bifurcation nodes (>=2 children in BFS tree) on path from root.

    Approximates botanical branching order:
      trunk_base = 0, first split produces branch_order 1, and so on.
    """
    orders: dict[int, int] = {root: 0}
    visited: set[int] = {root}
    queue: deque[int] = deque([root])

    while queue:
        node = queue.popleft()
        children = [nb for nb in G.neighbors(node) if nb not in visited]
        is_bifurcation = len(children) >= 2
        for child in children:
            visited.add(child)
            orders[child] = orders[node] + (1 if is_bifurcation else 0)
            queue.append(child)

    for n in G.nodes():
        if n not in orders:
            orders[n] = 0
    return orders


def _compute_strahler_orders(G: nx.Graph, root: int) -> dict[int, int]:
    """Strahler stream order over the BFS spanning tree.

    Leaves = 1.  A node's order equals the max child order; it increments
    by 1 when two or more children tie at the maximum.
    """
    tree = nx.bfs_tree(G, root)
    topo = list(nx.topological_sort(tree))
    strahler: dict[int, int] = {}

    for node in reversed(topo):
        children = list(tree.successors(node))
        if not children:
            strahler[node] = 1
        else:
            child_orders = sorted(
                [strahler[c] for c in children], reverse=True
            )
            if len(child_orders) >= 2 and child_orders[0] == child_orders[1]:
                strahler[node] = child_orders[0] + 1
            else:
                strahler[node] = child_orders[0]

    for n in G.nodes():
        if n not in strahler:
            strahler[n] = 1
    return strahler


def _classify_node(
    node: int,
    root: int,
    degree: int,
    strahler: int,
    max_strahler: int,
) -> str:
    """Map a skeleton node to one of {trunk_base, primary, lateral, fine, terminal}.

    Classification is based on Strahler order relative to the graph maximum:
      >= 75 % → primary   (thick structural roots)
      >= 40 % → lateral   (secondary branching)
      < 40 %  → fine      (thin distal roots)
      degree 1 → terminal (tips)
      root node → trunk_base (collar)
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


def _estimate_radii(
    skel_positions: np.ndarray,
    mesh_vertices: np.ndarray,
) -> np.ndarray:
    """Estimate tube radius at each skeleton node.

    For tube meshes (inflated skeletons such as the .ply outputs from the
    Blender skeletonization session), the nearest surface vertex is on the
    tube wall, so this distance equals the actual tube radius.
    """
    kdtree = KDTree(mesh_vertices)
    dists, _ = kdtree.query(skel_positions)
    return dists.astype(float)


# ---------------------------------------------------------------------------
# TSP tour  (SPEC §5.1 / §6.5 — closed tour for seamless RAVE loop)
# ---------------------------------------------------------------------------

def _nearest_neighbor_tour(positions: np.ndarray, start: int) -> list[int]:
    """Greedy nearest-neighbor tour starting from `start`."""
    n = len(positions)
    visited = [False] * n
    tour = [start]
    visited[start] = True
    kdtree = KDTree(positions)

    while len(tour) < n:
        current = tour[-1]
        k = min(n, 32)
        _, idxs = kdtree.query(positions[current], k=k)
        found = False
        for idx in idxs:
            if not visited[int(idx)]:
                tour.append(int(idx))
                visited[int(idx)] = True
                found = True
                break
        if not found:
            unvisited = [i for i in range(n) if not visited[i]]
            if unvisited:
                dists = np.linalg.norm(
                    positions[unvisited] - positions[current], axis=1
                )
                nearest = unvisited[int(np.argmin(dists))]
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
    positions: np.ndarray, tour: list[int], max_passes: int = 30
) -> list[int]:
    """Improve a closed tour with 2-opt edge swaps."""
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
    """Compute a closed TSP tour starting from `root`.

    The tour is closed: positions[tour[-1]] → positions[tour[0]] closes
    the loop, which is required for the RAVE latent trajectory to loop
    seamlessly (SPEC §6.5).
    """
    if method != "tsp_2opt":
        raise ValueError(
            f"Unsupported tour method '{method}'. Only 'tsp_2opt' is supported."
        )
    tour = _nearest_neighbor_tour(positions, root)
    tour = _tsp_2opt(positions, tour)
    return tour


# ---------------------------------------------------------------------------
# Coordinate conversion  (SPEC §2.1)
# ---------------------------------------------------------------------------

def _to_unity_y_up(positions: np.ndarray) -> np.ndarray:
    """Convert glTF Y-up (right-handed) → Unity Y-up (left-handed).

    Only the Z axis flips:  (x, y, z) → (x, y, -z).
    This matches the glTF → Unity import convention described in SPEC §2.1.
    """
    converted = positions.copy()
    converted[:, 2] *= -1.0
    return converted


# ---------------------------------------------------------------------------
# JSON assembly  (SPEC §5.1)
# ---------------------------------------------------------------------------

def build_root_graph(
    skel_positions: np.ndarray,
    skel_edges: np.ndarray,
    mesh_vertices: np.ndarray,
    root_node: int,
    tree_id: str,
    source_mesh: str,
    tour_method: str,
    coordinate_space: str,
) -> dict[str, Any]:
    """Assemble the root_graph.json data structure.

    Parameters
    ----------
    skel_positions  : (K, 3) skeleton node positions in the INPUT coordinate
                      space (gltf_y_up as loaded from the PLY file).
    skel_edges      : (E, 2) edge pairs, indices into skel_positions.
    mesh_vertices   : (N, 3) original mesh surface vertices used to estimate
                      tube radii.
    root_node       : index of the trunk_base node in skel_positions.
    tree_id         : value for the tree_id JSON field.
    source_mesh     : basename of the input file for the source_mesh field.
    tour_method     : TSP method name, must be 'tsp_2opt'.
    coordinate_space: 'unity_y_up' (Z-flip applied) or 'gltf_y_up' (as-is).
    """
    G = _rebuild_graph(skel_positions, skel_edges)

    # Attributes computed in input (gltf) space — topology is space-agnostic
    depth_orders = _compute_depth_orders(G, root_node)
    branch_orders = _compute_branch_orders(G, root_node)
    strahler = _compute_strahler_orders(G, root_node)
    max_strahler = max(strahler.values()) if strahler else 1
    radii = _estimate_radii(skel_positions, mesh_vertices)

    # Coordinate conversion
    if coordinate_space == "unity_y_up":
        out_positions = _to_unity_y_up(skel_positions)
    else:
        out_positions = skel_positions.copy()

    # Bounds (in output space)
    bmin = out_positions.min(axis=0).tolist()
    bmax = out_positions.max(axis=0).tolist()

    # Nodes
    nodes: list[dict[str, Any]] = []
    for i in range(len(out_positions)):
        cls = _classify_node(
            i, root_node, G.degree(i), strahler[i], max_strahler
        )
        nodes.append({
            "id": i,
            "position": [round(float(v), 6) for v in out_positions[i]],
            "radius": round(float(radii[i]), 6),
            "depth_order": int(depth_orders[i]),
            "branch_order": int(branch_orders[i]),
            "is_terminal": bool(G.degree(i) == 1 and i != root_node),
            "class": cls,
        })

    # Edges (lengths in output space)
    edges: list[dict[str, Any]] = []
    for u, v in G.edges():
        length = float(np.linalg.norm(out_positions[u] - out_positions[v]))
        edges.append({
            "source": int(u),
            "target": int(v),
            "length": round(length, 6),
        })

    # TSP tour (in output space so distances match what RAVE receives)
    log.info("      Computing %s tour over %d nodes …", tour_method,
             len(out_positions))
    tour_sequence = _compute_tsp_tour(out_positions, root_node, tour_method)
    total_length = _tour_length(out_positions, tour_sequence)

    tours: list[dict[str, Any]] = [
        {
            "name": "tsp_primary",
            "method": tour_method,
            "node_sequence": tour_sequence,
            "total_length": round(total_length, 4),
            # rendered_stem links this tour to the RAVE-decoded audio file
            # (SPEC §5.1 — provenance record for the thesis pipeline)
            "rendered_stem": "track_root_rave.wav",
        }
    ]

    return {
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "tree_id": tree_id,
        "generated_utc": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "source_mesh": source_mesh,
        "units": "meters",
        "coordinate_space": coordinate_space,
        "bounds": {
            "min": [round(v, 6) for v in bmin],
            "max": [round(v, 6) for v in bmax],
        },
        "nodes": nodes,
        "edges": edges,
        "emitters": [],   # reserved for future 3D-audio build (SPEC §3.3)
        "tours": tours,
    }


# ---------------------------------------------------------------------------
# Polyscope visualisation  (--viz flag; requires polyscope>=2.1.0)
# ---------------------------------------------------------------------------

#: Node-class colour palette (RGB 0-1) used in the Polyscope viewer.
_CLASS_COLORS: dict[str, list[float]] = {
    "trunk_base": [0.80, 0.10, 0.10],  # red
    "primary":    [0.90, 0.50, 0.10],  # orange
    "lateral":    [0.90, 0.85, 0.10],  # yellow
    "fine":       [0.20, 0.70, 0.20],  # green
    "terminal":   [0.20, 0.40, 0.90],  # blue
}


def _visualize_polyscope(
    mesh: trimesh.Trimesh,
    skel_positions: np.ndarray,
    skel_edges: np.ndarray,
    graph: dict[str, Any],
) -> None:
    """Open an interactive Polyscope window showing the mesh + skeleton overlay.

    Skeleton nodes are coloured by class; the TSP tour is highlighted in magenta.
    Both the mesh and skeleton must be in the same coordinate space before calling.
    """
    try:
        import polyscope as ps  # noqa: PLC0415
    except ImportError:
        log.error(
            "polyscope is not installed. Install it with: "
            "pip install 'polyscope>=2.1.0'"
        )
        return

    ps.init()
    ps.set_up_dir("y_up")

    # ── Mesh surface (semi-transparent) ───────────────────────────────────────
    ps_mesh = ps.register_surface_mesh("mesh", mesh.vertices, mesh.faces)
    ps_mesh.set_transparency(0.70)   # 0 = opaque, 1 = invisible in Polyscope
    ps_mesh.set_color((0.75, 0.65, 0.55))

    # ── Skeleton nodes coloured by class ──────────────────────────────────────
    nodes = graph["nodes"]
    node_colors = np.array(
        [_CLASS_COLORS.get(n["class"], [0.5, 0.5, 0.5]) for n in nodes],
        dtype=float,
    )
    ps_pts = ps.register_point_cloud("skeleton_nodes", skel_positions)
    ps_pts.add_color_quantity("class", node_colors, enabled=True)
    ps_pts.set_radius(0.015, relative=False)

    # ── Skeleton edges ────────────────────────────────────────────────────────
    ps_edges = ps.register_curve_network(
        "skeleton_edges", skel_positions, skel_edges, radius=0.005
    )
    ps_edges.set_color((0.85, 0.85, 0.85))

    # ── TSP tour (magenta) ────────────────────────────────────────────────────
    if graph.get("tours"):
        seq = graph["tours"][0]["node_sequence"]
        tour_edge_arr = np.array(
            [[seq[i], seq[i + 1]] for i in range(len(seq) - 1)],
            dtype=int,
        )
        ps_tour = ps.register_curve_network(
            "tsp_tour", skel_positions, tour_edge_arr, radius=0.008
        )
        ps_tour.set_color((0.90, 0.20, 0.80))

    # Legend hint
    log.info(
        "Polyscope legend — nodes: red=trunk_base  orange=primary  "
        "yellow=lateral  green=fine  blue=terminal  | magenta=TSP tour"
    )
    log.info("Close the Polyscope window to exit.")
    ps.show()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Extract a curve skeleton from a mesh and write root_graph.json "
            "(SPEC §6.4 / §5.1)."
        )
    )
    parser.add_argument(
        "--mesh", required=True,
        help="Path to input mesh file (.ply, .glb, .obj, …)",
    )
    parser.add_argument(
        "--out", required=True,
        help="Output path for root_graph.json",
    )
    parser.add_argument(
        "--tree-id", default="sbcast_oak_01",
        help="Tree identifier written to tree_id field (default: sbcast_oak_01)",
    )
    parser.add_argument(
        "--coordinate-space",
        choices=["unity_y_up", "gltf_y_up"],
        default="unity_y_up",
        help=(
            "Output coordinate space. 'unity_y_up' flips the Z axis to convert "
            "from glTF right-handed to Unity left-handed convention (SPEC §2.1). "
            "Default: unity_y_up"
        ),
    )
    parser.add_argument(
        "--tour", default="tsp_2opt",
        help="TSP tour method written to tours[].method (default: tsp_2opt)",
    )
    parser.add_argument(
        "--root-at-top", action="store_true",
        help=(
            "Treat the highest-Y vertex as the skeleton root. Use this for "
            "downward-growing root meshes (skel_roots_main.ply) whose collar "
            "sits at the top of the mesh in Y-up space."
        ),
    )
    # Geodesic extraction parameters
    parser.add_argument(
        "--shells", type=int, default=60,
        help="Number of geodesic distance shells for connected meshes (default: 60). "
             "More shells = finer skeleton but slower.",
    )
    parser.add_argument(
        "--cluster-eps", type=float, default=0.07,
        help=(
            "Spatial cluster radius as a fraction of mesh extent in geodesic mode "
            "(default: 0.07). Increase if branches merge; decrease if they split."
        ),
    )
    # Fragmented-mesh fallback parameters
    parser.add_argument(
        "--seeds", type=int, default=500,
        help="Initial Voronoi seed count for point-cloud / surface mode (default: 500)",
    )
    parser.add_argument(
        "--reduction", type=float, default=0.85,
        help="Seed reduction ratio per iteration in point-cloud mode (default: 0.85)",
    )
    parser.add_argument(
        "--min-nodes", type=int, default=20,
        help="Stop contracting when skeleton node count reaches this value (default: 20)",
    )
    parser.add_argument(
        "--knn", type=int, default=6,
        help="k-NN connections per point in point-cloud mode (default: 6)",
    )
    parser.add_argument(
        "--mst", action="store_true",
        help=(
            "Use Minimum Spanning Tree instead of k-NN for fragmented meshes. "
            "Required for root meshes where k-NN produces hub-collapse starburst."
        ),
    )
    # Decimation
    parser.add_argument(
        "--target-faces", type=int, default=10_000,
        help=(
            "Target face count after decimation (default: 10000). "
            "For tube skeleton meshes use --no-decimate to preserve thin geometry."
        ),
    )
    parser.add_argument(
        "--no-decimate", action="store_true",
        help=(
            "Skip mesh decimation. Recommended for .ply tube skeleton files "
            "(skel_roots_main.ply, skel_branches.ply) where thin tubes collapse "
            "under aggressive simplification."
        ),
    )
    # Origin
    parser.add_argument(
        "--center-at-root", action="store_true",
        help=(
            "Shift all node positions so the trunk_base node is at the origin. "
            "Use only if the Blender model origin is not already at the trunk base."
        ),
    )
    parser.add_argument(
        "--viz", action="store_true",
        help=(
            "Open an interactive Polyscope viewer after extraction. "
            "Shows the mesh surface (semi-transparent) overlaid with the skeleton "
            "nodes (coloured by class) and the TSP tour (magenta). "
            "Requires polyscope>=2.1.0 to be installed."
        ),
    )

    args = parser.parse_args()

    mesh_path = Path(args.mesh)
    out_path = Path(args.out)

    if not mesh_path.exists():
        log.error("Mesh file not found: %s", mesh_path)
        sys.exit(2)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # ── 1. Load ──────────────────────────────────────────────────────────────
    log.info("[1/5] Loading %s", mesh_path)
    mesh = load_mesh(str(mesh_path))
    log.info("      %d vertices, %d faces", len(mesh.vertices), len(mesh.faces))

    # Preserve original surface vertices for radius estimation before decimation
    original_vertices = mesh.vertices.copy()

    # ── 2. Decimate ───────────────────────────────────────────────────────────
    if args.no_decimate:
        log.info("[2/5] Skipping decimation (--no-decimate)")
    else:
        log.info("[2/5] Decimating to ~%d faces …", args.target_faces)
        mesh = decimate_mesh(mesh, args.target_faces)
        log.info("      After decimation: %d vertices, %d faces",
                 len(mesh.vertices), len(mesh.faces))

    # ── 3. Extract skeleton ────────────────────────────────────────────────────
    log.info("[3/5] Extracting skeleton …")

    comps = mesh.split(only_watertight=False)
    n_comps = len(comps)
    total_faces = sum(len(c.faces) for c in comps)
    log.info("      Connected components: %d", n_comps)

    if n_comps <= FRAGMENTED_THRESHOLD:
        # Connected mesh → geodesic shell mode.
        # Preferred over surface contraction for tube/skeleton meshes because
        # contraction collapses complex non-convex branching to a star-burst hub.
        log.info("      Connected mesh → geodesic shell mode "
                 "(shells=%d, cluster_eps=%.2f)", args.shells, args.cluster_eps)
        extractor = SkeletonExtractor.from_geodesic(
            mesh,
            n_shells=args.shells,
            cluster_eps_factor=args.cluster_eps,
            root_at_top=args.root_at_top,
        )
        mode = "geodesic shells"

    else:
        comps_sorted = sorted(comps, key=lambda c: len(c.faces), reverse=True)
        largest_ratio = len(comps_sorted[0].faces) / total_faces

        if largest_ratio >= DOMINANT_COMPONENT_RATIO:
            # One large component dominates → geodesic on the structural mesh
            threshold = total_faces * 0.01
            structural = [c for c in comps_sorted if len(c.faces) >= threshold]
            struct_mesh = (
                structural[0] if len(structural) == 1
                else trimesh.util.concatenate(structural)
            )
            kept_pct = 100 * sum(len(c.faces) for c in structural) / total_faces
            log.info(
                "      Dominant component (%.0f%% of faces) → "
                "geodesic on structural mesh (%.0f%% of faces kept)",
                largest_ratio * 100, kept_pct,
            )
            extractor = SkeletonExtractor.from_geodesic(
                struct_mesh,
                n_shells=args.shells,
                cluster_eps_factor=args.cluster_eps,
                root_at_top=args.root_at_top,
            )
            mode = "geodesic shells (structural component)"

        else:
            # No dominant component → point-cloud or MST mode
            centers = component_centers(mesh, min_faces=1)
            log.info("      No dominant component → %d component centers",
                     len(centers))
            if len(centers) < 2:
                log.error("Not enough components to build a skeleton.")
                sys.exit(1)

            if args.mst:
                from scipy.sparse import csr_matrix
                from scipy.sparse.csgraph import (
                    minimum_spanning_tree as _mst_fn,
                )
                from scipy.spatial.distance import cdist

                dist_mat = cdist(centers, centers)
                mst_coo = _mst_fn(csr_matrix(dist_mat)).tocoo()

                instance = SkeletonExtractor.__new__(SkeletonExtractor)
                instance.verts = centers
                instance.faces = np.zeros((0, 3), dtype=int)
                instance.vert_weights = np.ones(len(centers), dtype=float)
                instance.ecc = 0.0
                instance.n_seeds_initial = args.seeds
                instance.r = args.reduction
                instance.min_nodes = args.min_nodes

                G_mst: nx.Graph = nx.Graph()
                for i, pos in enumerate(centers):
                    G_mst.add_node(i, pos=pos, weight=1.0)
                for i, j in zip(mst_coo.row, mst_coo.col):
                    G_mst.add_edge(int(i), int(j))

                instance.G = G_mst
                instance.clusters = {
                    i: np.array([i], dtype=int) for i in range(len(centers))
                }
                instance._surface_kdtree = KDTree(centers)
                instance._node_kdtree = None
                instance._skip_extraction = True
                extractor = instance
                mode = "MST"

            else:
                extractor = SkeletonExtractor.from_point_cloud(
                    positions=centers,
                    k_neighbors=args.knn,
                    n_seeds_initial=args.seeds,
                    reduction_ratio=args.reduction,
                    min_nodes=args.min_nodes,
                )
                mode = "point-cloud k-NN"

    extractor.extract()
    skel_positions, skel_edges = extractor.skeleton_arrays()

    log.info("      Mode: %s → %d nodes, %d edges",
             mode, len(skel_positions), len(skel_edges))

    if len(skel_positions) < 2:
        log.error(
            "Skeleton too sparse (%d nodes). "
            "Try --shells with a higher value or --cluster-eps with a smaller value.",
            len(skel_positions),
        )
        sys.exit(1)

    # ── 4. Find root and optionally re-centre ─────────────────────────────────
    log.info("[4/5] Computing node attributes …")

    root_node = _find_root_node(skel_positions, args.root_at_top)
    log.info("      Root node: %d  pos (input space): %s",
             root_node, np.round(skel_positions[root_node], 4).tolist())

    if args.center_at_root:
        root_pos = skel_positions[root_node].copy()
        skel_positions = skel_positions - root_pos
        original_vertices = original_vertices - root_pos
        # Also shift the (decimated) mesh so --viz overlay stays aligned
        mesh = trimesh.Trimesh(
            vertices=mesh.vertices - root_pos, faces=mesh.faces, process=False
        )
        log.info("      Shifted origin to root node (--center-at-root)")

    # ── 5. Build JSON and write ───────────────────────────────────────────────
    log.info("[5/5] Building root_graph.json …")

    graph = build_root_graph(
        skel_positions=skel_positions,
        skel_edges=skel_edges,
        mesh_vertices=original_vertices,
        root_node=root_node,
        tree_id=args.tree_id,
        source_mesh=mesh_path.name,
        tour_method=args.tour,
        coordinate_space=args.coordinate_space,
    )

    try:
        out_path.write_text(
            json.dumps(graph, indent=2), encoding="utf-8"
        )
    except IOError as exc:
        log.error("Failed to write %s: %s", out_path, exc)
        sys.exit(1)

    n_nodes = len(graph["nodes"])
    n_edges = len(graph["edges"])
    tour_len = graph["tours"][0]["total_length"]
    node_classes: dict[str, int] = {}
    for nd in graph["nodes"]:
        node_classes[nd["class"]] = node_classes.get(nd["class"], 0) + 1

    log.info("      Written: %s", out_path)
    log.info("      Nodes: %d  Edges: %d  Tour length: %.3f m",
             n_nodes, n_edges, tour_len)
    log.info("      Node classes: %s", node_classes)
    log.info("      schema_version: %s  coordinate_space: %s",
             SUPPORTED_SCHEMA_VERSION, args.coordinate_space)
    log.info("Done. Run `python tools/validate_assets.py` to verify.")

    # ── Optional interactive viewer ────────────────────────────────────────────
    if args.viz:
        log.info("Opening Polyscope viewer …")
        _visualize_polyscope(mesh, skel_positions, skel_edges, graph)


if __name__ == "__main__":
    main()
