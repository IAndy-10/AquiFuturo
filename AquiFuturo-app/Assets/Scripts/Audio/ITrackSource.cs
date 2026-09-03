using UnityEngine;

namespace AquiFuturo.Audio
{
    /// <summary>
    /// Abstraction over a track's audio content (SPEC §3.3).
    /// The clip-backed implementation is used in the MVP.
    /// The streaming implementation (runtime RAVE) is deferred.
    /// </summary>
    public interface ITrackSource
    {
        /// <summary>Identifier matching audio_manifest.json 'id' field.</summary>
        string Id { get; }

        /// <summary>AudioClip to assign to the AudioSource. Null in streaming implementations.</summary>
        AudioClip Clip { get; }
    }
}
