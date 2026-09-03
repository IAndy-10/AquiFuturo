using UnityEngine;
using UnityEngine.XR.ARFoundation;
using AquiFuturo.Core;
using AquiFuturo.Audio;
using AquiFuturo.Graph;

namespace AquiFuturo.Placement
{
    /// <summary>
    /// Handles button-driven placement (SPEC §8.1).
    /// The user taps "Place roots" to call PlaceAndConfirm(), then can Reset() to re-place.
    /// No AR plane detection — position is derived from camera pose (fallback path only).
    /// </summary>
    public sealed class TreePlacement : MonoBehaviour
    {
        [SerializeField] private PlacementSettingsConfig _config;
        [SerializeField] private GameManager _gameManager;
        [SerializeField] private PoseAnalyzer _poseAnalyzer;
        [SerializeField] private TreeAdjuster _treeAdjuster;
        [SerializeField] private RootMeshBuilder _rootMeshBuilder;
        [SerializeField] private GameObject _treePrefab;

        private Camera _arCamera;
        private GameObject _treeInstance;
        private bool _placed;
        private int _placementAttempts;
        private long _placementStartMs;

        private void Awake()
        {
            var arCamMgr = FindObjectOfType<ARCameraManager>();
            if (arCamMgr != null)
                _arCamera = arCamMgr.GetComponent<Camera>();

            if (_arCamera == null)
                _arCamera = Camera.main;

            _placementStartMs = System.DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        }

        // ── Public API ────────────────────────────────────────────────────

        /// <summary>Confirms adjusted placement and transitions to Experiencing.</summary>
        public void ConfirmPlacement()
        {
            _gameManager?.OnPlacementConfirmed();
        }

        /// <summary>
        /// Places the root system at the camera forward position and immediately confirms.
        /// Called by the "Click to locate the roots" UI button (§8.1).
        /// </summary>
        public void PlaceAndConfirm()
        {
            if (_placed) return;
            AppState state = _gameManager != null ? _gameManager.State : AppState.Booting;
            if (state != AppState.Placing) return;

            PlaceFallback();
            _gameManager?.OnPlacementConfirmed();
        }

        /// <summary>Destroys the current tree instance and resets placement state.</summary>
        public void ResetPlacement()
        {
            if (_treeInstance != null)
                Destroy(_treeInstance);

            _treeInstance = null;
            _placed = false;
            _placementAttempts = 0;

            _poseAnalyzer?.ClearTreeBase();
            _rootMeshBuilder?.ClearMesh();
            _gameManager?.ResetPlacement();
        }

        // ── Private ───────────────────────────────────────────────────────

        private void PlaceFallback()
        {
            _placementAttempts++;
            if (_arCamera == null) return;

            float dist = _config != null ? _config.fallbackDistanceM  : 2f;
            float eyeH = _config != null ? _config.fallbackEyeHeightM : 1.4f;

            Vector3 forward = _arCamera.transform.forward;
            forward.y = 0f;
            if (forward.sqrMagnitude < 0.001f) forward = Vector3.forward;
            forward.Normalize();

            Vector3 pos = _arCamera.transform.position + forward * dist;
            pos.y = _arCamera.transform.position.y - eyeH;

            Pose pose = new Pose(pos, Quaternion.LookRotation(forward, Vector3.up));
            InstantiateTree(pose);
        }

        private void InstantiateTree(Pose pose)
        {
            _treeInstance = _treePrefab != null
                ? Instantiate(_treePrefab)
                : CreatePlaceholderCylinder();

            float depthOffset = _config != null ? _config.rootDepthOffsetM : 0f;
            Vector3 placedPos = pose.position + Vector3.up * depthOffset;
            _treeInstance.transform.SetPositionAndRotation(placedPos, pose.rotation);
            _placed = true;

            _poseAnalyzer?.SetTreeBase(_treeInstance.transform);
            _treeAdjuster?.SetTree(_treeInstance);
            _rootMeshBuilder?.BuildMesh(_treeInstance.transform);
            _gameManager?.OnTreePlaced();

            long elapsed = System.DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - _placementStartMs;
            SessionLogger.Instance?.LogPlacementDone(_placementAttempts, elapsed, fallback: true);
        }

        private static GameObject CreatePlaceholderCylinder()
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            go.name = "TreePlaceholder";
            go.transform.localScale = new Vector3(0.1f, 1f, 0.1f);
            return go;
        }
    }
}
