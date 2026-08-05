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

        public RootGraph Graph      { get; private set; }
        public SpatialHash SpatialHash { get; private set; }

        public bool IsLoaded => Graph != null;

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
            float cellSize = _interactionConfig != null
                ? _interactionConfig.spatialHashCellSize
                : 0.25f;

            SpatialHash = new SpatialHash(cellSize);
            foreach (var node in Graph.Nodes)
                SpatialHash.Insert(node);

            Debug.Log($"[RootGraphLoader] Loaded graph '{Graph.TreeId}' " +
                      $"with {Graph.Nodes.Count} nodes, {Graph.Edges.Count} edges.");
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
