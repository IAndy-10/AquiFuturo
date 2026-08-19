using System.Collections;
using UnityEngine;
using UnityEngine.UI;
using TMPro;
using AquiFuturo.Core;
using AquiFuturo.Placement;

namespace AquiFuturo.UI
{
    /// <summary>
    /// Drives the full UI flow: Menu → Instructions → AR overlay.
    /// All panels are CanvasGroups shown/hidden by state.
    /// Curtain transition: fade through black between Menu and Instructions.
    /// </summary>
    [RequireComponent(typeof(AudioSource))]
    public sealed class MenuController : MonoBehaviour
    {
        [Header("Config")]
        [SerializeField] private UISettingsConfig _config;
        [SerializeField] private GameManager      _gameManager;
        [SerializeField] private TreePlacement    _treePlacement;

        [Header("Panels — CanvasGroups")]
        [SerializeField] private CanvasGroup _menuPanel;
        [SerializeField] private CanvasGroup _instructionsPanel;
        [SerializeField] private CanvasGroup _arPanel;

        [Header("Curtain")]
        [Tooltip("Full-screen black Image used for fade transitions. Starts at alpha 0.")]
        [SerializeField] private CanvasGroup _curtainGroup;

        [Header("Instruction Step Dots (3 Images)")]
        [SerializeField] private Image[] _stepDots;            // length 3

        [Header("Instruction Illustrations (3 GameObjects — one per card)")]
        [SerializeField] private GameObject[] _illustrationImages;  // length 3

        [Header("Instruction Body Text")]
        [SerializeField] private TMP_Text _instructionText;

        [Header("AR Overlay Groups")]
        [SerializeField] private GameObject _preLocateGroup;   // shown before roots placed
        [SerializeField] private GameObject _postLocateGroup;  // shown after roots placed

        [Header("Background")]
        [Tooltip("Full-screen background Image shown during Menu and Instructions only. Hidden during AR states.")]
        [SerializeField] private GameObject _background;

        [Header("Particles")]
        [Tooltip("Empty RectTransform inside the Menu panel. Particles are spawned here.")]
        [SerializeField] private RectTransform _particleContainer;
        [Tooltip("Optional soft circle sprite for particles. Leave empty for solid squares.")]
        [SerializeField] private Sprite _particleSprite;

        // ── Design palette (from ui/AquiFuturo App.dc.html) ──────────────
        private static readonly Color ColDotActive   = new Color(91f/255f, 132f/255f, 176f/255f, 1f);
        private static readonly Color ColDotInactive = new Color(38f/255f,  43f/255f,  61f/255f, 1f);
        private static readonly Color ColParticleBlue = new Color(91f/255f, 132f/255f, 176f/255f, 0.55f);
        private static readonly Color ColParticleOrange = new Color(199f/255f, 124f/255f, 78f/255f, 0.55f);

        private static readonly string[] InstructionTexts =
        {
            "Find a tree that you like and get closer to its trunk. Ideally touch the tree to ensure that you are in the correct distance.",
            "Keep your cellphone at a normal height, like the one you normally chat, and change the angle pointing the root of the tree.",
            "Press \"Click to locate the roots\". Step back to see the full root system. Touch the roots to trigger sounds and move the phone to explore the spatial audio."
        };

        private AudioSource _audioSource;
        private int  _step;
        private bool _transitioning;

        // ── Unity lifecycle ───────────────────────────────────────────────

        private void Awake()
        {
            _audioSource = GetComponent<AudioSource>();
            _audioSource.playOnAwake = false;
            _audioSource.spatialBlend = 0f;

            // Curtain starts invisible
            if (_curtainGroup != null)
            {
                _curtainGroup.alpha = 0f;
                _curtainGroup.blocksRaycasts = false;
            }
        }

        private void OnEnable()
        {
            if (_gameManager != null)
                _gameManager.OnStateChanged += HandleStateChanged;
        }

        private void OnDisable()
        {
            if (_gameManager != null)
                _gameManager.OnStateChanged -= HandleStateChanged;
        }

        private void Start()
        {
            SpawnParticles();
            RefreshPanels(AppState.Menu);
        }

        // ── Button handlers — wire these to Button.OnClick in Inspector ──

        /// <summary>Play button on main menu.</summary>
        public void OnPlayPressed()
        {
            _gameManager?.OnMenuPlay();
        }

        /// <summary>Test Audio button on main menu.</summary>
        public void OnTestAudioPressed()
        {
            if (_config?.testAudioClip == null)
            {
                Debug.LogWarning("[MenuController] Test audio clip not assigned in UISettings.");
                return;
            }
            if (_audioSource.isPlaying) _audioSource.Stop();
            _audioSource.PlayOneShot(_config.testAudioClip);
        }

        /// <summary>Leave a Comment — opens the Google Form URL.</summary>
        public void OnLeaveCommentPressed()
        {
            string url = _config?.commentFormUrl;
            if (!string.IsNullOrEmpty(url))
                Application.OpenURL(url);
        }

        /// <summary>Back arrow / Back button on instructions panel.</summary>
        public void OnPrevPressed()
        {
            if (_step > 0)
                ShowStep(_step - 1);
            else
                _gameManager?.OnBackToMenu();
        }

        /// <summary>Continue arrow / Continue button on instructions panel.</summary>
        public void OnNextPressed()
        {
            if (_step < 2)
                ShowStep(_step + 1);
            else
                _gameManager?.OnInstructionsComplete();
        }

        /// <summary>"Click to locate the roots" button on AR panel.</summary>
        public void OnLocatePressed()
        {
            _treePlacement?.PlaceAndConfirm();
        }

        /// <summary>Reset icon — clear placed root system, go back to "Click to locate".</summary>
        public void OnResetPressed()
        {
            _treePlacement?.ResetPlacement();
        }

        /// <summary>Home icon — destroy placement and return to main menu.</summary>
        public void OnHomePressed()
        {
            _treePlacement?.ResetPlacement();
            _gameManager?.OnBackToMenu();
        }

        // ── State machine ─────────────────────────────────────────────────

        private void HandleStateChanged(AppState prev, AppState next)
        {
            // Curtain fade: Menu ↔ Instructions
            bool useFade = (prev == AppState.Menu && next == AppState.Instructions) ||
                           (prev == AppState.Instructions && next == AppState.Menu);

            if (useFade)
                StartCoroutine(FadeTransition(() => RefreshPanels(next)));
            else
                RefreshPanels(next);
        }

        private void RefreshPanels(AppState state)
        {
            bool isMenu  = state == AppState.Menu;
            bool isInstr = state == AppState.Instructions;
            bool isAr    = state == AppState.Placing ||
                           state == AppState.PlacingFallback ||
                           state == AppState.Adjusting ||
                           state == AppState.Experiencing;

            SetPanel(_menuPanel,         isMenu);
            SetPanel(_instructionsPanel, isInstr);
            SetPanel(_arPanel,           isAr);

            // Background and particles only on menu / instructions
            bool showCover = isMenu || isInstr;
            if (_background != null)
                _background.SetActive(showCover);
            if (_particleContainer != null)
                _particleContainer.gameObject.SetActive(showCover);

            if (isInstr)
                ShowStep(0);

            if (isAr)
            {
                bool hasRoots = state == AppState.Experiencing;
                if (_preLocateGroup  != null) _preLocateGroup.SetActive(!hasRoots);
                if (_postLocateGroup != null) _postLocateGroup.SetActive(hasRoots);
            }
        }

        // ── Instruction cards ─────────────────────────────────────────────

        private void ShowStep(int step)
        {
            _step = Mathf.Clamp(step, 0, 2);

            if (_instructionText != null)
                _instructionText.text = InstructionTexts[_step];

            for (int i = 0; i < 3; i++)
            {
                if (i < _stepDots.Length && _stepDots[i] != null)
                    _stepDots[i].color = (i <= _step) ? ColDotActive : ColDotInactive;

                if (i < _illustrationImages.Length && _illustrationImages[i] != null)
                    _illustrationImages[i].SetActive(i == _step);
            }
        }

        // ── Curtain (fade through black) ──────────────────────────────────

        private IEnumerator FadeTransition(System.Action midAction)
        {
            if (_transitioning) yield break;
            _transitioning = true;

            float half = (_config != null ? _config.curtainDuration : 0.43f) * 0.5f;

            // Fade to black
            if (_curtainGroup != null) _curtainGroup.blocksRaycasts = true;
            yield return FadeCurtain(0f, 1f, half);

            midAction?.Invoke();

            // Fade from black
            yield return FadeCurtain(1f, 0f, half);
            if (_curtainGroup != null) _curtainGroup.blocksRaycasts = false;

            _transitioning = false;
        }

        private IEnumerator FadeCurtain(float from, float to, float duration)
        {
            if (_curtainGroup == null) yield break;
            float elapsed = 0f;
            while (elapsed < duration)
            {
                elapsed += Time.unscaledDeltaTime;
                float t = Mathf.Clamp01(elapsed / duration);
                float smooth = t * t * (3f - 2f * t);  // smoothstep
                _curtainGroup.alpha = Mathf.Lerp(from, to, smooth);
                yield return null;
            }
            _curtainGroup.alpha = to;
        }

        // ── Ambient particles ─────────────────────────────────────────────

        private void SpawnParticles()
        {
            if (_particleContainer == null) return;
            int count = _config != null ? _config.particleCount : 20;

            for (int i = 0; i < count; i++)
            {
                var go = new GameObject($"P{i}");
                go.transform.SetParent(_particleContainer, false);

                var rt = go.AddComponent<RectTransform>();
                float size = Random.Range(4f, 14f);
                rt.sizeDelta = new Vector2(size, size);
                rt.anchorMin = new Vector2(Random.value, Random.value);
                rt.anchorMax = rt.anchorMin;
                rt.anchoredPosition = Vector2.zero;

                var img = go.AddComponent<Image>();
                if (_particleSprite != null) img.sprite = _particleSprite;
                img.color = (Random.value < 0.7f) ? ColParticleBlue : ColParticleOrange;

                StartCoroutine(FloatParticle(rt, Random.Range(10f, 26f), Random.Range(0f, 26f)));
            }
        }

        private IEnumerator FloatParticle(RectTransform rt, float period, float offset)
        {
            Vector2 origin = rt.anchoredPosition;
            float elapsed = offset;
            while (true)
            {
                elapsed += Time.unscaledDeltaTime;
                float t = (elapsed % period) / period * Mathf.PI * 2f;
                rt.anchoredPosition = origin + new Vector2(
                    Mathf.Sin(t) * 8f + Mathf.Sin(t * 2f + 1f) * 4f,
                    Mathf.Cos(t) * 10f + Mathf.Cos(t * 1.5f + 0.5f) * 5f);
                yield return null;
            }
        }

        // ── Helpers ───────────────────────────────────────────────────────

        private static void SetPanel(CanvasGroup panel, bool visible)
        {
            if (panel == null) return;
            panel.alpha          = visible ? 1f : 0f;
            panel.interactable   = visible;
            panel.blocksRaycasts = visible;
        }
    }
}
