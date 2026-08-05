using System.Collections.Generic;
using UnityEngine;
using AquiFuturo.Core;

namespace AquiFuturo.Interaction
{
    /// <summary>
    /// Pool of 2D AudioSources for interaction one-shots (SPEC §9.4).
    /// Pool size and max-concurrent are driven by AudioSettingsConfig.
    /// Oldest voice is stolen when the pool is exhausted.
    /// </summary>
    public sealed class InteractionAudioPool : MonoBehaviour
    {
        [SerializeField] private AudioSettingsConfig _config;

        // Clip banks keyed by node class.
        [System.Serializable]
        public struct ClassClips
        {
            public string      nodeClass;
            public AudioClip[] clips;
        }

        [SerializeField] private ClassClips[] _classBanks;

        private AudioSource[] _pool;
        private int           _nextSlot;
        private int           _activeCount;

        private void Awake()
        {
            int size = _config != null ? _config.poolSize : 12;
            _pool = new AudioSource[size];

            for (int i = 0; i < size; i++)
            {
                var go = new GameObject($"InteractionVoice_{i}");
                go.transform.SetParent(transform);
                var src = go.AddComponent<AudioSource>();
                src.spatialBlend = 0f;   // 2D — same rule as tracks (SPEC §9.1)
                src.playOnAwake  = false;
                _pool[i] = src;
            }
        }

        /// <summary>
        /// Plays a random clip matching nodeClass, panned to panValue.
        /// Random pitch within ±pitchVarSemitones.
        /// </summary>
        public void Play(string nodeClass, float panValue, float pitchVarSemitones)
        {
            AudioClip clip = PickClip(nodeClass);
            if (clip == null)
            {
                Debug.LogWarning($"[InteractionAudioPool] No clips for class '{nodeClass}'.");
                return;
            }

            int maxConcurrent = _config != null ? _config.maxConcurrentInteractions : 6;
            AudioSource src = AcquireVoice(maxConcurrent);
            if (src == null) return;

            src.clip       = clip;
            src.panStereo  = Mathf.Clamp(panValue, -1f, 1f);
            src.pitch      = SemitonesToPitch(Random.Range(-pitchVarSemitones, pitchVarSemitones));
            src.Play();
        }

        // ── Private ───────────────────────────────────────────────────────

        private AudioSource AcquireVoice(int maxConcurrent)
        {
            // Steal oldest if at max concurrent.
            if (_activeCount >= maxConcurrent)
            {
                var oldest = OldestActive();
                oldest?.Stop();
                return oldest;
            }

            // Find first idle slot.
            for (int i = 0; i < _pool.Length; i++)
            {
                if (!_pool[i].isPlaying)
                {
                    _activeCount++;
                    return _pool[i];
                }
            }

            // Fallback: steal next in round-robin.
            var stolen = _pool[_nextSlot % _pool.Length];
            _nextSlot++;
            stolen.Stop();
            return stolen;
        }

        private AudioSource OldestActive()
        {
            // Simple heuristic: return the pool voice with the smallest time offset.
            AudioSource oldest = null;
            float minTime = float.MaxValue;
            foreach (var src in _pool)
            {
                if (src.isPlaying && src.time < minTime)
                {
                    minTime = src.time;
                    oldest  = src;
                }
            }
            return oldest;
        }

        private AudioClip PickClip(string nodeClass)
        {
            if (_classBanks == null) return null;
            foreach (var bank in _classBanks)
            {
                if (bank.nodeClass == nodeClass && bank.clips != null && bank.clips.Length > 0)
                    return bank.clips[Random.Range(0, bank.clips.Length)];
            }
            return null;
        }

        private static float SemitonesToPitch(float semitones)
        {
            return Mathf.Pow(2f, semitones / 12f);
        }
    }
}
