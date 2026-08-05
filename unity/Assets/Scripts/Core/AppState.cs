namespace AquiFuturo.Core
{
    /// <summary>Application state machine states (SPEC §7).</summary>
    public enum AppState
    {
        Booting,
        Scanning,
        Placing,
        PlacingFallback,
        Adjusting,
        Experiencing,
        Ended
    }
}
