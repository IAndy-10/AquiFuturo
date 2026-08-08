using UnityEngine;
using AquiFuturo.Core;

namespace AquiFuturo.Audio
{
    /// <summary>
    /// Owns the four looping TrackChannels and applies all pose-driven modulations
    /// every frame (SPEC §9.1–§9.3). Responds to GameManager state changes for
    /// the intro gain ramp and tracking-loss mute.
    /// All modulation is 2D — no positional audio.
    /// No heap allocations in Update.
    /// </summary>
    public sealed class TrackMixer : MonoBehaviour
    {
        [SerializeField] private AudioSettingsConfig _audioConfig;
        [SerializeField] private PlacementSettingsConfig _placementConfig;
        [SerializeField] private PoseAnalyzer _poseAnalyzer;
        [SerializeField] private GameManager _gameManager;

        [Header("Tracks — must match manifest order: root_rave, soil, canopy, drone")]
        [SerializeField] private TrackChannel[] _tracks;

        private bool _started;

        // Tracking-loss mute ramp.
        private float _muteGain = 1f;  // linear [0,1]
        private float _muteGainVel;

        private void Awake()
        {
            if (_tracks == null || _tracks.Length != 4)
                Debug.LogError("[TrackMixer] Exactly 4 TrackChannel references required (SPEC §9.1).");
        }

        private void Start()
        {
            if (_audioConfig != null && _audioConfig.startImmediatelyForTesting)
            {
                Debug.Log("[TrackMixer] startImmediatelyForTesting enabled — starting audio now (M1 test mode).");
                StartScheduled();
            }
        }

        private void OnEnable()
        {
            if (_gameManager != null)
                _gameManager.OnStateChanged += HandleStateChanged;
        }

        private void OnDisable()
        {
            if (_gameManager != null)
                _gameManager.OnStateChanged -= HandleStateChanged;
        }

        private void Update()
        {
            if (!_started || _tracks == null || _audioConfig == null || _poseAnalyzer == null)
                return;

            // Tracking-loss mute ramp (SPEC §8.3).
            bool shouldMute = _gameManager != null && _gameManager.IsTrackingMuted;
            float rampTime = (_placementConfig != null)
                ? _placementConfig.trackingLossRampSeconds
                : 1f;
            _muteGain = Mathf.SmoothDamp(_muteGain, shouldMute ? 0f : 1f, ref _muteGainVel, rampTime);

            ApplyModulation();
        }

        // ── Public API ────────────────────────────────────────────────────

        /// <summary>
        /// Schedules all four tracks to start at the same DSP time (SPEC §9.2).
        /// The 0.2 s margin ensures dspTime is never in the past when this runs late.
        /// </summary>
        public void StartScheduled()
        {
            if (_tracks == null || _audioConfig == null) return;
            if (_started) return;

            double startTime = AudioSettings.dspTime + _audioConfig.scheduleMarginSeconds;

            foreach (var track in _tracks)
            {
                if (track == null || track.Source == null) continue;
                track.Source.PlayScheduled(startTime);
            }

            _started = true;
        }

        // ── Private ───────────────────────────────────────────────────────

        private void ApplyModulation()
        {
            float attention = _poseAnalyzer.Attention;
            float azimuthRad = _poseAnalyzer.Azimuth * Mathf.Deg2Rad;
            float tilt       = _poseAnalyzer.Tilt;
            float distance   = _poseAnalyzer.Distance;

            // Mapping 1 — Logarithmic LPF cutoff (SPEC §9.3). Never linear in Hz.
            float cutoffHz = _audioConfig.cutoffMinHz *
                Mathf.Pow(_audioConfig.cutoffMaxHz / _audioConfig.cutoffMinHz, attention);

            // Mapping 4 — Distance cutoff ceiling multiplicative cap.
            float ceiling = _audioConfig.distanceCutoffCeiling.Evaluate(distance);
            cutoffHz = Mathf.Min(cutoffHz, ceiling);

            // Mapping 2 — Azimuth → pan (sine form, SPEC §9.3).
            float panBase = Mathf.Sin(azimuthRad);

            // Mapping 4 — Distance master gain offset in dB.
            float distGainDb = _audioConfig.distanceGainDb.Evaluate(distance);

            for (int i = 0; i < _tracks.Length; i++)
            {
                TrackChannel ch = _tracks[i];
                if (ch == null || ch.Source == null) continue;

                ch.SetCutoffHz(cutoffHz);

                // Per-track pan width multiplier (SPEC §9.3 Mapping 2).
                float panWidth = (i < _audioConfig.panWidths.Length) ? _audioConfig.panWidths[i] : 1f;
                ch.SetPan(panBase * panWidth);

                // Mapping 3 — Tilt vertical layer balance (SPEC §9.3 Mapping 3).
                float tiltGainDb = _audioConfig.tiltGainRangeDb * (ch.TiltBias * -tilt);
                float totalDb = ch.BaseGainDb + tiltGainDb + distGainDb;
                totalDb = Mathf.Clamp(totalDb, _audioConfig.gainMinDb, _audioConfig.gainMaxDb);

                // Convert dB to linear, apply tracking-loss mute.
                float linearGain = Mathf.Pow(10f, totalDb / 20f) * _muteGain;
                ch.Source.volume = linearGain;
            }
        }

        private void HandleStateChanged(AppState prev, AppState next)
        {
            if (next == AppState.Adjusting)
            {
                // Tracks start here so the mix is already playing when the user confirms.
                // Attention will be low (looking around during adjustment), so the LPF
                // naturally closes — no separate gain fade needed.
                StartScheduled();
            }
        }
    }
}
