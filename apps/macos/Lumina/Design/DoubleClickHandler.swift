import AppKit
import SwiftUI

/// AppKit bridge for double-click on List rows without blocking single-click selection.
struct DoubleClickHandler: NSViewRepresentable {
    var onDoubleClick: () -> Void

    func makeNSView(context: Context) -> NSView {
        let view = DoubleClickNSView()
        view.onDoubleClick = onDoubleClick
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        (nsView as? DoubleClickNSView)?.onDoubleClick = onDoubleClick
    }

    private final class DoubleClickNSView: NSView {
        var onDoubleClick: (() -> Void)?

        override func mouseDown(with event: NSEvent) {
            super.mouseDown(with: event)
            if event.clickCount == 2 {
                onDoubleClick?()
            }
        }
    }
}
