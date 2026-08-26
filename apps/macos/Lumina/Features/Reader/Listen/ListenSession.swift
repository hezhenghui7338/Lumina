import Foundation

enum ListenAdvanceDecision: Equatable {
    case play(Int)
    case skip(idx: Int, reason: String)
    case pauseTooManySkips(idx: Int)
    case finished
}

enum ListenAdvancePolicy {
    static func decide(
        idx: Int,
        segmentCount: Int,
        ready: Bool,
        skipReason: String?,
        consecutiveSkips: Int,
        maxSkips: Int = ListenPreferences.maxConsecutiveSkips
    ) -> ListenAdvanceDecision {
        if idx < 0 || idx >= segmentCount {
            return .finished
        }
        if ready {
            return .play(idx)
        }
        let reason = skipReason ?? "summary_not_ready"
        let skips = consecutiveSkips + 1
        if skips >= maxSkips {
            return .pauseTooManySkips(idx: idx)
        }
        let next = idx + 1
        if next >= segmentCount {
            return .finished
        }
        return .skip(idx: next, reason: reason)
    }
}

@MainActor
final class ListenSession: ObservableObject {
    @Published private(set) var isActive = false
    @Published private(set) var isPlaying = false
    @Published private(set) var isLoading = false
    @Published private(set) var isPaused = false
    @Published private(set) var mode: ListenMode = .summary
    @Published private(set) var currentIdx = 0
    @Published var rate: Float = ListenPreferences.rate
    @Published private(set) var statusMessage: String?
    @Published private(set) var skipNotice: String?
    @Published private(set) var segmentLabel = ""

    var onHighlightSegment: ((Int) -> Void)?

    private var generation = 0
    private var consecutiveSkips = 0
    private var playTask: Task<Void, Never>?
    private var engine: ListenEngine?
    private var bookId = ""
    private var segmentCount = 0
    private var resolve: ((Int, ListenMode) async -> ListenScript)?
    private var labelFor: ((Int) -> String)?
    private var makeEngine: (() -> ListenEngine)?

    func configure(
        bookId: String,
        segmentCount: Int,
        resolve: @escaping (Int, ListenMode) async -> ListenScript,
        labelFor: @escaping (Int) -> String,
        makeEngine: @escaping () -> ListenEngine
    ) {
        self.bookId = bookId
        self.segmentCount = segmentCount
        self.resolve = resolve
        self.labelFor = labelFor
        self.makeEngine = makeEngine
    }

    func updateSegmentCount(_ count: Int) {
        segmentCount = count
    }

    func start(mode: ListenMode, from idx: Int) {
        guard segmentCount > 0, resolve != nil else { return }
        stop()
        self.mode = mode
        currentIdx = max(0, min(idx, segmentCount - 1))
        rate = ListenPreferences.rate
        consecutiveSkips = 0
        skipNotice = nil
        statusMessage = nil
        isActive = true
        generation += 1
        let token = generation
        playTask = Task { [weak self] in
            await self?.runLoop(token: token)
        }
    }

    func togglePause() {
        guard isActive, let engine else { return }
        if engine.isPaused {
            engine.resume()
            isPaused = false
            isPlaying = true
        } else {
            engine.pause()
            isPaused = true
            isPlaying = false
        }
    }

    func skipForward() {
        guard isActive else { return }
        jump(to: currentIdx + 1)
    }

    func skipBack() {
        guard isActive else { return }
        jump(to: max(0, currentIdx - 1))
    }

    func setRate(_ newRate: Float) {
        rate = newRate
        ListenPreferences.rate = newRate
        if isActive {
            jump(to: currentIdx)
        }
    }

    func jump(to idx: Int) {
        guard isActive else { return }
        generation += 1
        engine?.stop()
        consecutiveSkips = 0
        skipNotice = nil
        currentIdx = max(0, min(idx, max(segmentCount - 1, 0)))
        let token = generation
        playTask?.cancel()
        playTask = Task { [weak self] in
            await self?.runLoop(token: token)
        }
    }

    func stop() {
        generation += 1
        playTask?.cancel()
        playTask = nil
        engine?.stop()
        engine = nil
        isActive = false
        isPlaying = false
        isPaused = false
        isLoading = false
        statusMessage = nil
        skipNotice = nil
        consecutiveSkips = 0
    }

    private func runLoop(token: Int) async {
        while token == generation, isActive {
            if currentIdx >= segmentCount {
                statusMessage = "已听完"
                isPlaying = false
                isLoading = false
                return
            }
            isLoading = true
            statusMessage = nil
            let idx = currentIdx
            segmentLabel = labelFor?(idx) ?? "段 \(idx + 1)"
            onHighlightSegment?(idx)
            let script = await resolve?(idx, mode) ?? .notReady(mode, reason: "summary_not_ready")
            guard token == generation else { return }

            let decision = ListenAdvancePolicy.decide(
                idx: idx,
                segmentCount: segmentCount,
                ready: script.ready && !script.texts.isEmpty,
                skipReason: script.skipReason,
                consecutiveSkips: consecutiveSkips
            )
            switch decision {
            case .finished:
                statusMessage = "已听完"
                isLoading = false
                isPlaying = false
                return
            case .pauseTooManySkips:
                skipNotice = skipMessage(for: idx, reason: script.skipReason)
                statusMessage = "连续多段无法朗读，已暂停"
                isLoading = false
                isPlaying = false
                isPaused = true
                return
            case .skip(let next, let reason):
                consecutiveSkips += 1
                skipNotice = skipMessage(for: idx, reason: reason)
                currentIdx = next
                continue
            case .play:
                consecutiveSkips = 0
                skipNotice = nil
            }

            isLoading = false
            isPaused = false
            isPlaying = true
            let engine = makeEngine?() ?? SystemNeuralEngine()
            self.engine = engine
            do {
                try await engine.speak(
                    ListenSpeakRequest(
                        texts: script.texts,
                        language: script.language,
                        rate: rate,
                        bookId: bookId,
                        idx: idx,
                        mode: mode
                    )
                )
            } catch is CancellationError {
                return
            } catch {
                if error.isCancellation { return }
                statusMessage = error.localizedDescription
                isPlaying = false
                isLoading = false
                return
            }
            guard token == generation, isActive else { return }
            currentIdx = idx + 1
        }
        if currentIdx >= segmentCount {
            statusMessage = "已听完"
            isPlaying = false
        }
    }

    private func skipMessage(for idx: Int, reason: String?) -> String {
        let n = idx + 1
        switch reason {
        case "empty_text":
            return "第 \(n) 段没有可朗读的原文，已跳过"
        case "missing_segment":
            return "第 \(n) 段不存在，已跳过"
        default:
            return "第 \(n) 段尚无摘要，已跳过"
        }
    }
}
