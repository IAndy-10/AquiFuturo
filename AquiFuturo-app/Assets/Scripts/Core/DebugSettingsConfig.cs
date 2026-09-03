using UnityEngine;

namespace AquiFuturo.Core
{
    /// <summary>Debug and diagnostic settings (SPEC §15). Build the pose readout — tuning 4 axes by ear is not viable.</summary>
    [CreateAssetMenu(fileName = "DebugSettings", menuName = "AquiFuturo/Debug Settings")]
    public sealed class DebugSettingsConfig : ScriptableObject
    {
        [Tooltip("Show on-screen readout of the four pose axes.")]
        public bool showPoseReadout = true;

        [Tooltip("Draw gizmos for root graph nodes in the Scene view.")]
        public bool showGraphGizmos = true;

        [Tooltip("Diagnostic logging verbosity.")]
        public Verbosity verbosity = Verbosity.Info;

        public enum Verbosity { Silent, Info, Verbose }
    }
}
