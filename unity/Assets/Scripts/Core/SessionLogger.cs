using System;
using System.IO;
using System.Text;
using UnityEngine;

namespace AquiFuturo.Core
{
    /// <summary>
    /// Writes session telemetry to CSV at Application.persistentDataPath/sessions/ (SPEC §12).
    /// Flushed every 5 seconds and on application pause.
    /// File I/O failures are logged to Debug.LogError and never swallowed silently.
    /// </summary>
    public sealed class SessionLogger : MonoBehaviour
    {
        public static SessionLogger Instance { get; private set; }

        private const float FlushIntervalSeconds = 5f;

        private string _filePath;
        private StringBuilder _buffer = new StringBuilder(4096);
        private float _flushTimer;
        private long _sessionStartMs;

        private void Awake()
        {
            if (Instance != null && Instance != this)
            {
                Destroy(gameObject);
                return;
            }
            Instance = this;
        }

        private void Start()
        {
            _sessionStartMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            string sessionId = DateTime.UtcNow.ToString("yyyyMMdd_HHmmss");

            string dir = Path.Combine(Application.persistentDataPath, "sessions");
            try
            {
                Directory.CreateDirectory(dir);
                _filePath = Path.Combine(dir, $"{sessionId}.csv");
                File.WriteAllText(_filePath, "timestamp_ms,event,payload\n");
            }
            catch (IOException ex)
            {
                Debug.LogError($"[SessionLogger] Failed to create log file: {ex.Message}");
                _filePath = null;
            }

            LogRaw(0, "session_start", BuildDevicePayload(sessionId));
        }

        private void Update()
        {
            _flushTimer += Time.deltaTime;
            if (_flushTimer >= FlushIntervalSeconds)
            {
                _flushTimer = 0f;
                Flush();
            }
        }

        private void OnApplicationPause(bool paused)
        {
            if (paused) Flush();
        }

        private void OnDestroy()
        {
            Flush();
        }

        // ── Public logging API ────────────────────────────────────────────

        /// <summary>Logs an application state transition.</summary>
        public void LogStateChange(AppState from, AppState to)
        {
            LogRaw(ElapsedMs(), "state_change", $"{{\"from\":\"{from}\",\"to\":\"{to}\"}}");
        }

        /// <summary>Logs placement completion.</summary>
        public void LogPlacementDone(int attempts, long elapsedMs, bool fallback)
        {
            LogRaw(ElapsedMs(), "placement_done",
                $"{{\"attempts\":{attempts},\"elapsed_ms\":{elapsedMs},\"fallback\":{(fallback ? "true" : "false")}}}");
        }

        /// <summary>Logs a 2 Hz pose sample (SPEC §12).</summary>
        public void LogPose(float azimuth, float alignment, float tilt, float distance)
        {
            LogRaw(ElapsedMs(), "pose",
                $"{{\"az\":{azimuth:F1},\"align\":{alignment:F2},\"tilt\":{tilt:F2},\"dist\":{distance:F1}}}");
        }

        /// <summary>Logs a root touch interaction.</summary>
        public void LogRootTouch(int nodeId, string nodeClass, float distM)
        {
            LogRaw(ElapsedMs(), "root_touch",
                $"{{\"node_id\":{nodeId},\"class\":\"{nodeClass}\",\"dist_m\":{distM:F1}}}");
        }

        /// <summary>Logs a tracking loss event.</summary>
        public void LogTrackingLoss(bool lost)
        {
            LogRaw(ElapsedMs(), lost ? "tracking_lost" : "tracking_recovered", "{}");
        }

        /// <summary>Logs instantaneous frames per second.</summary>
        public void LogFps(float fps)
        {
            LogRaw(ElapsedMs(), "fps", $"{{\"fps\":{fps:F1}}}");
        }

        // ── Internal ──────────────────────────────────────────────────────

        private void LogRaw(long timestampMs, string eventName, string payload)
        {
            _buffer.Append(timestampMs)
                   .Append(',')
                   .Append(eventName)
                   .Append(',')
                   .Append(payload)
                   .Append('\n');
        }

        private void Flush()
        {
            if (_filePath == null || _buffer.Length == 0) return;

            string data = _buffer.ToString();
            _buffer.Clear();

            try
            {
                File.AppendAllText(_filePath, data);
            }
            catch (IOException ex)
            {
                // SPEC §12: IOException must be logged, never silently swallowed.
                Debug.LogError($"[SessionLogger] Flush failed — data loss risk: {ex.Message}");
            }
        }

        private long ElapsedMs()
        {
            return DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - _sessionStartMs;
        }

        private static string BuildDevicePayload(string sessionId)
        {
            return $"{{\"session\":\"{sessionId}\"," +
                   $"\"device\":\"{SystemInfo.deviceModel}\"," +
                   $"\"os\":\"{SystemInfo.operatingSystem}\"," +
                   $"\"build\":\"{Application.version}\"}}";
        }
    }
}
