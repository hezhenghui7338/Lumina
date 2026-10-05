import AppKit
import Foundation
import OSLog
import SwiftUI

/// Main-thread-only layout diagnostics for system fullscreen / width settle.
/// No locks, no layout side effects, no file I/O — safe on the ensureLayout path.
enum LuminaLayoutPerf {
    static let log = Logger(subsystem: "app.lumina", category: "layout")

    /// Log a single ensureLayout only when it exceeds one frame.
    static let ensureInfoThresholdMs: Double = 16
    /// Escalate when a single measure is likely user-visible freeze.
    static let ensureErrorThresholdMs: Double = 200
    /// Cap per-session detail lines so Console cannot amplify a freeze.
    static let maxEnsureDetailLogsPerSession: Int = 20
    /// Aggregate fan-out after the first slow ensure in a burst.
    static let fanOutWindowSeconds: TimeInterval = 0.15
    /// Flush session totals after didEnter/didExit so late work is counted.
    static let sessionFlushDelaySeconds: TimeInterval = 0.3
    /// Main-thread gap that counts as a stall during a fullscreen session.
    static let stallThresholdMs: Double = 50
    /// Cap stall detail lines per session.
    static let maxStallDetailLogsPerSession: Int = 30

    enum Phase: String {
        case makeNSView
        case updateNSView
        case configure
        case setFrameSize
        case viewDidMove
        case containerLayout
        case applyLayoutWidth
        case invalidateNow
        case intrinsic
        case ensureLayout
        case viewportSettle
        // Reader / SwiftUI feed (outside NSTextView)
        case readerSegmentBlock
        case readerSegmentBody
        case readerPreference
        case readerContentMode
        case readerFeedLayout
        case readerFeedSetFrame
        case readerFeedMoveWindow
        case readerScrollDocLayout
        case readerScrollLayout
    }

    private static var installed = false
    private static var observerTokens: [NSObjectProtocol] = []
    private static var runLoopObserver: CFRunLoopObserver?

    private static var sessionId: UInt64 = 0
    private static var sessionActive = false
    private static var sessionKind: String = ""
    private static var sessionStartedAt: CFAbsoluteTime = 0
    private static var sessionEnsureCount: Int = 0
    private static var sessionEnsureTotalMs: Double = 0
    private static var sessionEnsureMaxMs: Double = 0
    private static var sessionEnsureMaxChars: Int = 0
    private static var sessionEnsureDetailLogs: Int = 0
    private static var sessionWidthSettleCount: Int = 0
    private static var sessionWidthSettleImmediate: Int = 0
    private static var sessionWidthSettleDebounce: Int = 0
    private static var sessionViewportSettleCount: Int = 0
    private static var sessionDetachCount: Int = 0
    private static var sessionAttachCount: Int = 0
    private static var sessionMakeCount: Int = 0
    private static var sessionUpdateCount: Int = 0
    private static var sessionImmediateFirstLayout: Int = 0
    private static var sessionSegmentBlockCount: Int = 0
    private static var sessionSegmentBodyCount: Int = 0
    private static var sessionPreferenceCount: Int = 0
    private static var sessionContentModeCount: Int = 0
    private static var sessionSegmentCountSnapshot: Int = 0
    private static var sessionContentModeSnapshot: String = "-"
    private static var sessionPhaseMs: [String: Double] = [:]
    private static var sessionPhaseCount: [String: Int] = [:]
    private static var sessionLastPhase: String = "-"
    private static var sessionLastPhaseAt: CFAbsoluteTime = 0
    private static var sessionStallCount: Int = 0
    private static var sessionStallTotalMs: Double = 0
    private static var sessionStallMaxMs: Double = 0
    private static var sessionStallDetailLogs: Int = 0
    private static var sessionRunLoopLastAt: CFAbsoluteTime = 0
    private static var sessionFlushWorkItem: DispatchWorkItem?

    private static var fanOutActive = false
    private static var fanOutCount: Int = 0
    private static var fanOutTotalMs: Double = 0
    private static var fanOutMaxMs: Double = 0
    private static var fanOutFlushWorkItem: DispatchWorkItem?
    /// Accumulates inclusive nested child time so phase totals stay exclusive.
    private static var activeNestedMs: Double = 0

    static func installWindowObserversIfNeeded() {
        guard !installed else { return }
        installed = true
        let center = NotificationCenter.default
        let names: [(Notification.Name, String)] = [
            (NSWindow.willEnterFullScreenNotification, "willEnter"),
            (NSWindow.didEnterFullScreenNotification, "didEnter"),
            (NSWindow.willExitFullScreenNotification, "willExit"),
            (NSWindow.didExitFullScreenNotification, "didExit"),
        ]
        for (name, kind) in names {
            let token = center.addObserver(
                forName: name,
                object: nil,
                queue: .main
            ) { _ in
                handleFullscreen(kind)
            }
            observerTokens.append(token)
        }
        installRunLoopObserverIfNeeded()
    }

    /// Time an instrumented phase. Always accumulates during an active session;
    /// never logs per call (session summary + stall detector carry the signal).
    /// Nested traces record exclusive time so instrumented_ms does not double-count.
    static func trace(_ phase: Phase, _ body: () -> Void) {
        guard sessionActive else {
            body()
            return
        }
        let started = CFAbsoluteTimeGetCurrent()
        let parentNested = activeNestedMs
        activeNestedMs = 0
        body()
        let totalMs = (CFAbsoluteTimeGetCurrent() - started) * 1000
        let childMs = activeNestedMs
        let exclusiveMs = max(0, totalMs - childMs)
        activeNestedMs = parentNested + totalMs
        recordPhase(phase, ms: exclusiveMs)
    }

    static func noteWidthSettle(immediate: Bool) {
        guard sessionActive else { return }
        sessionWidthSettleCount &+= 1
        if immediate {
            sessionWidthSettleImmediate &+= 1
            sessionImmediateFirstLayout &+= 1
        } else {
            sessionWidthSettleDebounce &+= 1
        }
    }

    static func noteDebounceFired(cancelledByGeneration: Bool) {
        guard cancelledByGeneration, sessionActive else { return }
        // Rare; keep one-line visibility without per-view spam.
        log.info("width settle debounce skipped stale generation session=\(sessionId)")
    }

    static func noteViewDidMoveToWindow(hasWindow: Bool) {
        guard sessionActive else { return }
        if hasWindow {
            sessionAttachCount &+= 1
        } else {
            sessionDetachCount &+= 1
        }
    }

    static func noteViewportSettle(committed: Bool) {
        guard sessionActive else { return }
        sessionViewportSettleCount &+= 1
        _ = committed
    }

    static func noteReaderSegmentBlock() {
        guard sessionActive else { return }
        sessionSegmentBlockCount &+= 1
        touch(.readerSegmentBlock)
    }

    static func noteReaderSegmentBody() {
        guard sessionActive else { return }
        sessionSegmentBodyCount &+= 1
        touch(.readerSegmentBody)
    }

    static func noteReaderPreference() {
        guard sessionActive else { return }
        sessionPreferenceCount &+= 1
    }

    static func noteReaderContentMode() {
        guard sessionActive else { return }
        sessionContentModeCount &+= 1
    }

    static func noteReaderContext(segmentCount: Int, contentMode: String) {
        guard sessionActive else { return }
        sessionSegmentCountSnapshot = segmentCount
        sessionContentModeSnapshot = contentMode
    }

    /// Breadcrumb only — updates last_phase without attributing duration.
    static func touch(_ phase: Phase) {
        guard sessionActive else { return }
        sessionLastPhase = phase.rawValue
        sessionLastPhaseAt = CFAbsoluteTimeGetCurrent()
        sessionPhaseCount[phase.rawValue, default: 0] &+= 1
    }

    static func noteMakeNSView() {
        guard sessionActive else { return }
        sessionMakeCount &+= 1
    }

    static func noteUpdateNSView() {
        guard sessionActive else { return }
        sessionUpdateCount &+= 1
    }

    /// Time `body` (the ensureLayout path). Fast paths still accumulate session totals
    /// without calling Logger when under the info threshold.
    static func traceEnsureLayout(
        chars: Int,
        width: CGFloat,
        pendingFastPath: Bool,
        _ body: () -> Void
    ) {
        guard sessionActive else {
            let started = CFAbsoluteTimeGetCurrent()
            body()
            let ms = (CFAbsoluteTimeGetCurrent() - started) * 1000
            recordEnsure(ms: ms, chars: chars, width: width, pendingFastPath: pendingFastPath)
            return
        }
        let started = CFAbsoluteTimeGetCurrent()
        let parentNested = activeNestedMs
        activeNestedMs = 0
        body()
        let totalMs = (CFAbsoluteTimeGetCurrent() - started) * 1000
        let childMs = activeNestedMs
        let exclusiveMs = max(0, totalMs - childMs)
        activeNestedMs = parentNested + totalMs
        recordPhase(.ensureLayout, ms: exclusiveMs)
        recordEnsure(ms: totalMs, chars: chars, width: width, pendingFastPath: pendingFastPath)
    }

    private static func recordPhase(_ phase: Phase, ms: Double) {
        guard sessionActive else { return }
        let key = phase.rawValue
        sessionPhaseMs[key, default: 0] += ms
        sessionPhaseCount[key, default: 0] &+= 1
        sessionLastPhase = key
        sessionLastPhaseAt = CFAbsoluteTimeGetCurrent()
    }

    private static func recordEnsure(
        ms: Double,
        chars: Int,
        width: CGFloat,
        pendingFastPath: Bool
    ) {
        if sessionActive {
            sessionEnsureCount &+= 1
            sessionEnsureTotalMs += ms
            if ms > sessionEnsureMaxMs {
                sessionEnsureMaxMs = ms
                sessionEnsureMaxChars = chars
            }
        }

        if ms >= ensureInfoThresholdMs {
            bumpFanOut(ms: ms)
            let allowDetail: Bool
            if sessionActive {
                allowDetail = sessionEnsureDetailLogs < maxEnsureDetailLogsPerSession
                if allowDetail {
                    sessionEnsureDetailLogs &+= 1
                }
            } else {
                allowDetail = true
            }
            if allowDetail {
                if ms >= ensureErrorThresholdMs {
                    log.error(
                        "ensureLayout chars=\(chars) width=\(width, format: .fixed(precision: 1)) ms=\(ms, format: .fixed(precision: 1)) pending=\(pendingFastPath) session=\(sessionId)"
                    )
                } else {
                    log.info(
                        "ensureLayout chars=\(chars) width=\(width, format: .fixed(precision: 1)) ms=\(ms, format: .fixed(precision: 1)) pending=\(pendingFastPath) session=\(sessionId)"
                    )
                }
            }
        } else if fanOutActive {
            bumpFanOut(ms: ms)
        }
    }

    private static func bumpFanOut(ms: Double) {
        if !fanOutActive {
            fanOutActive = true
            fanOutCount = 0
            fanOutTotalMs = 0
            fanOutMaxMs = 0
        }
        fanOutCount &+= 1
        fanOutTotalMs += ms
        fanOutMaxMs = max(fanOutMaxMs, ms)
        fanOutFlushWorkItem?.cancel()
        let work = DispatchWorkItem {
            flushFanOut()
        }
        fanOutFlushWorkItem = work
        DispatchQueue.main.asyncAfter(
            deadline: .now() + fanOutWindowSeconds,
            execute: work
        )
    }

    private static func flushFanOut() {
        guard fanOutActive else { return }
        fanOutActive = false
        fanOutFlushWorkItem = nil
        guard fanOutCount > 0 else { return }
        log.info(
            "batch ensure_count=\(fanOutCount) total_ms=\(fanOutTotalMs, format: .fixed(precision: 1)) max_ms=\(fanOutMaxMs, format: .fixed(precision: 1)) session=\(sessionId)"
        )
        fanOutCount = 0
        fanOutTotalMs = 0
        fanOutMaxMs = 0
    }

    private static func installRunLoopObserverIfNeeded() {
        guard runLoopObserver == nil else { return }
        let observer = CFRunLoopObserverCreateWithHandler(
            kCFAllocatorDefault,
            CFRunLoopActivity.beforeWaiting.rawValue | CFRunLoopActivity.afterWaiting.rawValue,
            true,
            0
        ) { _, activity in
            handleRunLoop(activity)
        }
        runLoopObserver = observer
        if let observer {
            CFRunLoopAddObserver(CFRunLoopGetMain(), observer, .commonModes)
        }
    }

    private static func handleRunLoop(_ activity: CFRunLoopActivity) {
        guard sessionActive else { return }
        let now = CFAbsoluteTimeGetCurrent()
        if sessionRunLoopLastAt > 0, activity == .beforeWaiting {
            let gapMs = (now - sessionRunLoopLastAt) * 1000
            if gapMs >= stallThresholdMs {
                sessionStallCount &+= 1
                sessionStallTotalMs += gapMs
                sessionStallMaxMs = max(sessionStallMaxMs, gapMs)
                if sessionStallDetailLogs < maxStallDetailLogsPerSession {
                    sessionStallDetailLogs &+= 1
                    let sincePhaseMs = sessionLastPhaseAt > 0
                        ? (now - sessionLastPhaseAt) * 1000
                        : -1
                    log.error(
                        "mainStall ms=\(gapMs, format: .fixed(precision: 1)) last_phase=\(sessionLastPhase, privacy: .public) since_phase_ms=\(sincePhaseMs, format: .fixed(precision: 1)) segs=\(sessionSegmentCountSnapshot) mode=\(sessionContentModeSnapshot, privacy: .public) seg_block=\(sessionSegmentBlockCount) seg_body=\(sessionSegmentBodyCount) pref=\(sessionPreferenceCount) session=\(sessionId)"
                    )
                }
            }
        }
        sessionRunLoopLastAt = now
    }

    private static func handleFullscreen(_ kind: String) {
        switch kind {
        case "willEnter", "willExit":
            beginSession(kind: kind)
        case "didEnter", "didExit":
            scheduleSessionFlush(kind: kind)
        default:
            break
        }
        NotificationCenter.default.post(
            name: .luminaFullscreenTransition,
            object: nil,
            userInfo: ["kind": kind]
        )
    }

    private static func beginSession(kind: String) {
        sessionFlushWorkItem?.cancel()
        sessionFlushWorkItem = nil
        flushFanOut()
        sessionId &+= 1
        sessionActive = true
        sessionKind = kind
        sessionStartedAt = CFAbsoluteTimeGetCurrent()
        sessionEnsureCount = 0
        sessionEnsureTotalMs = 0
        sessionEnsureMaxMs = 0
        sessionEnsureMaxChars = 0
        sessionEnsureDetailLogs = 0
        sessionWidthSettleCount = 0
        sessionWidthSettleImmediate = 0
        sessionWidthSettleDebounce = 0
        sessionViewportSettleCount = 0
        sessionDetachCount = 0
        sessionAttachCount = 0
        sessionMakeCount = 0
        sessionUpdateCount = 0
        sessionImmediateFirstLayout = 0
        sessionSegmentBlockCount = 0
        sessionSegmentBodyCount = 0
        sessionPreferenceCount = 0
        sessionContentModeCount = 0
        sessionSegmentCountSnapshot = 0
        sessionContentModeSnapshot = "-"
        sessionPhaseMs = [:]
        sessionPhaseCount = [:]
        sessionLastPhase = "-"
        sessionLastPhaseAt = sessionStartedAt
        sessionStallCount = 0
        sessionStallTotalMs = 0
        sessionStallMaxMs = 0
        sessionStallDetailLogs = 0
        sessionRunLoopLastAt = sessionStartedAt
        activeNestedMs = 0
        log.info("fullscreen \(kind, privacy: .public) id=\(sessionId)")
    }

    private static func scheduleSessionFlush(kind: String) {
        log.info("fullscreen \(kind, privacy: .public) id=\(sessionId)")
        sessionFlushWorkItem?.cancel()
        let work = DispatchWorkItem {
            endSession(didKind: kind)
        }
        sessionFlushWorkItem = work
        DispatchQueue.main.asyncAfter(
            deadline: .now() + sessionFlushDelaySeconds,
            execute: work
        )
    }

    private static func endSession(didKind: String) {
        sessionFlushWorkItem = nil
        flushFanOut()
        guard sessionActive else { return }
        let elapsedMs = (CFAbsoluteTimeGetCurrent() - sessionStartedAt) * 1000
        let instrumentedMs = sessionPhaseMs.values.reduce(0, +)
        let unaccountedMs = max(0, elapsedMs - instrumentedMs)
        let phaseSummary = sessionPhaseMs
            .sorted { $0.value > $1.value }
            .prefix(8)
            .map { key, ms in
                let count = sessionPhaseCount[key] ?? 0
                return "\(key)=\(String(format: "%.1f", ms))ms×\(count)"
            }
            .joined(separator: " ")
        log.info(
            "fullscreen session id=\(sessionId) will=\(sessionKind, privacy: .public) did=\(didKind, privacy: .public) elapsed_ms=\(elapsedMs, format: .fixed(precision: 1)) instrumented_ms=\(instrumentedMs, format: .fixed(precision: 1)) unaccounted_ms=\(unaccountedMs, format: .fixed(precision: 1)) stall_count=\(sessionStallCount) stall_total_ms=\(sessionStallTotalMs, format: .fixed(precision: 1)) stall_max_ms=\(sessionStallMaxMs, format: .fixed(precision: 1)) ensure_count=\(sessionEnsureCount) ensure_total_ms=\(sessionEnsureTotalMs, format: .fixed(precision: 1)) ensure_max_ms=\(sessionEnsureMaxMs, format: .fixed(precision: 1)) ensure_max_chars=\(sessionEnsureMaxChars) width_settle=\(sessionWidthSettleCount) immediate=\(sessionWidthSettleImmediate) debounce=\(sessionWidthSettleDebounce) detach=\(sessionDetachCount) attach=\(sessionAttachCount) make=\(sessionMakeCount) update=\(sessionUpdateCount) viewport=\(sessionViewportSettleCount) seg_block=\(sessionSegmentBlockCount) seg_body=\(sessionSegmentBodyCount) pref=\(sessionPreferenceCount) content_mode=\(sessionContentModeCount) segs=\(sessionSegmentCountSnapshot) mode=\(sessionContentModeSnapshot, privacy: .public) phases=\(phaseSummary, privacy: .public)"
        )
        sessionActive = false
    }
}

// MARK: - Reader feed AppKit probes

/// Sits in the reading ScrollView hierarchy so fullscreen layout passes are timed
/// outside LuminaSelectableTextView.
struct LuminaReaderLayoutProbe: NSViewRepresentable {
    var label: String = "feed"

    func makeNSView(context: Context) -> LuminaReaderLayoutProbeNSView {
        let view = LuminaReaderLayoutProbeNSView()
        view.label = label
        return view
    }

    func updateNSView(_ nsView: LuminaReaderLayoutProbeNSView, context: Context) {
        nsView.label = label
    }
}

final class LuminaReaderLayoutProbeNSView: NSView {
    var label: String = "feed"

    override func viewDidMoveToWindow() {
        LuminaLayoutPerf.trace(.readerFeedMoveWindow) {
            super.viewDidMoveToWindow()
        }
    }

    override func setFrameSize(_ newSize: NSSize) {
        LuminaLayoutPerf.trace(.readerFeedSetFrame) {
            super.setFrameSize(newSize)
        }
    }

    override func layout() {
        LuminaLayoutPerf.trace(.readerFeedLayout) {
            super.layout()
            if let scroll = enclosingScrollView {
                LuminaLayoutPerf.trace(.readerScrollLayout) {
                    _ = scroll.bounds
                    _ = scroll.contentSize
                }
                if let doc = scroll.documentView {
                    LuminaLayoutPerf.trace(.readerScrollDocLayout) {
                        _ = doc.bounds
                        _ = doc.subviews.count
                    }
                }
            }
        }
    }
}
