using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace AquiFuturo.Graph
{
    /// <summary>
    /// Builds a single combined procedural tube mesh from a loaded RootGraph (SPEC §5.1).
    /// One tapered tube is generated per edge, scaled by node radii.
    /// The mesh is parented to the placed tree root and assigned to the "RootMesh" layer
    /// so RootInteraction can raycast against it (SPEC §10).
    /// Call BuildMesh(treeRoot) once after tree placement; call ClearMesh() on reset.
    /// </summary>
    public sealed class RootMeshBuilder : MonoBehaviour
    {
        [SerializeField] private RootMeshConfig _config;
        [SerializeField] private RootGraphLoader _graphLoader;

        [Header("Testing")]
        [Tooltip("Build the mesh at Start() without placement. Disable before field sessions.")]
        [SerializeField] private bool _buildOnStart;

        private GameObject _meshRoot;

        private void Start()
        {
            if (_buildOnStart)
                BuildMesh(transform);
        }

        // ── Public API ────────────────────────────────────────────────────

        /// <summary>
        /// Generates the root tube mesh and parents it to <paramref name="treeRoot"/>.
        /// The trunk_base node is placed at treeRoot's local origin.
        /// </summary>
        public void BuildMesh(Transform treeRoot)
        {
            if (_graphLoader == null || !_graphLoader.IsLoaded)
            {
                Debug.LogWarning("[RootMeshBuilder] RootGraphLoader not ready — skipping mesh build. " +
                                 "Ensure root_graph.json is in StreamingAssets and schema_version is '1.1'.");
                return;
            }

            ClearMesh();

            RootGraph graph  = _graphLoader.Graph;
            int       sides  = _config != null ? _config.tubeSides       : 6;
            float     scale  = _config != null ? _config.scaleMultiplier : 1f;

            // Build fast node lookups
            var nodePos    = new Dictionary<int, Vector3>(graph.Nodes.Count);
            var nodeRadius = new Dictionary<int, float>(graph.Nodes.Count);
            Vector3 originOffset = Vector3.zero;

            foreach (RootNode node in graph.Nodes)
            {
                nodePos[node.Id]    = node.Position;
                nodeRadius[node.Id] = node.Radius;
                if (node.Class == "trunk_base")
                    originOffset = node.Position;
            }

            // One tube mesh per edge
            var combines   = new List<CombineInstance>(graph.Edges.Count);
            var tempMeshes = new List<Mesh>(graph.Edges.Count);

            foreach (RootEdge edge in graph.Edges)
            {
                if (!nodePos.TryGetValue(edge.Source, out Vector3 startPos)) continue;
                if (!nodePos.TryGetValue(edge.Target, out Vector3 endPos))   continue;

                float sr = nodeRadius.TryGetValue(edge.Source, out float s) ? s : 0.01f;
                float er = nodeRadius.TryGetValue(edge.Target,  out float e) ? e : 0.01f;

                // Shift so trunk_base sits at local origin, then apply scale
                Vector3 localStart = (startPos - originOffset) * scale;
                Vector3 localEnd   = (endPos   - originOffset) * scale;

                Mesh tube = CreateTubeMesh(localStart, localEnd, sr * scale, er * scale, sides);
                tempMeshes.Add(tube);
                combines.Add(new CombineInstance { mesh = tube, transform = Matrix4x4.identity });
            }

            if (combines.Count == 0)
            {
                Debug.LogWarning("[RootMeshBuilder] No edges produced geometry — mesh not built.");
                return;
            }

            // Combine into one draw call
            var combined = new Mesh { name = "RootGraphMesh" };
            combined.indexFormat = IndexFormat.UInt32; // safe for large graphs
            combined.CombineMeshes(combines.ToArray(), mergeSubMeshes: true, useMatrices: true);
            combined.RecalculateNormals();
            combined.RecalculateBounds();

            // Temp per-edge meshes are no longer needed
            foreach (Mesh m in tempMeshes)
                Destroy(m);

            // Build the scene GameObject
            int layer = LayerMask.NameToLayer("RootMesh");
            if (layer == -1)
            {
                Debug.LogWarning("[RootMeshBuilder] 'RootMesh' layer not found. " +
                                 "Create it in Project Settings → Tags & Layers. " +
                                 "RootInteraction raycasts will miss this mesh until then.");
                layer = 0;
            }

            _meshRoot = new GameObject("RootGraphMesh") { layer = layer };
            _meshRoot.transform.SetParent(treeRoot, worldPositionStays: false);
            _meshRoot.transform.localPosition = Vector3.zero;
            _meshRoot.transform.localRotation = Quaternion.identity;
            _meshRoot.transform.localScale    = Vector3.one;

            var mf = _meshRoot.AddComponent<MeshFilter>();
            var mr = _meshRoot.AddComponent<MeshRenderer>();
            var mc = _meshRoot.AddComponent<MeshCollider>();

            mf.sharedMesh = combined;
            mc.sharedMesh = combined;

            if (_config != null && _config.rootMaterial != null)
                mr.sharedMaterial = _config.rootMaterial;

            Debug.Log($"[RootMeshBuilder] Built root mesh: {graph.Edges.Count} edges, " +
                      $"{combined.vertexCount} vertices. Origin offset = {originOffset}.");
        }

        /// <summary>Destroys the generated mesh. Call on placement reset.</summary>
        public void ClearMesh()
        {
            if (_meshRoot != null)
            {
                Destroy(_meshRoot);
                _meshRoot = null;
            }
        }

        // ── Private ───────────────────────────────────────────────────────

        /// <summary>
        /// Generates a tapered tube mesh between two points in local space.
        /// Start and end rings have independent radii for natural tapering.
        /// </summary>
        private static Mesh CreateTubeMesh(
            Vector3 start, Vector3 end,
            float startRadius, float endRadius,
            int sides)
        {
            Vector3 dir = end - start;
            if (dir.sqrMagnitude < 1e-8f)
                return new Mesh(); // degenerate zero-length edge

            dir.Normalize();

            // Build orthonormal basis perpendicular to the tube axis
            Vector3 perp = Mathf.Abs(Vector3.Dot(dir, Vector3.up)) < 0.99f
                ? Vector3.Cross(dir, Vector3.up).normalized
                : Vector3.Cross(dir, Vector3.right).normalized;
            Vector3 perp2 = Vector3.Cross(dir, perp).normalized;

            var verts = new Vector3[sides * 2];
            var tris  = new int[sides * 6];
            float step = 2f * Mathf.PI / sides;

            for (int i = 0; i < sides; i++)
            {
                float cos = Mathf.Cos(i * step);
                float sin = Mathf.Sin(i * step);
                Vector3 ring = cos * perp + sin * perp2;
                verts[i]         = start + ring * startRadius;
                verts[sides + i] = end   + ring * endRadius;
            }

            for (int i = 0; i < sides; i++)
            {
                int next = (i + 1) % sides;
                int ti   = i * 6;
                // Winding: outward-facing normals when viewed from outside the tube
                tris[ti]     = i;
                tris[ti + 1] = sides + i;
                tris[ti + 2] = next;
                tris[ti + 3] = next;
                tris[ti + 4] = sides + i;
                tris[ti + 5] = sides + next;
            }

            var mesh = new Mesh { name = "RootTube" };
            mesh.vertices  = verts;
            mesh.triangles = tris;
            mesh.RecalculateNormals();
            mesh.RecalculateBounds();
            return mesh;
        }
    }
}
