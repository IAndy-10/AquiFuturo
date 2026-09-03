using UnityEngine;

namespace AquiFuturo.Core
{
    /// <summary>Tunable placement and AR session values (SPEC §8, §15).</summary>
    [CreateAssetMenu(fileName = "PlacementSettings", menuName = "AquiFuturo/Placement Settings")]
    public sealed class PlacementSettingsConfig : ScriptableObject
    {
        [Header("Adjustment")]
        [Tooltip("Minimum uniform scale multiplier from pinch gesture.")]
        public float scaleMin = 0.5f;

        [Tooltip("Maximum uniform scale multiplier from pinch gesture.")]
        public float scaleMax = 2.0f;

        [Header("Root System Position")]
        [Tooltip("Vertical offset applied to the root system after placement. " +
                 "Negative values move it below the detected surface (into the ground). " +
                 "Tune this in PlacementSettings.asset.")]
        public float rootDepthOffsetM = 0f;

        [Header("Fallback Placement (SPEC §8.1)")]
        [Tooltip("Distance forward from camera when placing without a detected plane.")]
        public float fallbackDistanceM = 2.0f;

        [Tooltip("Assumed eye height used to project fallback placement to ground level.")]
        public float fallbackEyeHeightM = 1.4f;

        [Header("Tracking Loss (SPEC §8.3)")]
        [Tooltip("Seconds of lost tracking before muting the audio mix.")]
        public float trackingLossMuteSeconds = 3f;

        [Tooltip("Seconds over which the mix is ramped to silence on tracking loss.")]
        public float trackingLossRampSeconds = 1f;
    }
}
