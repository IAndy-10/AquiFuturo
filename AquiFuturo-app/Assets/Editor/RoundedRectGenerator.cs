using System.IO;
using UnityEditor;
using UnityEngine;

namespace AquiFuturo.Editor
{
    /// <summary>
    /// Generates a 128x128 white rounded-rectangle sprite with 9-slice borders.
    /// Run once via AquiFuturo -> Generate Rounded Rect Sprite.
    /// Tint the sprite at runtime via Image.color — no extra textures needed.
    /// </summary>
    public static class RoundedRectGenerator
    {
        private const string OutputPath = "Assets/Art/UI/rounded_rect.png";
        private const int Size   = 128;
        private const int Radius = 28;

        [MenuItem("AquiFuturo/Generate Rounded Rect Sprite")]
        public static void Generate()
        {
            var tex = new Texture2D(Size, Size, TextureFormat.RGBA32, false);

            for (int y = 0; y < Size; y++)
            for (int x = 0; x < Size; x++)
                tex.SetPixel(x, y, InsideRoundedRect(x, y) ? Color.white : Color.clear);

            tex.Apply();

            string absDir = Path.Combine(Application.dataPath, "Art", "UI");
            Directory.CreateDirectory(absDir);

            string absPath = Path.Combine(Application.dataPath, "..", OutputPath);
            File.WriteAllBytes(absPath, tex.EncodeToPNG());
            Object.DestroyImmediate(tex);

            AssetDatabase.Refresh();

            var importer = AssetImporter.GetAtPath(OutputPath) as TextureImporter;
            if (importer != null)
            {
                importer.textureType         = TextureImporterType.Sprite;
                importer.spriteImportMode    = SpriteImportMode.Single;
                importer.spriteBorder        = new Vector4(Radius, Radius, Radius, Radius);
                importer.alphaIsTransparency = true;
                importer.SaveAndReimport();
            }

            Debug.Log("[RoundedRectGenerator] Sprite saved to " + OutputPath);
        }

        private static bool InsideRoundedRect(int x, int y)
        {
            int r = Radius, w = Size, h = Size;
            if (x < r    && y < r)    return InCircle(x, y, r,   r,   r);
            if (x >= w-r && y < r)    return InCircle(x, y, w-r, r,   r);
            if (x < r    && y >= h-r) return InCircle(x, y, r,   h-r, r);
            if (x >= w-r && y >= h-r) return InCircle(x, y, w-r, h-r, r);
            return true;
        }

        private static bool InCircle(int px, int py, int cx, int cy, int r)
        {
            int dx = px - cx, dy = py - cy;
            return dx * dx + dy * dy <= r * r;
        }
    }
}
