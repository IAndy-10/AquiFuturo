using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.XR.ARFoundation;

namespace AquiFuturo.Placement
{
    /// <summary>
    /// Applies ARKit light estimation data to the scene's Directional Light each frame (SPEC §8).
    /// Reads averageBrightness, colorTemperature, mainLightDirection, mainLightColor,
    /// and ambientSphericalHarmonics from ARCameraManager.frameReceived.
    /// Requests all individual light estimation flags (AR Foundation 6 replaced the
    /// EnvironmentalHDR shorthand with per-feature flags). Falls back gracefully to
    /// ambient-only on older devices that don't support directional estimation.
    /// </summary>
    public sealed class ARLightEstimation : MonoBehaviour
    {
        [SerializeField] private ARCameraManager _cameraManager;
        [SerializeField] private Light _directionalLight;

        private void OnEnable()
        {
            if (_cameraManager == null || !_cameraManager.enabled)
            {
                Debug.LogWarning("[ARLightEstimation] ARCameraManager unavailable — light estimation disabled.");
                return;
            }

            _cameraManager.requestedLightEstimation =
                LightEstimation.AmbientIntensity          |
                LightEstimation.AmbientColor              |
                LightEstimation.AmbientSphericalHarmonics |
                LightEstimation.MainLightDirection        |
                LightEstimation.MainLightIntensity;
            _cameraManager.frameReceived += OnCameraFrameReceived;
        }

        private void OnDisable()
        {
            if (_cameraManager != null)
            {
                _cameraManager.frameReceived -= OnCameraFrameReceived;
                _cameraManager.requestedLightEstimation = LightEstimation.None;
            }
        }

        private void OnCameraFrameReceived(ARCameraFrameEventArgs args)
        {
            if (_directionalLight == null) return;

            ARLightEstimationData est = args.lightEstimation;

            // --- Main light direction (ARKit Environmental HDR) ---
            if (est.mainLightDirection.HasValue)
                _directionalLight.transform.rotation =
                    Quaternion.LookRotation(est.mainLightDirection.Value);

            // --- Main light intensity (lux) ---
            if (est.mainLightIntensityLumens.HasValue)
                _directionalLight.intensity = est.mainLightIntensityLumens.Value;

            // --- Main light color ---
            if (est.mainLightColor.HasValue)
                _directionalLight.color = est.mainLightColor.Value;

            // --- Fallback: ambient brightness when HDR data is unavailable ---
            if (!est.mainLightIntensityLumens.HasValue && est.averageBrightness.HasValue)
                _directionalLight.intensity = est.averageBrightness.Value;

            // --- Fallback: color temperature ---
            if (!est.mainLightColor.HasValue && est.averageColorTemperature.HasValue)
            {
                _directionalLight.useColorTemperature = true;
                _directionalLight.colorTemperature = est.averageColorTemperature.Value;
            }

            // --- Ambient spherical harmonics ---
            if (est.ambientSphericalHarmonics.HasValue)
            {
                RenderSettings.ambientMode  = AmbientMode.Skybox;
                RenderSettings.ambientProbe = est.ambientSphericalHarmonics.Value;
            }
        }
    }
}
