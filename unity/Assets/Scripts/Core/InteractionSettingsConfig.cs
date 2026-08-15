using UnityEngine;

namespace AquiFuturo.Core
{
    /// <summary>Tunable interaction values (SPEC §10, §15).</summary>
    [CreateAssetMenu(fileName = "InteractionSettings", menuName = "AquiFuturo/Interaction Settings")]
    public sealed class InteractionSettingsConfig : ScriptableObject
    {
        [Tooltip("Minimum milliseconds between accepted touches on the same node.")]
        public float debounceMs = 120f;

        [Tooltip("Screen-space tap radius in pixels. A node within this distance from the touch " +
                 "point (in screen pixels) is considered hit. 80 px ≈ fingertip at iPhone resolution.")]
        public float screenSpaceTapRadiusPx = 80f;

        [Tooltip("Spatial hash cell size in metres (SPEC §10).")]
        public float spatialHashCellSize = 0.25f;

        [Tooltip("Pitch variation range in semitones for interaction one-shots.")]
        public float pitchVarSemitones = 2f;
    }
}
