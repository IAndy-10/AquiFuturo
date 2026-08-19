using System.Collections;
using UnityEngine;
using UnityEngine.UI;

namespace AquiFuturo.UI
{
    /// <summary>
    /// Displays a texture with CSS object-fit:cover behaviour — scales to fill
    /// the RectTransform, crops edges, centres the subject.
    /// Optionally clips to a rounded rectangle via a custom UI shader.
    /// Requires pivot = (0.5, 0.5) for correct corner rendering.
    /// Attach alongside a RawImage. Assign Texture in the RawImage field.
    /// </summary>
    [RequireComponent(typeof(RawImage))]
    public sealed class CoverImage : MonoBehaviour
    {
        [SerializeField]
        [Tooltip("Shader asset: AquiFuturo/UI/RoundedCorners. Leave empty for no rounding.")]
        private Shader _roundedCornersShader;

        [SerializeField]
        [Tooltip("Corner radius in Canvas pixels. Only used when shader is assigned.")]
        private float _cornerRadius = 24f;

        private RawImage      _rawImage;
        private RectTransform _rt;
        private Material      _material;
        private bool          _pendingRefresh;

        // ── Unity lifecycle ───────────────────────────────────────────────

        private void Awake()
        {
            _rawImage = GetComponent<RawImage>();
            _rt       = GetComponent<RectTransform>();

            if (_roundedCornersShader != null)
            {
                _material         = new Material(_roundedCornersShader);
                _rawImage.material = _material;
            }
        }

        private void OnEnable() => ScheduleRefresh();

        private void OnDestroy()
        {
            if (_material != null)
                Destroy(_material);
        }

        // ── Public API ────────────────────────────────────────────────────

        /// <summary>Recalculates UV rect (cover crop) and updates shader rect size.</summary>
        public void Refresh()
        {
            if (_rawImage.texture == null) return;

            float frameW = _rt.rect.width;
            float frameH = _rt.rect.height;
            if (frameW <= 0f || frameH <= 0f) return;

            float texW = _rawImage.texture.width;
            float texH = _rawImage.texture.height;

            float frameAspect = frameW / frameH;
            float texAspect   = texW   / texH;

            float uSize, vSize, u, v;

            if (texAspect > frameAspect)
            {
                // Texture wider than frame — crop left/right, fill height
                vSize = 1f;
                uSize = frameAspect / texAspect;
                u     = (1f - uSize) * 0.5f;
                v     = 0f;
            }
            else
            {
                // Texture taller than frame — crop top/bottom, fill width
                uSize = 1f;
                vSize = texAspect / frameAspect;
                u     = 0f;
                v     = (1f - vSize) * 0.5f;
            }

            _rawImage.uvRect = new Rect(u, v, uSize, vSize);

            if (_material != null)
            {
                _material.SetVector("_RectSize", new Vector4(frameW, frameH, 0f, 0f));
                _material.SetFloat("_CornerRadius", _cornerRadius);
            }
        }

        // ── Layout timing guard ───────────────────────────────────────────

        // Defer Refresh by one frame so the VerticalLayoutGroup finishes
        // assigning children's heights before we read rect.width/height.
        private void OnRectTransformDimensionsChange() => ScheduleRefresh();

        private void ScheduleRefresh()
        {
            if (_pendingRefresh || !gameObject.activeInHierarchy) return;
            _pendingRefresh = true;
            StartCoroutine(RefreshNextFrame());
        }

        private IEnumerator RefreshNextFrame()
        {
            yield return null;
            _pendingRefresh = false;
            Refresh();
        }
    }
}
