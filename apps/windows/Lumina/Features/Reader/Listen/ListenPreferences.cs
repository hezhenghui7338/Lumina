using Lumina.Design;
using Lumina.Services;

namespace Lumina.Features.Reader.Listen;

public static class ListenPreferences
{
    public static readonly float[] Rates = [0.8f, 1.0f, 1.25f, 1.5f, 2.0f];

    public static float Rate
    {
        get => SnapRate(LocalPrefs.ListenRate);
        set => LocalPrefs.ListenRate = SnapRate(value);
    }

    public static string? SystemVoiceId
    {
        get => string.IsNullOrWhiteSpace(LocalPrefs.ListenSystemVoiceId)
            ? null
            : LocalPrefs.ListenSystemVoiceId;
        set => LocalPrefs.ListenSystemVoiceId = value ?? "";
    }

    public static float SnapRate(float value)
    {
        var best = 1.0f;
        var bestDelta = float.MaxValue;
        foreach (var rate in Rates)
        {
            var delta = Math.Abs(rate - value);
            if (delta < bestDelta)
            {
                best = rate;
                bestDelta = delta;
            }
        }
        return best;
    }

    public static void SyncFromSettings(TtsSettings? tts)
    {
        if (tts is null) return;
        if (tts.Speed > 0)
            Rate = (float)tts.Speed;
    }
}
