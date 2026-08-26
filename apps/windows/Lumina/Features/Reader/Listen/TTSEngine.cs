using Windows.Media.Core;
using Windows.Media.Playback;
using Windows.Media.SpeechSynthesis;
using Windows.Storage.Streams;

namespace Lumina.Features.Reader.Listen;

public sealed record ListenSpeakRequest(
    IReadOnlyList<string> Texts,
    string Language,
    float Rate,
    string BookId,
    int Idx,
    ListenMode Mode);

public interface IListenEngine : IDisposable
{
    bool IsPaused { get; }
    Task SpeakAsync(ListenSpeakRequest request, CancellationToken ct);
    void Pause();
    void Resume();
    void Stop();
}

public sealed class SystemNeuralEngine : IListenEngine
{
    private readonly MediaPlayer _player = new();
    private TaskCompletionSource<bool>? _ended;
    private int _generation;
    private bool _paused;
    public bool IsPaused => _paused;

    public async Task SpeakAsync(ListenSpeakRequest request, CancellationToken ct)
    {
        Stop();
        var token = Interlocked.Increment(ref _generation);
        _paused = false;
        using var synth = new SpeechSynthesizer();
        var voice = PreferredVoice(request.Language, ListenPreferences.SystemVoiceId);
        if (voice is not null)
            synth.Voice = voice;
        try
        {
            synth.Options.SpeakingRate = Math.Clamp(request.Rate, 0.5, 6.0);
        }
        catch (ArgumentException)
        {
            // Some voices ignore out-of-range rates; keep going.
        }

        foreach (var text in request.Texts)
        {
            ct.ThrowIfCancellationRequested();
            if (token != _generation) throw new OperationCanceledException();
            var stream = await synth.SynthesizeTextToStreamAsync(text).AsTask(ct).ConfigureAwait(true);
            await PlayAsync(stream, stream.ContentType, token, ct).ConfigureAwait(true);
        }
    }

    public void Pause()
    {
        _player.Pause();
        _paused = true;
    }

    public void Resume()
    {
        _player.Play();
        _paused = false;
    }

    public void Stop()
    {
        Interlocked.Increment(ref _generation);
        _paused = false;
        _player.Pause();
        _player.Source = null;
        _ended?.TrySetCanceled();
        _ended = null;
    }

    public void Dispose()
    {
        Stop();
        _player.Dispose();
    }

    private async Task PlayAsync(IRandomAccessStream stream, string mime, int token, CancellationToken ct)
    {
        var tcs = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        _ended = tcs;
        void OnEnded(MediaPlayer sender, object args) => tcs.TrySetResult(true);
        void OnFailed(MediaPlayer sender, MediaPlayerFailedEventArgs args) =>
            tcs.TrySetException(new InvalidOperationException(args.ErrorMessage));
        _player.MediaEnded += OnEnded;
        _player.MediaFailed += OnFailed;
        using var reg = ct.Register(() =>
        {
            _player.Pause();
            tcs.TrySetCanceled();
        });
        try
        {
            _player.Source = MediaSource.CreateFromStream(stream, mime);
            _player.Play();
            await tcs.Task.ConfigureAwait(true);
        }
        finally
        {
            _player.MediaEnded -= OnEnded;
            _player.MediaFailed -= OnFailed;
            if (ReferenceEquals(_ended, tcs)) _ended = null;
            if (token != _generation) throw new OperationCanceledException();
        }
    }

    public static VoiceInformation? PreferredVoice(string language, string? identifier)
    {
        var voices = SpeechSynthesizer.AllVoices.ToList();
        if (!string.IsNullOrWhiteSpace(identifier))
        {
            var match = voices.FirstOrDefault(v => v.Id == identifier);
            if (match is not null) return match;
        }
        var prefix = language == "en" ? "en" : "zh";
        var filtered = voices
            .Where(v => v.Language.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            .ToList();
        return filtered.FirstOrDefault(v => IsHighQuality(v))
            ?? filtered.FirstOrDefault()
            ?? SpeechSynthesizer.DefaultVoice;
    }

    public static bool IsHighQuality(VoiceInformation voice) =>
        voice.DisplayName.Contains("Neural", StringComparison.OrdinalIgnoreCase)
        || voice.DisplayName.Contains("Natural", StringComparison.OrdinalIgnoreCase);

    public static string QualityLabel(VoiceInformation voice) =>
        IsHighQuality(voice) ? "高级" : "标准";

    public static bool HasDownloadedHighQualityVoice()
    {
        try
        {
            return SpeechSynthesizer.AllVoices.Any(v =>
                (v.Language.StartsWith("zh", StringComparison.OrdinalIgnoreCase)
                 || v.Language.StartsWith("en", StringComparison.OrdinalIgnoreCase))
                && IsHighQuality(v));
        }
        catch
        {
            return false;
        }
    }
}
