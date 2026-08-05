using UnityEngine;
using UnityEngine.XR.ARFoundation;

namespace AquiFuturo.Audio
{
    /// <summary>
    /// Computes the four pose axes used to drive the audio mix (SPEC §9.3).
    /// Azimuth, alignment, tilt, and distance are all SmoothDamped before use.
    /// Lives on the Bootstrap GameObject.
    /// </summary>
    public sealed class PoseAnalyzer : MonoBehaviour
    {
        [SerializeField] private AquiFuturo.Core.AudioSettingsConfig _config;

        // Smoothed output values — read by TrackMixer every frame.
        public float Azimuth   { get; private set; }
        public float Alignment { get; private set; }
        public float Tilt      { get; private set; }
        public float Distance  { get; private set; }

        // Derived value consumed by TrackMixer for the LPF mapping.
        public float Attention { get; private set; }

        private Transform _cameraTransform;
        private Transform _treeBase;   // set by TreePlacement after placement

        // SmoothDamp velocity refs — must be stored fields, not locals (SPEC csharp-unity §HIGH).
        private float _azimuthVel;
        private float _alignmentVel;
        private float _tiltVel;
        private float _distanceVel;

        // Pose logging at 2 Hz.
        private float _poseLogTimer;
        private const float PoseLogInterval = 0.5f;

        private void Awake()
        {
            // Cache camera once — do not use Camera.main in Update.
            var arCameraManager = FindObjectOfType<ARCameraManager>();
            if (arCameraManager != null)
                _cameraTransform = arCameraManager.transform;
            else
                Debug.LogWarning("[PoseAnalyzer] ARCameraManager not found — pose axes will be zero.");
        }

        private void Update()
        {
            if (_cameraTransform == null) return;

            ComputeRawAxes(out float rawAz, out float rawAlign, out float rawTilt, out float rawDist);

            float smooth = _config != null ? _config.azimuthSmoothTime   : 0.2f;
            Azimuth   = Mathf.SmoothDamp(Azimuth,   rawAz,    ref _azimuthVel,   smooth);

            smooth = _config != null ? _config.alignmentSmoothTime : 0.35f;
            Alignment = Mathf.SmoothDamp(Alignment, rawAlign, ref _alignmentVel, smooth);

            smooth = _config != null ? _config.tiltSmoothTime : 0.3f;
            Tilt      = Mathf.SmoothDamp(Tilt,      rawTilt,  ref _tiltVel,      smooth);

            smooth = _config != null ? _config.distanceSmoothTime : 0.5f;
            Distance  = Mathf.SmoothDamp(Distance,  rawDist,  ref _distanceVel,  smooth);

            Attention = ComputeAttention(Alignment);

            _poseLogTimer += Time.deltaTime;
            if (_poseLogTimer >= PoseLogInterval)
            {
                _poseLogTimer = 0f;
                Core.SessionLogger.Instance?.LogPose(Azimuth, Alignment, Tilt, Distance);
            }
        }

        /// <summary>Called by TreePlacement once the tree is anchored.</summary>
        public void SetTreeBase(Transform treeBase)
        {
            _treeBase = treeBase;
        }

        /// <summary>Clears the tree reference when placement is reset.</summary>
        public void ClearTreeBase()
        {
            _treeBase = null;
        }

        // ── Private ───────────────────────────────────────────────────────

        private void ComputeRawAxes(
            out float azimuth, out float alignment, out float tilt, out float distance)
        {
            if (_treeBase == null)
            {
                azimuth = alignment = tilt = distance = 0f;
                tilt = _cameraTransform.forward.y; // tilt is always meaningful
                return;
            }

            Vector3 camPos     = _cameraTransform.position;
            Vector3 camForward = _cameraTransform.forward;
            Vector3 treePos    = _treeBase.position;

            // Azimuth: signed XZ angle from camera forward to tree direction (SPEC §9.3).
            Vector3 toTree = treePos - camPos;
            Vector3 toTreeXZ = new Vector3(toTree.x, 0f, toTree.z);
            Vector3 camFwdXZ = new Vector3(camForward.x, 0f, camForward.z);

            azimuth = toTreeXZ.sqrMagnitude > 0.0001f
                ? Vector3.SignedAngle(camFwdXZ.normalized, toTreeXZ.normalized, Vector3.up)
                : 0f;

            // Alignment: dot of camera forward with direction to root centroid.
            // Using treeBase as a proxy; RootInteraction can set a better centroid later.
            alignment = toTree.sqrMagnitude > 0.0001f
                ? Vector3.Dot(camForward, toTree.normalized)
                : 0f;

            // Tilt: camera forward Y component.
            tilt = camForward.y;

            // Distance: horizontal distance to tree base.
            distance = toTreeXZ.magnitude;
        }

        private float ComputeAttention(float align)
        {
            if (_config == null) return 0f;
            float t = Mathf.InverseLerp(_config.attentionLow, _config.attentionHigh, align);
            return Mathf.Clamp01(t);
        }
    }
}
