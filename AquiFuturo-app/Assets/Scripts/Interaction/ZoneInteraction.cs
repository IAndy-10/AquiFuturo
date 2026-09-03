using UnityEngine;
using UnityEngine.XR.ARFoundation;
using AquiFuturo.Core;

namespace AquiFuturo.Interaction
{
    /// <summary>
    /// Handles tap-to-zone interaction for the four spatial Box Collider zones.
    /// Raycasts from the AR camera through the touch point against the zone layer
    /// and fires the ZoneTrigger on whichever collider is hit.
    ///
    /// Setup: assign all four zone GameObjects to a dedicated Unity layer
    /// (e.g. "InteractionZone") and point _zoneMask at that layer.
    /// </summary>
    public sealed class ZoneInteraction : MonoBehaviour
    {
        [SerializeField] private GameManager _gameManager;
        [SerializeField] private InteractionSettingsConfig _config;

        [Tooltip("Layer mask covering only the four zone Box Colliders.")]
        [SerializeField] private LayerMask _zoneMask;

        [Tooltip("Bypass AppState guard for in-editor testing. Disable before field sessions.")]
        [SerializeField] private bool _startImmediatelyForTesting = false;

        [Tooltip("Max raycast distance in metres.")]
        [SerializeField] private float _raycastDistance = 50f;

        private Camera _arCamera;
        private float  _lastTriggerTime = -999f;

        private void Awake()
        {
            var arCamMgr = FindObjectOfType<ARCameraManager>();
            _arCamera = arCamMgr != null
                ? arCamMgr.GetComponent<Camera>()
                : Camera.main;

            if (_arCamera == null)
                Debug.LogWarning("[ZoneInteraction] AR camera not found - zone taps will not work.");
        }

        private void Update()
        {
            if (!_startImmediatelyForTesting &&
                (_gameManager == null || _gameManager.State != AppState.Experiencing)) return;
            if (_arCamera == null) return;
            if (Input.touchCount == 0) return;

            Touch touch = Input.GetTouch(0);
            if (touch.phase != TouchPhase.Began) return;

            float debounce = _config != null ? _config.debounceMs / 1000f : 0.12f;
            if (Time.time - _lastTriggerTime < debounce) return;

            HandleTouch(touch.position);
        }

        private void HandleTouch(Vector2 touchPos)
        {
            Ray ray = _arCamera.ScreenPointToRay(touchPos);
            if (!Physics.Raycast(ray, out RaycastHit hit, _raycastDistance, _zoneMask))
                return;

            var trigger = hit.collider.GetComponent<ZoneTrigger>();
            if (trigger == null)
            {
                Debug.LogWarning("[ZoneInteraction] Hit a zone collider with no ZoneTrigger component.");
                return;
            }

            // Pan from normalised screen X: left edge = -1, right edge = +1.
            float pan = (touchPos.x / Screen.width) * 2f - 1f;

            trigger.Play(pan);
            _lastTriggerTime = Time.time;
        }
    }
}
