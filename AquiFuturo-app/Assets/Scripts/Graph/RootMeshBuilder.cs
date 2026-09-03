using UnityEngine;

namespace AquiFuturo.Graph
{
    /// <summary>
    /// Rebuilds the spatial hash in world space after the FBX tree is placed (SPEC §5.1, §10).
    /// Collision comes from the MeshCollider on the FBX RootA child (layer "RootMesh").
    /// Call BuildMesh(treeRoot) once after tree placement; call ClearMesh() on reset.
    /// </summary>
    public sealed class RootMeshBuilder : MonoBehaviour
    {
        [SerializeField] private RootMeshConfig _config;
        [SerializeField] private RootGraphLoader _graphLoader;

        [Header("Testing")]
        [Tooltip("Rebuild the spatial hash at Start() without placement. Disable before field sessions.")]
        [SerializeField] private bool _buildOnStart;

        private System.Collections.IEnumerator Start()
        {
            if (!_buildOnStart) yield break;

            // Wait one frame so RootGraphLoader.Start() has run first.
            yield return null;

            BuildMesh(transform);
        }

        // ── Public API ────────────────────────────────────────────────────

        /// <summary>
        /// Rebuilds the spatial hash in world space so RootInteraction hit points resolve correctly.
        /// Graph node positions are in the same metre-scale coordinate space as the FBX vertices.
        /// scaleMultiplier should be 1.0 for FBX-based placement (set in RootMeshSettings asset).
        /// </summary>
        public void BuildMesh(Transform treeRoot)
        {
            if (_graphLoader == null || !_graphLoader.IsLoaded)
            {
                Debug.LogWarning("[RootMeshBuilder] RootGraphLoader not ready — skipping spatial hash rebuild. " +
                                 "Ensure root_graph.json is in StreamingAssets and schema_version is '1.1'.");
                return;
            }

            RootGraph graph = _graphLoader.Graph;
            float     scale = _config != null ? _config.scaleMultiplier : 1f;

            // originOffset not used — FBX positions are not re-centred at treeRoot.
            _graphLoader.RebuildSpatialHashInWorldSpace(treeRoot, scale, Vector3.zero);

            Debug.Log($"[RootMeshBuilder] Spatial hash rebuilt: {graph.Nodes.Count} nodes.");
        }

        /// <summary>No-op stub — mesh lives on the FBX prefab. Called by TreePlacement on reset.</summary>
        public void ClearMesh() { }
    }
}
