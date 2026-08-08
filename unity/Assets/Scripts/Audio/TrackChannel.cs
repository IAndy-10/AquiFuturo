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

        [Tooltip("Tilt bias. -1 = underground (louder when phone points down), " +
                 "+1 = canopy (louder when phone points up), 0 = neutral.")]
        [SerializeField] private float _tiltBias = 0f;

        [Header("Modulation")]
        [Tooltip("When true, this track is static — LPF stays fully open, pan stays centred, " +
                 "only base gain + tracking-loss mute are applied. Use for the drone/foundation layer.")]
        [SerializeField] private bool _isStatic = false;

        [Tooltip("How strongly attention drives the LPF on this track. " +
                 "1 = full 800–20 kHz range, 0.5 = 800–4 kHz range, 0 = always at cutoffMinHz.")]
        [Range(0f, 1f)]
        [SerializeField] private float _lpfSensitivity = 1f;

        [Tooltip("Stereo pan width for this track. 1 = full ±1 range, 0 = always centred. " +
                 "Spatial is the primary expressive axis — set deliberately per track.")]
        [Range(0f, 1f)]
        [SerializeField] private float _panWidth = 1f;

        // Cached component references — never call GetComponent in Update.
        private AudioSource _source;
        private AudioLowPassFilter _lpf;

        public string TrackId      => _trackId;
        public AudioSource Source  => _source;
        public float BaseGainDb    => _baseGainDb;
        public float TiltBias      => _tiltBias;
        public bool  IsStatic      => _isStatic;
        public float LpfSensitivity => _lpfSensitivity;
        public float PanWidth      => _panWidth;

        private void Awake()
        {
            _source = GetComponent<AudioSource>();
            _lpf    = GetComponent<AudioLowPassFilter>();

            // SPEC §9.1 — 2D sources only. This must not be changed.
            _source.spatialBlend = 0f;
            _source.loop         = true;
            _source.playOnAwake  = false;
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
    }
}
