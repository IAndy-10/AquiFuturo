using UnityEngine;

namespace AquiFuturo.Interaction
{
    /// <summary>
    /// Pool of ParticleSystem instances for root-touch bursts (SPEC §11).
    /// 8 pooled instances; world simulation space; no physics.
    /// </summary>
    public sealed class ParticleSpawner : MonoBehaviour
    {
        [SerializeField] private ParticleSystem _particlePrefab;
        [SerializeField] private int _poolSize = 8;

        private ParticleSystem[] _pool;
        private int _nextSlot;

        private void Awake()
        {
            if (_particlePrefab == null)
            {
                Debug.LogWarning("[ParticleSpawner] No particle prefab assigned — sparks disabled.");
                return;
            }

            _pool = new ParticleSystem[_poolSize];
            for (int i = 0; i < _poolSize; i++)
            {
                var ps = Instantiate(_particlePrefab, transform);
                ps.gameObject.SetActive(false);
                ps.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
                _pool[i] = ps;
            }
        }

        /// <summary>Plays a burst at worldPosition, facing along surfaceNormal.</summary>
        public void Burst(Vector3 worldPosition, Vector3 surfaceNormal)
        {
            if (_pool == null) return;

            ParticleSystem ps = _pool[_nextSlot % _poolSize];
            _nextSlot++;

            ps.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
            ps.gameObject.SetActive(true);
            ps.transform.SetPositionAndRotation(
                worldPosition,
                Quaternion.LookRotation(surfaceNormal, Vector3.up));
            ps.Play();
        }
    }
}
