using UnityEngine;

namespace AquiFuturo.Graph
{
    /// <summary>Visual quality and appearance tunables for the procedural root mesh (SPEC §15).</summary>
    [CreateAssetMenu(fileName = "RootMeshSettings", menuName = "AquiFuturo/Root Mesh Settings")]
    public sealed class RootMeshConfig : ScriptableObject
    {
        [Header("Geometry")]
        [Tooltip("Polygon sides per tube cross-section. Higher = smoother, more vertices.")]
        [Range(3, 12)]
        public int tubeSides = 6;

        [Header("Appearance")]
        [Tooltip("Material applied to the combined root mesh. If null, Unity default diffuse is used.")]
        public Material rootMaterial;
    }
}
