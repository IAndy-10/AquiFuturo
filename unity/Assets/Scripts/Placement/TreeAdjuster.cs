using UnityEngine;
using AquiFuturo.Core;
using AquiFuturo.Placement;

namespace AquiFuturo.Placement
{
    /// <summary>
    /// Handles one-finger yaw rotation, pinch scale, and confirm gesture
    /// during the Adjusting state (SPEC §8.2).
    /// No allocations in Update.
    /// </summary>
    public sealed class TreeAdjuster : MonoBehaviour
    {
        [SerializeField] private PlacementSettingsConfig _config;
        [SerializeField] private GameManager _gameManager;
        [SerializeField] private TreePlacement _treePlacement;

        private GameObject _treeInstance;
        private Vector3 _baseScale;
        private float _prevPinchDist;

        /// <summary>Called by TreePlacement (or Unity wiring) to hand over the tree instance.</summary>
        public void SetTree(GameObject tree)
        {
            _treeInstance = tree;
            _baseScale    = tree != null ? tree.transform.localScale : Vector3.one;
            _prevPinchDist = -1f;
        }

        private void Update()
        {
            if (_gameManager == null || _gameManager.State != AppState.Adjusting) return;
            if (_treeInstance == null) return;

            int touchCount = Input.touchCount;

            if (touchCount == 1)
            {
                Touch t = Input.GetTouch(0);
                if (t.phase == TouchPhase.Moved)
                    ApplyYaw(t.deltaPosition.x);
                _prevPinchDist = -1f;
            }
            else if (touchCount >= 2)
            {
                ApplyPinchScale();
            }
            else
            {
                _prevPinchDist = -1f;
            }
        }

        private void ApplyYaw(float deltaX)
        {
            // 0.3 degrees per pixel — tunable via config if needed later.
            float degrees = deltaX * 0.3f;
            _treeInstance.transform.Rotate(Vector3.up, degrees, Space.World);
        }

        private void ApplyPinchScale()
        {
            Touch t0 = Input.GetTouch(0);
            Touch t1 = Input.GetTouch(1);

            float dist = Vector2.Distance(t0.position, t1.position);

            if (_prevPinchDist < 0f)
            {
                _prevPinchDist = dist;
                return;
            }

            float scaleMin = _config != null ? _config.scaleMin : 0.5f;
            float scaleMax = _config != null ? _config.scaleMax : 2.0f;

            float ratio = dist / Mathf.Max(_prevPinchDist, 0.001f);
            Vector3 newScale = _treeInstance.transform.localScale * ratio;

            // Clamp each axis relative to the authored base scale.
            float clampedX = Mathf.Clamp(newScale.x, _baseScale.x * scaleMin, _baseScale.x * scaleMax);
            float clampedY = Mathf.Clamp(newScale.y, _baseScale.y * scaleMin, _baseScale.y * scaleMax);
            float clampedZ = Mathf.Clamp(newScale.z, _baseScale.z * scaleMin, _baseScale.z * scaleMax);

            _treeInstance.transform.localScale = new Vector3(clampedX, clampedY, clampedZ);
            _prevPinchDist = dist;
        }
    }
}
