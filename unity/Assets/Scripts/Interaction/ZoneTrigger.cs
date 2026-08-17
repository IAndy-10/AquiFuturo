using UnityEngine;

namespace AquiFuturo.Interaction
{
    /// <summary>
    /// Attached to each interaction zone Box Collider.
    /// Holds the one-shot AudioClip for this zone and plays it on demand.
    /// The AudioSource is created at runtime — no scene-side source needed.
    /// </summary>
    [RequireComponent(typeof(BoxCollider))]
    public sealed class ZoneTrigger : MonoBehaviour
    {
        [SerializeField] private int _zoneId;

        [Tooltip("One-shot clip played when this zone is tapped (e.g. rave_zone1.wav).")]
        [SerializeField] private AudioClip _clip;

        private AudioSource _source;

        /// <summary>Zone identifier (1-4), used for logging.</summary>
        public int ZoneId => _zoneId;

        private void Awake()
        {
            var vo = new GameObject("ZoneVoice");
            vo.transform.SetParent(transform);
            _source              = vo.AddComponent<AudioSource>();
            _source.spatialBlend = 0f;   // 2D - SPEC 9.1
            _source.playOnAwake  = false;
            _source.clip         = _clip;
        }

        /// <summary>Plays the zone clip panned to pan (-1 left, +1 right).</summary>
        public void Play(float pan)
        {
            if (_clip == null)
            {
                Debug.LogWarning($"[ZoneTrigger] Zone {_zoneId} has no clip assigned.");
                return;
            }
            _source.panStereo = Mathf.Clamp(pan, -1f, 1f);
            _source.Stop();
            _source.Play();
            Debug.Log($"[ZoneTrigger] Zone {_zoneId} triggered - pan={pan:F2}");
        }
    }
}
