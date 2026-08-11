using UnityEngine;

namespace AquiFuturo.Core
{
    /// <summary>All tunable audio values (SPEC §9, §15). No magic numbers in code.</summary>
    [CreateAssetMenu(fileName = "AudioSettings", menuName = "AquiFuturo/Audio Settings")]
    public sealed class AudioSettingsConfig : ScriptableObject
    {
        [Header("Low-Pass Filter")]
        [Tooltip("Minimum cutoff frequency in Hz — fully occluded state.")]
        public float cutoffMinHz = 800f;

        [Tooltip("Maximum cutoff frequency in Hz — full attention state.")]
        public float cutoffMaxHz = 20000f;

        [Tooltip("LPF resonance Q. Keep at 1.0 to avoid drawing attention to the filter.")]
        public float resonanceQ = 1.0f;

        [Tooltip("Alignment value below which attention is clamped to 0.")]
        public float attentionLow = 0.2f;

        [Tooltip("Alignment value at which attention reaches 1.")]
        public float attentionHigh = 0.85f;

        [Header("Smooth Times (seconds)")]
        public float SmoothTime  = 0.50f;


        [Header("Tilt Gain")]
        [Tooltip("Maximum dB lift or cut from tilt modulation (SPEC §9.3 Mapping 3).")]
        public float tiltGainRangeDb = 6f;

        [Header("Distance Modulation (SPEC §9.3 Mapping 4)")]
        [Tooltip("X = distance in metres, Y = master gain offset in dB.")]
        public AnimationCurve distanceGainDb;

        [Tooltip("X = distance in metres, Y = additional cutoff ceiling in Hz.")]
        public AnimationCurve distanceCutoffCeiling;

        [Header("Gain Clamp")]
        public float gainMinDb = -24f;
        public float gainMaxDb =   0f;

        [Header("Startup")]
        [Tooltip("DSP scheduling margin in seconds (SPEC §9.2). Never set below 0.1.")]
        public double scheduleMarginSeconds = 0.2;

        [Tooltip("M1 testing only — start all four tracks immediately on app launch without requiring placement. " +
                 "Set to false before M3 audio tuning.")]
        public bool startImmediatelyForTesting = false;

        [Tooltip("Gain in dB during Adjusting state so the mix 'arrives' on confirm.")]
        public float adjustingGainDb = -12f;

        [Header("Interaction Pool")]
        [Tooltip("Number of pooled one-shot AudioSources (SPEC §9.4).")]
        public int poolSize = 12;

        [Tooltip("Maximum concurrent interaction sounds before stealing oldest.")]
        public int maxConcurrentInteractions = 6;

        private void Reset()
        {
            distanceGainDb = new AnimationCurve(
                new Keyframe(0f,  0f),
                new Keyframe(4f, -5f),
                new Keyframe(8f, -14f));

            distanceCutoffCeiling = new AnimationCurve(
                new Keyframe(0f,    20000f),
                new Keyframe(4f,    8000f),
                new Keyframe(8f,    3000f));
        }
    }
}
