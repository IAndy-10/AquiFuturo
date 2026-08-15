using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace AquiFuturo.Graph
{
    /// <summary>
    /// Loads and validates root_graph.json from StreamingAssets (SPEC §5.1, §5.4).
    /// Schema version mismatch throws InvalidOperationException — never silently accepted.
    /// The spatial hash is built in Start(), not lazily on first touch (SPEC §10).
    /// </summary>
    public sealed class RootGraphLoader : MonoBehaviour
    {
        [SerializeField] private string _graphFileName = "root_graph.json";
        [SerializeField] private AquiFuturo.Core.InteractionSettingsConfig _interactionConfig;

        public RootGraph   Graph       { get; private set; }
        public SpatialHash SpatialHash { get; private set; }

        public bool IsLoaded => Graph != null;

        private float _cellSize = 0.25f;

        // Cached transform for world→graph-space back-projection in NearestNodeTo.
        private Transform _treeTransform;
        private float     _hashScaleMultiplier = 1f;

        private void Start()
        {
            string path = Path.Combine(Application.streamingAssetsPath, _graphFileName);

            try
            {
                string json = File.ReadAllText(path);
                Graph = Parse(json);
            }
            catch (FileNotFoundException)
            {
                Debug.LogWarning($"[RootGraphLoader] {_graphFileName} not found at {path}. " +
                                 "Graph features will be disabled until the file is supplied.");
                return;
            }
            catch (Exception ex)
            {
                Debug.LogError($"[RootGraphLoader] Failed to load graph: {ex.Message}");
                return;
            }

            // SPEC §10: spatial hash must be built in Start(), not on first touch.
            _cellSize = _interactionConfig != null
                ? _interactionConfig.spatialHashCellSize
                : 0.25f;

            SpatialHash = new SpatialHash(_cellSize);
            foreach (var node in Graph.Nodes)
                SpatialHash.Insert(node);

            Debug.Log($"[RootGraphLoader] Loaded graph '{Graph.TreeId}' " +
                      $"with {Graph.Nodes.Count} nodes, {Graph.Edges.Count} edges.");
        }

        // ── Public API ────────────────────────────────────────────────────

        /// <summary>
        /// Rebuilds the spatial hash in graph space and caches the tree transform so that
        /// <see cref="NearestNodeTo"/> can back-project world hit points into graph space.
        /// Called by RootMeshBuilder after the FBX tree is placed.
        /// scaleMultiplier should be 1.0 when FBX graph and FBX mesh share the same metre scale.
        /// </summary>
        public void RebuildSpatialHashInWorldSpace(
            Transform treeRoot, float scaleMultiplier, Vector3 originOffset)
        {
            if (Graph == null) return;

            _treeTransform       = treeRoot;
            _hashScaleMultiplier = scaleMultiplier > 0f ? scaleMultiplier : 1f;

            // Hash stays in graph space — queries are back-projected by NearestNodeTo().
            var hash = new SpatialHash(_cellSize);
            foreach (RootNode node in Graph.Nodes)
                hash.Insert(node);

            SpatialHash = hash;

            // Debug: log trunk_base world position to verify alignment with hit points.
            foreach (RootNode node in Graph.Nodes)
            {
                if (node.Class == "trunk_base")
                {
                    Vector3 dbgWorld = treeRoot.TransformPoint(node.Position * _hashScaleMultiplier);
                    Debug.Log($"[RootGraphLoader] trunk_base world={dbgWorld} graph={node.Position} scale={_hashScaleMultiplier}");
                    break;
                }
            }

            Debug.Log($"[RootGraphLoader] Spatial hash rebuilt in graph space " +
                      $"(treeRoot={treeRoot.position} scale={_hashScaleMultiplier}).");
        }

        /// <summary>
        /// Converts a graph-space node position back to Unity world space.
        /// Inverse of the world→graph back-projection used in <see cref="NearestNodeTo"/>.
        /// Returns <c>Vector3.zero</c> if the tree transform is not yet set.
        /// </summary>
        public Vector3 NodeWorldPosition(RootNode node)
        {
            if (_treeTransform == null) return Vector3.zero;
            // Inverse of (local.x, local.z, -local.y) → (graph.x, graph.y, graph.z):
            // graph=(gx,gy,gz) → local=(gx,-gz,gy), then scale and transform.
            Vector3 local = new Vector3(node.Position.x, -node.Position.z, node.Position.y)
                            * _hashScaleMultiplier;
            return _treeTransform.TransformPoint(local);
        }

        /// <summary>
        /// Returns the graph node nearest to <paramref name="worldPoint"/> by back-projecting
        /// the world-space hit point into graph space before querying the spatial hash.
        /// Use this instead of <c>SpatialHash.NearestTo</c> in <c>RootInteraction</c>.
        /// </summary>
        public RootNode NearestNodeTo(Vector3 worldPoint)
        {
            if (SpatialHash == null)
            {
                Debug.LogWarning("[RootGraphLoader] NearestNodeTo: SpatialHash is null.");
                return null;
            }
            if (_treeTransform == null)
            {
                Debug.LogWarning("[RootGraphLoader] NearestNodeTo: _treeTransform is null — " +
                                 "RebuildSpatialHashInWorldSpace was never called. " +
                                 "Ensure TreePlacement._rootMeshBuilder is wired in Inspector.");
                return null;
            }

            // FBX is imported with bakeAxisConversion=0 and the prefab overrides the
            // root rotation to identity, leaving vertices in Blender Z-up local space.
            // Graph nodes are in Unity Y-up. The conversion is Rot(-90°X): (X,Y,Z)→(X,Z,-Y).
            Vector3 local = _treeTransform.InverseTransformPoint(worldPoint) / _hashScaleMultiplier;
            // bakeAxisConversion=0 + identity rotation override: mesh is in Blender Z-up local space.
            // Graph is in Unity Y-up. Rot(-90°X): (X,Y,Z)→(X,Z,-Y).
            Vector3 graphPoint = new Vector3(local.x, local.z, -local.y);
            Debug.Log($"[RootGraphLoader] NearestNodeTo: world={worldPoint} local={local} → graph={graphPoint}");

            RootNode result = SpatialHash.NearestTo(graphPoint);
            if (result != null) return result;

            // Linear scan fallback — skeleton is sparse (~545 nodes) so this is fast.
            // Triggered when the hit lands in an empty hash cell (fine root regions).
            RootNode best   = null;
            float    bestSq = float.MaxValue;
            foreach (RootNode node in Graph.Nodes)
            {
                float sq = (node.Position - graphPoint).sqrMagnitude;
                if (sq < bestSq) { bestSq = sq; best = node; }
            }
            if (best != null)
                Debug.Log($"[RootGraphLoader] Hash miss — linear scan found node {best.Id} " +
                          $"class={best.Class} dist={Mathf.Sqrt(bestSq):F2}m");
            return best;
        }

        // ── Private parsing ───────────────────────────────────────────────

        private static RootGraph Parse(string json)
        {
            var raw = JsonUtility.FromJson<RawGraph>(json);

            // SPEC §5.1: schema_version mismatch must throw, never be silently accepted.
            if (raw.schema_version != RootGraph.SupportedVersion)
                throw new InvalidOperationException(
                    $"[RootGraphLoader] root_graph.json schema_version '{raw.schema_version}' " +
                    $"is not supported. Expected '{RootGraph.SupportedVersion}'.");

            var nodes = new List<RootNode>(raw.nodes?.Length ?? 0);
            if (raw.nodes != null)
            {
                foreach (var rn in raw.nodes)
                {
                    nodes.Add(new RootNode(
                        rn.id,
                        new Vector3(rn.position[0], rn.position[1], rn.position[2]),
                        rn.radius,
                        rn.depth_order,
                        rn.branch_order,
                        rn.is_terminal,
                        rn.@class));
                }
            }

            var edges = new List<RootEdge>(raw.edges?.Length ?? 0);
            if (raw.edges != null)
            {
                foreach (var re in raw.edges)
                    edges.Add(new RootEdge(re.source, re.target, re.length));
            }

            var bounds = new Bounds();
            if (raw.bounds != null)
            {
                var mn = raw.bounds.min;
                var mx = raw.bounds.max;
                bounds = new Bounds(
                    new Vector3((mn[0] + mx[0]) / 2f, (mn[1] + mx[1]) / 2f, (mn[2] + mx[2]) / 2f),
                    new Vector3(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]));
            }

            return new RootGraph(
                raw.schema_version,
                raw.tree_id,
                raw.generated_utc,
                raw.units,
                raw.coordinate_space,
                bounds,
                nodes,
                edges);
        }

        // ── JSON-serialisable mirror types ────────────────────────────────

        [Serializable]
        private class RawGraph
        {
            public string     schema_version;
            public string     tree_id;
            public string     generated_utc;
            public string     units;
            public string     coordinate_space;
            public RawBounds  bounds;
            public RawNode[]  nodes;
            public RawEdge[]  edges;
        }

        [Serializable]
        private class RawBounds
        {
            public float[] min;
            public float[] max;
        }

        [Serializable]
        private class RawNode
        {
            public int     id;
            public float[] position;
            public float   radius;
            public int     depth_order;
            public int     branch_order;
            public bool    is_terminal;
            public string  @class;
        }

        [Serializable]
        private class RawEdge
        {
            public int   source;
            public int   target;
            public float length;
        }
    }
}
