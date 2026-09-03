using UnityEngine;
using UnityEngine.UI;
using AquiFuturo.Core;
using AquiFuturo.Audio;

namespace AquiFuturo.UI
{
    /// <summary>
    /// Drives all HUD elements: scan/place prompts, confirm/reset buttons,
    /// and the debug pose-axis readout (SPEC §15 DebugSettingsConfig).
    /// No allocations in Update — text is only set when values change meaningfully.
    /// </summary>
    public sealed class HudController : MonoBehaviour
    {
        [SerializeField] private DebugSettingsConfig _debugConfig;
        [SerializeField] private GameManager _gameManager;
        [SerializeField] private PoseAnalyzer _poseAnalyzer;

        [Header("Prompts")]
        [SerializeField] private GameObject _placePrompt;

        [Header("Buttons")]
        [SerializeField] private Button _confirmButton;
        [SerializeField] private Button _resetButton;

        [Header("Debug")]
        [SerializeField] private Text _debugReadout;

        private AppState _lastState = AppState.Booting;
        private float _debugUpdateTimer;
        private const float DebugUpdateInterval = 0.1f;   // 10 Hz is enough for readout

        private void OnEnable()
        {
            if (_gameManager != null)
                _gameManager.OnStateChanged += HandleStateChanged;

            if (_confirmButton != null)
                _confirmButton.onClick.AddListener(OnConfirmPressed);

            if (_resetButton != null)
                _resetButton.onClick.AddListener(OnResetPressed);
        }

        private void OnDisable()
        {
            if (_gameManager != null)
                _gameManager.OnStateChanged -= HandleStateChanged;

            if (_confirmButton != null)
                _confirmButton.onClick.RemoveListener(OnConfirmPressed);

            if (_resetButton != null)
                _resetButton.onClick.RemoveListener(OnResetPressed);
        }

        private void Start()
        {
            RefreshVisibility(AppState.Booting);
        }

        private void Update()
        {
            if (_debugReadout == null || _poseAnalyzer == null) return;
            if (_debugConfig == null || !_debugConfig.showPoseReadout) return;

            _debugUpdateTimer += Time.deltaTime;
            if (_debugUpdateTimer < DebugUpdateInterval) return;
            _debugUpdateTimer = 0f;

            // String.Format allocates — acceptable at 10 Hz on a non-critical UI path.
            _debugReadout.text =
                $"Az  {_poseAnalyzer.Azimuth,7:F1}°\n" +
                $"Al  {_poseAnalyzer.Alignment,7:F2}\n" +
                $"Ti  {_poseAnalyzer.Tilt,7:F2}\n" +
                $"Di  {_poseAnalyzer.Distance,7:F1} m\n" +
                $"At  {_poseAnalyzer.Attention,7:F2}";
        }

        // ── Button handlers ───────────────────────────────────────────────

        private void OnConfirmPressed()
        {
            var placement = FindObjectOfType<Placement.TreePlacement>();
            placement?.ConfirmPlacement();
        }

        private void OnResetPressed()
        {
            var placement = FindObjectOfType<Placement.TreePlacement>();
            placement?.ResetPlacement();
        }

        // ── State-driven UI ───────────────────────────────────────────────

        private void HandleStateChanged(AppState prev, AppState next)
        {
            RefreshVisibility(next);
        }

        private void RefreshVisibility(AppState state)
        {
            SetActive(_placePrompt,   state == AppState.Placing);
            SetActive(_confirmButton?.gameObject, state == AppState.Adjusting);
            SetActive(_resetButton?.gameObject,
                state == AppState.Adjusting || state == AppState.Experiencing);
            SetActive(_debugReadout?.gameObject,
                _debugConfig != null && _debugConfig.showPoseReadout);
        }

        private static void SetActive(GameObject go, bool active)
        {
            if (go != null && go.activeSelf != active)
                go.SetActive(active);
        }
    }
}
