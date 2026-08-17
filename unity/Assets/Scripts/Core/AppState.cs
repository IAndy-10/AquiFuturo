namespace AquiFuturo.Core
{
    /// <summary>Application state machine states (SPEC §7).</summary>
    public enum AppState
    {
        Menu,            // Main menu — shown on launch
        Instructions,    // 3-card onboarding flow
        Booting,
        Scanning,
        Placing,         // "Click to locate the roots" button visible
        PlacingFallback,
        Adjusting,       // Root system placed, audio starts
        Experiencing,    // Full AR session active
        Ended
    }
}
