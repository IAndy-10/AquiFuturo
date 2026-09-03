using System.Collections.Generic;
using UnityEngine;

namespace AquiFuturo.Graph
{
    /// <summary>
    /// In-memory representation of root_graph.json (SPEC §5.1).
    /// Produced by RootGraphLoader after schema_version validation.
    /// </summary>
    public sealed class RootGraph
    {
        /// <summary>Schema version this build understands. Reject anything else (SPEC §5.1).</summary>
        public const string SupportedVersion = "1.1";

        public string SchemaVersion  { get; }
        public string TreeId         { get; }
        public string GeneratedUtc   { get; }
        public string Units          { get; }
        public string CoordinateSpace { get; }
        public Bounds WorldBounds    { get; }

        public IReadOnlyList<RootNode> Nodes { get; }
        public IReadOnlyList<RootEdge> Edges { get; }

        public RootGraph(
            string schemaVersion,
            string treeId,
            string generatedUtc,
            string units,
            string coordinateSpace,
            Bounds worldBounds,
            IReadOnlyList<RootNode> nodes,
            IReadOnlyList<RootEdge> edges)
        {
            SchemaVersion   = schemaVersion;
            TreeId          = treeId;
            GeneratedUtc    = generatedUtc;
            Units           = units;
            CoordinateSpace = coordinateSpace;
            WorldBounds     = worldBounds;
            Nodes           = nodes;
            Edges           = edges;
        }
    }

    /// <summary>A single node in the root skeleton graph (SPEC §5.1).</summary>
    public sealed class RootNode
    {
        public int     Id          { get; }
        public Vector3 Position    { get; }
        public float   Radius      { get; }
        public int     DepthOrder  { get; }
        public int     BranchOrder { get; }
        public bool    IsTerminal  { get; }
        public string  Class       { get; }   // trunk_base | primary | lateral | fine | terminal

        public RootNode(int id, Vector3 position, float radius,
                        int depthOrder, int branchOrder, bool isTerminal, string nodeClass)
        {
            Id          = id;
            Position    = position;
            Radius      = radius;
            DepthOrder  = depthOrder;
            BranchOrder = branchOrder;
            IsTerminal  = isTerminal;
            Class       = nodeClass;
        }
    }

    /// <summary>A directed edge between two nodes (SPEC §5.1).</summary>
    public sealed class RootEdge
    {
        public int   Source { get; }
        public int   Target { get; }
        public float Length { get; }

        public RootEdge(int source, int target, float length)
        {
            Source = source;
            Target = target;
            Length = length;
        }
    }
}
