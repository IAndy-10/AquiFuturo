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
    ///
    /// One track is marked IsStatic on its TrackChannel (the drone/foundation layer).
    /// It receives only base gain + tracking-loss mute — no LPF, no pan, no tilt.
    /// The other three tracks receive all four mappings, each with individual
    /// LpfSensitivity and PanWidth so their spatial and timbral behaviour is distinct.
    /// Spatial (pan) is the primary expressive axis.
    /// </summary>
    public sealed class TrackMixer : MonoBehaviour
    {
        [SerializeField] private AudioSettingsConfig _audioConfig;
        [SerializeField] private PlacementSettingsConfig _placementConfig;
        [SerializeField] private PoseAnalyzer _poseAnalyzer;
        [SerializeField] private GameManager _gameManager;

        [Header("Tracks — order in array does not affect modulation (each track owns its config)")]
        [SerializeField] private TrackChannel[] _tracks;

        private bool _started;

        // Tracking-loss mute ramp.
        private float _muteGain = 1f;  // linear [0, 1]
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
            float attention  = _poseAnalyzer.Attention;
            float azimuthRad = _poseAnalyzer.Azimuth * Mathf.Deg2Rad;
            float tilt       = _poseAnalyzer.Tilt;
            float distance   = _poseAnalyzer.Distance;

            // Spatial base — sine of azimuth maps cleanly to [-1, 1] pan range.
            // Per-track PanWidth is applied below; this is the shared direction signal.
            float panBase = Mathf.Sin(azimuthRad);

            // Distance gain offset in dB — shared across all active tracks (Mapping 4).
            float distGainDb = _audioConfig.distanceGainDb.Evaluate(distance);

            // Distance LPF ceiling — upper bound on cutoff regardless of attention (Mapping 4).
            float distCeiling = _audioConfig.distanceCutoffCeiling.Evaluate(distance);

            for (int i = 0; i < _tracks.Length; i++)
            {
                TrackChannel ch = _tracks[i];
                if (ch == null || ch.Source == null) continue;

                if (ch.IsStatic)
                {
                    // Static track (drone/foundation): fully open filter, centred pan,
                    // base gain only. Provides a stable anchor while the other three move.
                    ch.SetCutoffHz(_audioConfig.cutoffMaxHz);
                    ch.SetPan(0f);
                    float staticDb     = Mathf.Clamp(ch.BaseGainDb, _audioConfig.gainMinDb, _audioConfig.gainMaxDb);
                    ch.Source.volume   = Mathf.Pow(10f, staticDb / 20f) * _muteGain;
                    continue;
                }

                // ── Active track — all four mappings ──────────────────────

                // Mapping 1: logarithmic LPF (SPEC §9.3). Per-track LpfSensitivity scales
                // how deeply attention drives the filter on this track. Never linear in Hz.
                float effectiveAttention = attention * ch.LpfSensitivity;
                float cutoffHz = _audioConfig.cutoffMinHz *
                    Mathf.Pow(_audioConfig.cutoffMaxHz / _audioConfig.cutoffMinHz, effectiveAttention);
                cutoffHz = Mathf.Min(cutoffHz, distCeiling);
                ch.SetCutoffHz(cutoffHz);

                // Mapping 2: spatial pan — primary expressive axis.
                // PanWidth is an intrinsic property of the track, set in its Inspector.
                ch.SetPan(panBase * ch.PanWidth);

                // Mapping 3: tilt → vertical layer balance.
                // TiltBias +1 = canopy (louder when phone points up, tilt > 0).
                // TiltBias -1 = underground (louder when phone points down, tilt < 0).
                float tiltGainDb = _audioConfig.tiltGainRangeDb * (ch.TiltBias * tilt);

                // Mapping 4: sum base + tilt + distance, clamp, convert, mute.
                float totalDb    = ch.BaseGainDb + tiltGainDb + distGainDb;
                totalDb          = Mathf.Clamp(totalDb, _audioConfig.gainMinDb, _audioConfig.gainMaxDb);
                ch.Source.volume = Mathf.Pow(10f, totalDb / 20f) * _muteGain;
            }
        }

        private void OnApplicationPause(bool paused)
        {
            // iOS suspends audio output on background. On resume, reschedule any
            // tracks that stopped so the mix continues without requiring a restart.
            if (paused || !_started || _tracks == null || _audioConfig == null) return;

            foreach (var track in _tracks)
            {
                if (track?.Source == null || track.Source.isPlaying) continue;
                track.Source.PlayScheduled(AudioSettings.dspTime + _audioConfig.scheduleMarginSeconds);
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
