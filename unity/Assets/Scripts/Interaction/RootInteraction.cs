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

        private Camera _arCamera;

        // Debounce: tracks last touch time per node id.
        private readonly Dictionary<int, float> _lastTouchTime = new Dictionary<int, float>();

        private void Awake()
        {
            var arCamMgr = FindObjectOfType<UnityEngine.XR.ARFoundation.ARCameraManager>();
            _arCamera = arCamMgr != null ? arCamMgr.GetComponent<Camera>() : Camera.main;
            if (_arCamera == null)
                Debug.LogWarning("[RootInteraction] AR camera not found — touch will not work.");
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

        private void HandleTouch(Vector2 touchPos)
        {
            if (_graphLoader == null || !_graphLoader.IsLoaded) return;

            float radiusPx = _config != null ? _config.screenSpaceTapRadiusPx : 80f;

            Debug.Log($"[RootInteraction] Touch {touchPos} screenRadiusPx={radiusPx}");

            RootNode node = FindNearestNodeInScreen(touchPos, radiusPx);
            if (node == null)
            {
                Debug.Log("[RootInteraction] No node within tap radius.");
                return;
            }

            Debug.Log($"[RootInteraction] Node id={node.Id} class={node.Class}");

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

            Vector3 nodeWorld = _graphLoader.NodeWorldPosition(node);
            _particleSpawner?.Burst(nodeWorld, Vector3.up);
            SessionLogger.Instance?.LogRootTouch(node.Id, node.Class,
                Vector3.Distance(_arCamera.transform.position, nodeWorld));
        }

        /// <summary>
        /// Finds the graph node whose screen-projected position is nearest to
        /// <paramref name="touchPos"/> within <paramref name="radiusPx"/> pixels.
        /// No physics colliders required.
        /// </summary>
        private RootNode FindNearestNodeInScreen(Vector2 touchPos, float radiusPx)
        {
            RootNode best       = null;
            float    bestDistSq = radiusPx * radiusPx;

            foreach (RootNode node in _graphLoader.Graph.Nodes)
            {
                Vector3 world  = _graphLoader.NodeWorldPosition(node);
                Vector3 screen = _arCamera.WorldToScreenPoint(world);

                if (screen.z < 0f) continue;   // behind the camera

                float dx     = screen.x - touchPos.x;
                float dy     = screen.y - touchPos.y;
                float distSq = dx * dx + dy * dy;

                if (distSq < bestDistSq) { bestDistSq = distSq; best = node; }
            }

            return best;
        }
    }
}
