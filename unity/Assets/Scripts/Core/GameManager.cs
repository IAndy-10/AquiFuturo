using System;
using UnityEngine;
using UnityEngine.XR.ARFoundation;

namespace AquiFuturo.Core
{
    /// <summary>
    /// Owns the application state machine (SPEC §7).
    /// Lives on the Bootstrap GameObject alongside SessionLogger, PoseAnalyzer, HudController.
    /// </summary>
    public sealed class GameManager : MonoBehaviour
    {
        [SerializeField] private PlacementSettingsConfig _placementConfig;

        private ARSession _arSession;
        private AppState _state = AppState.Booting;
        private float _scanTimer;
        private float _trackingLossTimer;
        private bool _trackingCurrentlyLost;

        /// <summary>Current application state.</summary>
        public AppState State => _state;

        /// <summary>Fired when the state changes. Arguments are (previousState, newState).</summary>
        public event Action<AppState, AppState> OnStateChanged;

        private void Awake()
        {
            _arSession = FindObjectOfType<ARSession>();
            if (_arSession == null)
                Debug.LogWarning("[GameManager] ARSession not found in scene.");
        }

        private void Start()
        {
            ARSession.stateChanged += HandleARSessionStateChanged;
            TransitionTo(AppState.Menu);
        }

        private void OnDestroy()
        {
            ARSession.stateChanged -= HandleARSessionStateChanged;
        }

        private void Update()
        {
            if (_state == AppState.Scanning)
            {
                _scanTimer += Time.deltaTime;
                if (_placementConfig != null &&
                    _scanTimer >= _placementConfig.scanTimeoutSeconds)
                {
                    TransitionTo(AppState.PlacingFallback);
                }
            }

            if (_trackingCurrentlyLost && _state == AppState.Experiencing)
            {
                _trackingLossTimer += Time.deltaTime;
            }
        }

        // ── Called by MenuController ──────────────────────────────────────

        /// <summary>Play pressed on main menu → begin onboarding.</summary>
        public void OnMenuPlay()
        {
            if (_state == AppState.Menu)
                TransitionTo(AppState.Instructions);
        }

        /// <summary>Last instruction card completed → start AR placement.</summary>
        public void OnInstructionsComplete()
        {
            if (_state == AppState.Instructions)
                TransitionTo(AppState.Placing);
        }

        /// <summary>Return to main menu from any state (reset clears the tree).</summary>
        public void OnBackToMenu()
        {
            _scanTimer = 0f;
            TransitionTo(AppState.Menu);
        }

        // ── Called by TreePlacement ───────────────────────────────────────

        /// <summary>Notifies GameManager that at least one valid plane has been detected.</summary>
        public void OnPlaneDetected()
        {
            if (_state == AppState.Scanning)
                TransitionTo(AppState.Placing);
        }

        /// <summary>Notifies GameManager that the user has tapped a valid placement point.</summary>
        public void OnTreePlaced()
        {
            if (_state == AppState.Placing || _state == AppState.PlacingFallback)
                TransitionTo(AppState.Adjusting);
        }

        /// <summary>Notifies GameManager that the user has confirmed the placement.</summary>
        public void OnPlacementConfirmed()
        {
            if (_state == AppState.Adjusting)
                TransitionTo(AppState.Experiencing);
        }

        /// <summary>Resets tree placement, returning to Placing state.</summary>
        public void ResetPlacement()
        {
            _scanTimer = 0f;
            TransitionTo(AppState.Placing);
        }

        /// <summary>Ends the session. SessionLogger flushes on destroy.</summary>
        public void EndSession()
        {
            TransitionTo(AppState.Ended);
        }

        /// <summary>Whether tracking has been lost for longer than the configured threshold.</summary>
        public bool IsTrackingMuted =>
            _trackingCurrentlyLost &&
            _placementConfig != null &&
            _trackingLossTimer >= _placementConfig.trackingLossMuteSeconds;

        // ── AR session events ─────────────────────────────────────────────

        private void HandleARSessionStateChanged(ARSessionStateChangedEventArgs args)
        {
            bool nowTracking = args.state == ARSessionState.SessionTracking;

            if (!nowTracking && !_trackingCurrentlyLost)
            {
                _trackingCurrentlyLost = true;
                _trackingLossTimer = 0f;
                SessionLogger.Instance?.LogTrackingLoss(true);
            }
            else if (nowTracking && _trackingCurrentlyLost)
            {
                _trackingCurrentlyLost = false;
                _trackingLossTimer = 0f;
                SessionLogger.Instance?.LogTrackingLoss(false);
            }
        }

        // ── Internal ──────────────────────────────────────────────────────

        private void TransitionTo(AppState next)
        {
            AppState prev = _state;
            _state = next;
            Debug.Log($"[GameManager] {prev} → {next}");
            OnStateChanged?.Invoke(prev, next);
            SessionLogger.Instance?.LogStateChange(prev, next);

            if (next == AppState.Scanning)
                _scanTimer = 0f;
        }
    }
}
