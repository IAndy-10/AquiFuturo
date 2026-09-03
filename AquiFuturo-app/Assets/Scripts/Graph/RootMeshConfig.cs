using UnityEngine;

namespace AquiFuturo.Graph
{
    /// <summary>Tunables for root graph spatial mapping (SPEC §15).</summary>
    [CreateAssetMenu(fileName = "RootMeshSettings", menuName = "AquiFuturo/Root Mesh Settings")]
    public sealed class RootMeshConfig : ScriptableObject
    {
        [Tooltip("Uniform scale applied to graph-space node positions when rebuilding the spatial hash. " +
                 "Match this to the scale set on the FBX root in the prefab.")]
        [Range(0.001f, 200f)]
        public float scaleMultiplier = 1f;
    }
}
