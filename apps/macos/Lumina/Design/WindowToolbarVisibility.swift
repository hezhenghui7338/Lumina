import AppKit
import SwiftUI

/// Toggles the host window toolbar visibility (macOS 14 compatible).
struct WindowToolbarVisibility: NSViewRepresentable {
    var visible: Bool

    func makeNSView(context: Context) -> WindowToolbarVisibilityView {
        let view = WindowToolbarVisibilityView()
        view.isVisible = visible
        return view
    }

    func updateNSView(_ nsView: WindowToolbarVisibilityView, context: Context) {
        nsView.isVisible = visible
    }
}

final class WindowToolbarVisibilityView: NSView {
    var isVisible = true {
        didSet { applyVisibility() }
    }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        applyVisibility()
    }

    private func applyVisibility() {
        guard let window else { return }
        DispatchQueue.main.async { [weak self] in
            guard let self, let window = self.window else { return }
            window.toolbar?.isVisible = self.isVisible
            if self.isVisible {
                window.titleVisibility = .visible
            } else {
                window.titleVisibility = .hidden
            }
        }
    }
}
