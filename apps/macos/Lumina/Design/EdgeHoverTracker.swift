import AppKit
import SwiftUI

/// Tracks pointer position inside a view without stealing ScrollView hits.
struct EdgeHoverTracker: NSViewRepresentable {
    /// Height of the top hot zone (SwiftUI y-down). Zero disables top detection.
    var topHotZone: CGFloat = 0
    /// When true, emit on every mouse move (needed for peek dismiss hit-testing).
    var continuousTracking: Bool = false
    var onUpdate: (CGPoint?, CGSize) -> Void

    func makeNSView(context: Context) -> EdgeTrackingView {
        let view = EdgeTrackingView()
        view.topHotZone = topHotZone
        view.continuousTracking = continuousTracking
        view.onUpdate = onUpdate
        return view
    }

    func updateNSView(_ nsView: EdgeTrackingView, context: Context) {
        nsView.topHotZone = topHotZone
        nsView.continuousTracking = continuousTracking
        nsView.onUpdate = onUpdate
    }
}

final class EdgeTrackingView: NSView {
    var onUpdate: ((CGPoint?, CGSize) -> Void)?
    var topHotZone: CGFloat = 0
    var continuousTracking = false
    private var monitor: Any?
    private var lastKind = 0
    private var lastSize: CGSize = .zero
    private let hotZone: CGFloat = 8

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        removeMonitor()
        guard window != nil else {
            emit(nil, bounds.size, kind: 0, force: true)
            return
        }
        monitor = NSEvent.addLocalMonitorForEvents(matching: [.mouseMoved, .leftMouseDragged]) { [weak self] event in
            self?.reportPointer()
            return event
        }
        reportPointer()
    }

    override func layout() {
        super.layout()
        reportPointer()
    }

    deinit {
        removeMonitor()
    }

    private func removeMonitor() {
        if let monitor {
            NSEvent.removeMonitor(monitor)
            self.monitor = nil
        }
    }

    private func reportPointer() {
        let size = bounds.size
        guard let window else {
            emit(nil, size, kind: 0, force: false)
            return
        }
        let screenPoint = NSEvent.mouseLocation
        let windowPoint = window.convertPoint(fromScreen: screenPoint)
        let viewPoint = convert(windowPoint, from: nil)
        guard size.width > 0, size.height > 0, bounds.contains(viewPoint) else {
            emit(nil, size, kind: 0, force: false)
            return
        }
        // AppKit y-up → SwiftUI y-down
        let point = CGPoint(x: viewPoint.x, y: size.height - viewPoint.y)
        emit(point, size, kind: classify(point, size: size), force: false)
    }

    /// 0 none · 1 left · 2 right · 3 bottom · 4 top
    private func classify(_ point: CGPoint, size: CGSize) -> Int {
        if topHotZone > 0, point.y <= topHotZone { return 4 }
        if point.x <= hotZone { return 1 }
        if point.x >= size.width - hotZone { return 2 }
        if point.y >= size.height - hotZone { return 3 }
        return 0
    }

    private func emit(_ point: CGPoint?, _ size: CGSize, kind: Int, force: Bool) {
        guard force || continuousTracking || kind != lastKind || size != lastSize else { return }
        lastKind = kind
        lastSize = size
        DispatchQueue.main.async { [weak self] in
            self?.onUpdate?(point, size)
        }
    }
}
