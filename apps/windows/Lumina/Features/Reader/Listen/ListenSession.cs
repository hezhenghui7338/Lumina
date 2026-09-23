using Microsoft.UI.Dispatching;

namespace Lumina.Features.Reader.Listen;

public sealed class ListenSession : IDisposable
{
    public event EventHandler? Changed;
    public event Action<int>? HighlightSegment;

    private readonly DispatcherQueue _dq;
    private int _generation;
    private int _consecutiveSkips;
    private CancellationTokenSource? _playCts;
    private IListenEngine? _engine;
    private Func<int, ListenMode, ListenChapterSpeakContext, CancellationToken, Task<ListenScript>>? _resolve;
    private Func<int, string>? _labelFor;
    private Func<int, string?>? _chapterFor;
    private Func<IListenEngine>? _makeEngine;
    private string _bookId = "";
    private int _segmentCount;
    private string? _lastSpokenChapter;
    private bool _hasSpokenSegment;

    public ListenSession(DispatcherQueue dispatcher)
    {
        _dq = dispatcher;
    }

    public bool IsActive { get; private set; }
    public bool IsPlaying { get; private set; }
    public bool IsLoading { get; private set; }
    public bool IsPaused { get; private set; }
    public ListenMode Mode { get; private set; } = ListenMode.Summary;
    public int CurrentIdx { get; private set; }
    public float Rate { get; private set; } = ListenPreferences.Rate;
    public string? StatusMessage { get; private set; }
    public string? SkipNotice { get; private set; }
    public string SegmentLabel { get; private set; } = "";
    /// Light follow-along target for the utterance currently speaking (kept while paused).
    public ListenHighlightAnchor? ActiveHighlight { get; private set; }

    public string Title
    {
        get
        {
            var mode = ListenScriptBuilder.ShortLabel(Mode);
            return string.IsNullOrEmpty(SegmentLabel)
                ? $"听{mode} · 段 {CurrentIdx + 1}"
                : $"听{mode} · {SegmentLabel}";
        }
    }

    public string Banner => SkipNotice ?? StatusMessage ?? "";

    public void Configure(
        string bookId,
        int segmentCount,
        Func<int, ListenMode, ListenChapterSpeakContext, CancellationToken, Task<ListenScript>> resolve,
        Func<int, string> labelFor,
        Func<IListenEngine> makeEngine,
        Func<int, string?>? chapterFor = null)
    {
        _bookId = bookId;
        _segmentCount = segmentCount;
        _resolve = resolve;
        _labelFor = labelFor;
        _chapterFor = chapterFor;
        _makeEngine = makeEngine;
    }

    public void UpdateSegmentCount(int count) => _segmentCount = count;

    public void Start(ListenMode mode, int fromIdx)
    {
        if (_segmentCount <= 0 || _resolve is null) return;
        Stop();
        Mode = mode;
        CurrentIdx = Math.Clamp(fromIdx, 0, Math.Max(0, _segmentCount - 1));
        Rate = ListenPreferences.Rate;
        _consecutiveSkips = 0;
        SkipNotice = null;
        StatusMessage = null;
        ActiveHighlight = null;
        _lastSpokenChapter = null;
        _hasSpokenSegment = false;
        IsActive = true;
        IsPaused = false;
        var token = Interlocked.Increment(ref _generation);
        _playCts = new CancellationTokenSource();
        var ct = _playCts.Token;
        Emit();
        _ = Task.Run(() => RunLoopAsync(token, ct));
    }

    public void TogglePause()
    {
        if (!IsActive || _engine is null) return;
        if (_engine.IsPaused)
        {
            _engine.Resume();
            IsPaused = false;
            IsPlaying = true;
        }
        else
        {
            _engine.Pause();
            IsPaused = true;
            IsPlaying = false;
        }
        Emit();
    }

    public void SkipForward()
    {
        if (IsActive) Jump(CurrentIdx + 1);
    }

    public void SkipBack()
    {
        if (IsActive) Jump(Math.Max(0, CurrentIdx - 1));
    }

    public void SetRate(float rate)
    {
        Rate = ListenPreferences.SnapRate(rate);
        ListenPreferences.Rate = Rate;
        if (IsActive) Jump(CurrentIdx);
        else Emit();
    }

    public void Jump(int idx)
    {
        if (!IsActive) return;
        Interlocked.Increment(ref _generation);
        _engine?.Stop();
        _consecutiveSkips = 0;
        SkipNotice = null;
        CurrentIdx = Math.Clamp(idx, 0, Math.Max(0, _segmentCount - 1));
        _playCts?.Cancel();
        _playCts = new CancellationTokenSource();
        var token = _generation;
        var ct = _playCts.Token;
        Emit();
        _ = Task.Run(() => RunLoopAsync(token, ct));
    }

    public void Stop()
    {
        Interlocked.Increment(ref _generation);
        _playCts?.Cancel();
        _playCts = null;
        _engine?.Stop();
        _engine?.Dispose();
        _engine = null;
        IsActive = false;
        IsPlaying = false;
        IsPaused = false;
        IsLoading = false;
        StatusMessage = null;
        SkipNotice = null;
        ActiveHighlight = null;
        _consecutiveSkips = 0;
        _lastSpokenChapter = null;
        _hasSpokenSegment = false;
        Emit();
    }

    public void Dispose() => Stop();

    private async Task RunLoopAsync(int token, CancellationToken ct)
    {
        try
        {
            while (token == _generation && IsActive && !ct.IsCancellationRequested)
            {
                if (CurrentIdx >= _segmentCount)
                {
                    StatusMessage = "已听完";
                    IsPlaying = false;
                    IsLoading = false;
                    Emit();
                    return;
                }
                IsLoading = true;
                ActiveHighlight = null;
                var idx = CurrentIdx;
                SegmentLabel = _labelFor?.Invoke(idx) ?? $"段 {idx + 1}";
                Highlight(idx);
                Emit();
                ListenChapterSpeakContext chapterContext = _hasSpokenSegment
                    ? new ListenChapterSpeakContext.Continuing(_lastSpokenChapter)
                    : new ListenChapterSpeakContext.SessionStart();
                var script = _resolve is null
                    ? ListenScript.NotReady(Mode, "summary_not_ready")
                    : await _resolve(idx, Mode, chapterContext, ct).ConfigureAwait(false);
                if (token != _generation) return;

                var decision = ListenAdvancePolicy.Decide(
                    idx,
                    _segmentCount,
                    script.Ready && script.Texts.Count > 0,
                    script.SkipReason,
                    _consecutiveSkips);
                switch (decision)
                {
                    case ListenAdvanceDecision.Finished:
                        StatusMessage = "已听完";
                        IsLoading = false;
                        IsPlaying = false;
                        ActiveHighlight = null;
                        Emit();
                        return;
                    case ListenAdvanceDecision.PauseTooManySkips:
                        SkipNotice = SkipMessage(idx, script.SkipReason);
                        StatusMessage = "连续多段无法朗读，已暂停";
                        IsLoading = false;
                        IsPlaying = false;
                        IsPaused = true;
                        ActiveHighlight = null;
                        Emit();
                        return;
                    case ListenAdvanceDecision.Skip skip:
                        _consecutiveSkips += 1;
                        SkipNotice = SkipMessage(idx, skip.Reason);
                        CurrentIdx = skip.Idx;
                        Emit();
                        continue;
                }

                _consecutiveSkips = 0;
                SkipNotice = null;
                _lastSpokenChapter = ListenChapterAnnouncePolicy.NormalizedChapter(_chapterFor?.Invoke(idx));
                _hasSpokenSegment = true;
                IsLoading = false;
                IsPaused = false;
                IsPlaying = true;
                Emit();
                _engine?.Stop();
                _engine?.Dispose();
                var engine = _makeEngine?.Invoke() ?? new SystemNeuralEngine();
                _engine = engine;
                var utterances = script.Utterances;
                try
                {
                    await engine.SpeakAsync(
                        new ListenSpeakRequest(script.Texts, script.Language, Rate, _bookId, idx, Mode),
                        ct,
                        utteranceIndex =>
                        {
                            if (token != _generation) return;
                            if (utteranceIndex < 0 || utteranceIndex >= utterances.Count) return;
                            ActiveHighlight = utterances[utteranceIndex].Anchor;
                            Emit();
                        }).ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    return;
                }
                catch (Exception ex)
                {
                    if (token != _generation) return;
                    StatusMessage = ex.Message;
                    IsPlaying = false;
                    IsLoading = false;
                    ActiveHighlight = null;
                    Emit();
                    return;
                }
                if (token != _generation || !IsActive) return;
                CurrentIdx = idx + 1;
            }
            if (CurrentIdx >= _segmentCount)
            {
                StatusMessage = "已听完";
                IsPlaying = false;
                ActiveHighlight = null;
                Emit();
            }
        }
        catch (OperationCanceledException)
        {
            // Stopped by the user.
        }
    }

    private void Highlight(int idx)
    {
        void Fire() => HighlightSegment?.Invoke(idx);
        if (_dq.HasThreadAccess) Fire();
        else _dq.TryEnqueue(Fire);
    }

    private void Emit()
    {
        void Fire() => Changed?.Invoke(this, EventArgs.Empty);
        if (_dq.HasThreadAccess) Fire();
        else _dq.TryEnqueue(Fire);
    }

    private static string SkipMessage(int idx, string? reason)
    {
        var n = idx + 1;
        return reason switch
        {
            "empty_text" => $"第 {n} 段没有可朗读的原文，已跳过",
            "missing_segment" => $"第 {n} 段不存在，已跳过",
            _ => $"第 {n} 段尚无摘要，已跳过",
        };
    }
}
