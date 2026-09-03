using UnityEngine;
using AquiFuturo.Core;

namespace AquiFuturo.Interaction
{
    /// <summary>
    /// Attached to each interaction zone Box Collider.
    /// Requires an AudioSource on the same GameObject — wire the clip and set
    /// Volume there. ZoneInteraction calls Play() when a tap ray hits this zone.
    ///
    /// Box Collider must NOT have "Is Trigger" enabled — Physics.Raycast skips triggers.
    /// </summary>
    [RequireComponent(typeof(BoxCollider))]
    [RequireComponent(typeof(AudioSource))]
    public sealed class ZoneTrigger : MonoBehaviour
    {
        [SerializeField] private int _zoneId;
        [SerializeField] private InteractionSettingsConfig _config;

        private AudioSource _source;

        /// <summary>Zone identifier (1-4), used for logging.</summary>
        public int ZoneId => _zoneId;

        private void Awake()
        {
            _source              = GetComponent<AudioSource>();
            _source.spatialBlend = 0f;   // 2D — SPEC §9.1
            _source.playOnAwake  = false;
            _source.loop         = false;
        }

        /// <summary>Plays the zone clip panned to pan (-1 left, +1 right).</summary>
        public void Play(float pan)
        {
            if (_source.clip == null)
            {
                Debug.LogWarning($"[ZoneTrigger] Zone {_zoneId}: AudioSource has no clip assigned.");
                return;
            }
            _source.panStereo = Mathf.Clamp(pan, -1f, 1f);

            float gainDb = _config != null ? _config.interactionGainDb : -12f;
            _source.volume = Mathf.Pow(10f, gainDb / 20f);

            _source.Stop();
            _source.Play();
            Debug.Log($"[ZoneTrigger] Zone {_zoneId} triggered — pan={pan:F2} gain={gainDb:F1} dB");
        }
    }
}
