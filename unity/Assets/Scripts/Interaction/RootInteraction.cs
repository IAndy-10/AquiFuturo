using System.Collections.Generic;
using UnityEngine;
using AquiFuturo.Core;
using AquiFuturo.Graph;
using AquiFuturo.Audio;

namespace AquiFuturo.Interaction
{
    /// <summary>
    /// Handles touch-to-root interactions (SPEC §10).
    /// Raycasts against the RootMesh layer only.
    /// Resolves nearest graph node via SpatialHash — no linear scan per touch.
    /// Fires one-shot audio and a particle burst.
    /// Spatial hash is read from RootGraphLoader (built in Start, not lazily).
    /// </summary>
    public sealed class RootInteraction : MonoBehaviour
    {
        [SerializeField] private InteractionSettingsConfig _config;
        [SerializeField] private GameManager _gameManager;
        [SerializeField] private RootGraphLoader _graphLoader;
        [SerializeField] private InteractionAudioPool _audioPool;
        [SerializeField] private ParticleSpawner _particleSpawner;
        [SerializeField] private PoseAnalyzer _poseAnalyzer;

        // Layer mask set to RootMesh only — never raycast against Default (SPEC §2.2).
        private int _rootMeshLayerMask;
        private Camera _arCamera;

        // Debounce: tracks last touch time per node id.
        private readonly Dictionary<int, float> _lastTouchTime = new Dictionary<int, float>();

        private void Awake()
        {
            _rootMeshLayerMask = LayerMask.GetMask("RootMesh");
            if (_rootMeshLayerMask == 0)
                Debug.LogWarning("[RootInteraction] 'RootMesh' layer not found. " +
                                 "Create it in Project Settings → Tags & Layers (SPEC §2.2).");

            var arCamMgr = FindObjectOfType<UnityEngine.XR.ARFoundation.ARCameraManager>();
            _arCamera = arCamMgr != null ? arCamMgr.GetComponent<Camera>() : Camera.main;
        }

        private void Update()
        {
            if (_gameManager == null || _gameManager.State != AppState.Experiencing) return;
            if (_arCamera == null) return;
            if (Input.touchCount == 0) return;

            Touch touch = Input.GetTouch(0);
            if (touch.phase != TouchPhase.Began) return;

            HandleTouch(touch.position);
        }

        // ── Private ───────────────────────────────────────────────────────

        private void HandleTouch(Vector2 screenPos)
        {
            float maxDist = _config != null ? _config.raycastDistanceM : 10f;
            Ray ray = _arCamera.ScreenPointToRay(screenPos);

            if (!Physics.Raycast(ray, out RaycastHit hit, maxDist, _rootMeshLayerMask))
                return;

            if (_graphLoader == null || !_graphLoader.IsLoaded) return;

            RootNode node = _graphLoader.SpatialHash.NearestTo(hit.point);
            if (node == null) return;

            // Debounce per node (SPEC §10).
            float debounceSeconds = _config != null ? _config.debounceMs / 1000f : 0.12f;
            if (_lastTouchTime.TryGetValue(node.Id, out float last) &&
                Time.time - last < debounceSeconds)
                return;

            _lastTouchTime[node.Id] = Time.time;

            // Pan the one-shot toward the touch azimuth (SPEC §9.4).
            float panValue = _poseAnalyzer != null
                ? Mathf.Sin(_poseAnalyzer.Azimuth * Mathf.Deg2Rad)
                : 0f;

            float pitchVar = _config != null ? _config.pitchVarSemitones : 2f;
            _audioPool?.Play(node.Class, panValue, pitchVar);
            _particleSpawner?.Burst(hit.point, hit.normal);
            SessionLogger.Instance?.LogRootTouch(node.Id, node.Class,
                Vector3.Distance(_arCamera.transform.position, hit.point));
        }
    }
}
