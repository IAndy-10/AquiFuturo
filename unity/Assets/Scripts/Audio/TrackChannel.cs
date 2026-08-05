using UnityEngine;

namespace AquiFuturo.Audio
{
    /// <summary>
    /// Wraps a single looping AudioSource + AudioLowPassFilter (SPEC §9.1).
    /// spatialBlend is forced to 0 on Awake. All modulation is applied per-frame
    /// by TrackMixer — this class only exposes the setters.
    /// No heap allocations. All component refs cached in Awake.
    /// </summary>
    [RequireComponent(typeof(AudioSource))]
    [RequireComponent(typeof(AudioLowPassFilter))]
    public sealed class TrackChannel : MonoBehaviour
    {
        [Header("Manifest Fields")]
        [Tooltip("Must match the 'id' field in audio_manifest.json.")]
        [SerializeField] private string _trackId;

        [Tooltip("Base gain in dB from audio_manifest.json.")]
        [SerializeField] private float _baseGainDb = -6f;

        [Tooltip("Tilt bias from audio_manifest.json. -1 = underground, +1 = canopy, 0 = neutral.")]
        [SerializeField] private float _tiltBias = 0f;

        [Tooltip("Index into AudioSettingsConfig.panWidths (0=root_rave,1=soil,2=canopy,3=drone).")]
        [SerializeField] private int _panWidthIndex = 0;

        // Cached component references — never call GetComponent in Update.
        private AudioSource _source;
        private AudioLowPassFilter _lpf;

        public string TrackId => _trackId;

        /// <summary>The underlying AudioSource. TrackMixer calls PlayScheduled on it directly.</summary>
        public AudioSource Source => _source;

        /// <summary>Base gain in dB as loaded from the manifest.</summary>
        public float BaseGainDb => _baseGainDb;

        /// <summary>Tilt bias [-1, 1] from the manifest.</summary>
        public float TiltBias => _tiltBias;

        /// <summary>Index into AudioSettingsConfig.panWidths.</summary>
        public int PanWidthIndex => _panWidthIndex;

        private void Awake()
        {
            _source = GetComponent<AudioSource>();
            _lpf    = GetComponent<AudioLowPassFilter>();

            // SPEC §9.1 — 2D sources only. This must not be changed.
            _source.spatialBlend  = 0f;
            _source.loop          = true;
            _source.playOnAwake   = false;
        }

        /// <summary>Sets the low-pass cutoff frequency in Hz.</summary>
        public void SetCutoffHz(float hz)
        {
            if (_lpf == null) return;
            _lpf.cutoffFrequency = hz;
        }

        /// <summary>Sets stereo pan. -1 = full left, 0 = centre, +1 = full right.</summary>
        public void SetPan(float pan)
        {
            if (_source == null) return;
            _source.panStereo = Mathf.Clamp(pan, -1f, 1f);
        }

        /// <summary>Sets the AudioSource volume from a dB value. Clamps to [gainMinDb, gainMaxDb].</summary>
        public void SetGainDb(float db, float gainMinDb, float gainMaxDb)
        {
            if (_source == null) return;
            float clamped = Mathf.Clamp(db, gainMinDb, gainMaxDb);
            _source.volume = Mathf.Pow(10f, clamped / 20f);
        }
    }
}
