using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;
using AquiFuturo.Core;
using AquiFuturo.Audio;
using AquiFuturo.Graph;

namespace AquiFuturo.Placement
{
    /// <summary>
    /// Handles AR plane detection, tap-to-place, and fallback placement (SPEC §8.1).
    /// Guards all AR Foundation subsystem access with null/enabled checks.
    /// Uses TryAddAnchorAsync (AR Foundation 6 API — AttachAnchor was removed).
    /// </summary>
    public sealed class TreePlacement : MonoBehaviour
    {
        [SerializeField] private PlacementSettingsConfig _config;
        [SerializeField] private GameManager _gameManager;
        [SerializeField] private PoseAnalyzer _poseAnalyzer;
        [SerializeField] private TreeAdjuster _treeAdjuster;
        [SerializeField] private RootMeshBuilder _rootMeshBuilder;
        [SerializeField] private GameObject _treePrefab;

        private ARRaycastManager _raycastManager;
        private ARPlaneManager _planeManager;
        private ARAnchorManager _anchorManager;
        private Camera _arCamera;

        private GameObject _treeInstance;
        private ARAnchor _treeAnchor;
        private bool _placed;
        private int _placementAttempts;
        private long _placementStartMs;

        // Allocated once — never inside Update.
        private readonly List<ARRaycastHit> _hits = new List<ARRaycastHit>();

        private void Awake()
        {
            _raycastManager = FindObjectOfType<ARRaycastManager>();
            _planeManager   = FindObjectOfType<ARPlaneManager>();
            _anchorManager  = FindObjectOfType<ARAnchorManager>();

            var arCamMgr = FindObjectOfType<ARCameraManager>();
            if (arCamMgr != null)
                _arCamera = arCamMgr.GetComponent<Camera>();

            if (_arCamera == null)
                _arCamera = Camera.main;

            _placementStartMs = System.DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        }

        private void OnEnable()
        {
            if (_planeManager != null)
                _planeManager.trackablesChanged.AddListener(OnPlanesChanged);
        }

        private void OnDisable()
        {
            if (_planeManager != null)
                _planeManager.trackablesChanged.RemoveListener(OnPlanesChanged);
        }

        private void Update()
        {
            if (_placed) return;

            AppState state = _gameManager != null ? _gameManager.State : AppState.Booting;
            if (state != AppState.Placing && state != AppState.PlacingFallback) return;
            if (Input.touchCount == 0) return;

            Touch touch = Input.GetTouch(0);
            if (touch.phase != TouchPhase.Began) return;

            if (state == AppState.Placing)
                TryPlaceOnPlane(touch.position);
            else
                PlaceFallback();
        }

        // ── Public API ────────────────────────────────────────────────────

        /// <summary>Confirms adjusted placement and transitions to Experiencing.</summary>
        public void ConfirmPlacement()
        {
            _gameManager?.OnPlacementConfirmed();
        }

        /// <summary>Destroys the current tree instance and resets placement state.</summary>
        public void ResetPlacement()
        {
            if (_treeInstance != null)
                Destroy(_treeInstance);

            if (_treeAnchor != null && _anchorManager != null && _anchorManager.enabled)
                Destroy(_treeAnchor.gameObject);

            _treeInstance = null;
            _treeAnchor   = null;
            _placed       = false;
            _placementAttempts = 0;

            _poseAnalyzer?.ClearTreeBase();
            _rootMeshBuilder?.ClearMesh();
            _gameManager?.ResetPlacement();
        }

        // ── Private ───────────────────────────────────────────────────────

        private void TryPlaceOnPlane(Vector2 screenPos)
        {
            if (_raycastManager == null || !_raycastManager.enabled)
            {
                Debug.LogWarning("[TreePlacement] ARRaycastManager unavailable — cannot raycast.");
                return;
            }

            _placementAttempts++;

            if (!_raycastManager.Raycast(screenPos, _hits, TrackableType.PlaneWithinPolygon)
                || _hits.Count == 0)
                return;

            ARRaycastHit bestHit = _hits[0];
            InstantiateTree(bestHit.pose, fallback: false);
            TryAddAnchorAsync(bestHit.pose);
        }

        private void PlaceFallback()
        {
            _placementAttempts++;
            if (_arCamera == null) return;

            float dist = _config != null ? _config.fallbackDistanceM   : 2f;
            float eyeH = _config != null ? _config.fallbackEyeHeightM  : 1.4f;

            Vector3 forward = _arCamera.transform.forward;
            forward.y = 0f;
            if (forward.sqrMagnitude < 0.001f) forward = Vector3.forward;
            forward.Normalize();

            Vector3 pos = _arCamera.transform.position + forward * dist;
            pos.y = _arCamera.transform.position.y - eyeH;

            Pose pose = new Pose(pos, Quaternion.LookRotation(forward, Vector3.up));
            InstantiateTree(pose, fallback: true);
            Debug.LogWarning("[TreePlacement] Fallback placement — no AR anchor attached.");
        }

        private void InstantiateTree(Pose pose, bool fallback)
        {
            _treeInstance = _treePrefab != null
                ? Instantiate(_treePrefab)
                : CreatePlaceholderCylinder();

            _treeInstance.transform.SetPositionAndRotation(pose.position, pose.rotation);
            _placed = true;

            _poseAnalyzer?.SetTreeBase(_treeInstance.transform);
            _treeAdjuster?.SetTree(_treeInstance);
            _rootMeshBuilder?.BuildMesh(_treeInstance.transform);
            _gameManager?.OnTreePlaced();

            long elapsed = System.DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - _placementStartMs;
            SessionLogger.Instance?.LogPlacementDone(_placementAttempts, elapsed, fallback);
        }

        /// <summary>
        /// Asynchronously attaches a world anchor to the placed tree (AR Foundation 6).
        /// AttachAnchor(ARPlane, Pose) was removed; TryAddAnchorAsync replaces it.
        /// SPEC §8.1: result is checked — null/failure logs a warning and uses no anchor.
        /// </summary>
        private async void TryAddAnchorAsync(Pose pose)
        {
            if (_anchorManager == null || !_anchorManager.enabled)
            {
                Debug.LogWarning("[TreePlacement] ARAnchorManager unavailable — no anchor attached.");
                return;
            }

            var result = await _anchorManager.TryAddAnchorAsync(pose);

            if (!result.status.IsSuccess())
            {
                Debug.LogWarning($"[TreePlacement] TryAddAnchorAsync failed: {result.status}. " +
                                 "Tree will drift without an anchor (SPEC §8.1).");
                return;
            }

            _treeAnchor = result.value;

            // Parent the tree to the anchor so ARKit world-tracking corrections propagate.
            if (_treeInstance != null && _treeAnchor != null)
                _treeInstance.transform.SetParent(_treeAnchor.transform, worldPositionStays: true);
        }

        private void OnPlanesChanged(ARTrackablesChangedEventArgs<ARPlane> args)
        {
            if (_placed || _gameManager == null) return;

            foreach (var plane in args.added)
            {
                if (PlaneQualifies(plane))
                {
                    _gameManager.OnPlaneDetected();
                    return;
                }
            }
        }

        private bool PlaneQualifies(ARPlane plane)
        {
            if (_config == null) return true;
            return plane.size.x * plane.size.y >= _config.minPlaneAreaSqM;
        }

        private static GameObject CreatePlaceholderCylinder()
        {
            // M1 placeholder when no tree prefab is assigned yet.
            var go = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            go.name = "TreePlaceholder";
            go.transform.localScale = new Vector3(0.1f, 1f, 0.1f);
            return go;
        }
    }
}
