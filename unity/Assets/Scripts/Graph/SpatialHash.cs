using System.Collections.Generic;
using UnityEngine;

namespace AquiFuturo.Graph
{
    /// <summary>
    /// Uniform-grid spatial hash over root graph nodes for O(1) nearest-node lookup
    /// per touch event (SPEC §10). Built once in Start() — never lazily on first touch.
    /// </summary>
    public sealed class SpatialHash
    {
        private readonly float _cellSize;
        private readonly float _invCellSize;
        private readonly Dictionary<long, List<RootNode>> _cells;

        public SpatialHash(float cellSize)
        {
            _cellSize    = cellSize;
            _invCellSize = 1f / cellSize;
            _cells       = new Dictionary<long, List<RootNode>>();
        }

        /// <summary>Inserts a node into the hash at its graph-space position.</summary>
        public void Insert(RootNode node)
        {
            Insert(node, node.Position);
        }

        /// <summary>
        /// Inserts a node into the hash at an explicit position (e.g. world space).
        /// Use this overload when the lookup space differs from node.Position.
        /// </summary>
        public void Insert(RootNode node, Vector3 atPosition)
        {
            long key = CellKey(atPosition);
            if (!_cells.TryGetValue(key, out var list))
            {
                list = new List<RootNode>(4);
                _cells[key] = list;
            }
            list.Add(node);
        }

        /// <summary>
        /// Returns the nearest node to the query point, or null if the hash is empty.
        /// Searches the 3×3×3 neighbourhood of the query cell (27 cells).
        /// </summary>
        public RootNode NearestTo(Vector3 point)
        {
            int cx = Mathf.FloorToInt(point.x * _invCellSize);
            int cy = Mathf.FloorToInt(point.y * _invCellSize);
            int cz = Mathf.FloorToInt(point.z * _invCellSize);

            RootNode best    = null;
            float    bestSq  = float.MaxValue;

            for (int dx = -1; dx <= 1; dx++)
            for (int dy = -1; dy <= 1; dy++)
            for (int dz = -1; dz <= 1; dz++)
            {
                long key = PackKey(cx + dx, cy + dy, cz + dz);
                if (!_cells.TryGetValue(key, out var list)) continue;

                foreach (var node in list)
                {
                    float sq = (node.Position - point).sqrMagnitude;
                    if (sq < bestSq)
                    {
                        bestSq = sq;
                        best   = node;
                    }
                }
            }

            return best;
        }

        // ── Key packing ───────────────────────────────────────────────────

        private long CellKey(Vector3 pos)
        {
            int cx = Mathf.FloorToInt(pos.x * _invCellSize);
            int cy = Mathf.FloorToInt(pos.y * _invCellSize);
            int cz = Mathf.FloorToInt(pos.z * _invCellSize);
            return PackKey(cx, cy, cz);
        }

        /// <summary>Packs three 20-bit signed integers into a single long key.</summary>
        private static long PackKey(int x, int y, int z)
        {
            // Offset to unsigned range (20 bits → max ±524287).
            const int offset = 1 << 19;
            long ux = (long)(x + offset) & 0xFFFFF;
            long uy = (long)(y + offset) & 0xFFFFF;
            long uz = (long)(z + offset) & 0xFFFFF;
            return (ux << 40) | (uy << 20) | uz;
        }
    }
}
