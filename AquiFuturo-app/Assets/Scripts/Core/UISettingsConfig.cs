using UnityEngine;

namespace AquiFuturo.Core
{
    /// <summary>
    /// Tunable UI values — no magic numbers in MenuController (SPEC §15).
    /// </summary>
    [CreateAssetMenu(menuName = "AquiFuturo/UISettingsConfig", fileName = "UISettings")]
    public sealed class UISettingsConfig : ScriptableObject
    {
        [Header("Links")]
        [Tooltip("Google Form URL opened by Leave a Comment.")]
        public string commentFormUrl =
            "https://docs.google.com/forms/d/e/1FAIpQLSdf9gWs-nB3LHqaTPVRlau-NX8k7zRxUIz1BAhj7zaOePz0Yw/viewform?usp=header";

        [Header("Test Audio")]
        [Tooltip("Short clip played when Test Audio is tapped. Assign test_audio.wav.")]
        public AudioClip testAudioClip;

        [Header("Particles")]
        [Range(5, 50)]
        [Tooltip("Number of ambient background particles on the menu.")]
        public int particleCount = 20;

        [Header("Transition")]
        [Tooltip("Fade-through-black curtain duration in seconds (half = fade-in, half = fade-out).")]
        public float curtainDuration = 0.43f;
    }
}
