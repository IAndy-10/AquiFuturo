namespace AquiFuturo.Core
{
    /// <summary>Application state machine states (SPEC §7).</summary>
    public enum AppState
    {
        Menu,            // Main menu — shown on launch
        Instructions,    // 3-card onboarding flow
        Booting,
        Placing,         // "Click to locate the roots" button visible
        Adjusting,       // Root system placed, audio starts
        Experiencing,    // Full AR session active
        Ended
    }
}
