import AppKit
import SwiftUI

/// Re-applying `NSToolbar.isVisible` on every SwiftUI `updateNSView`
/// retriggers AppKit help tags even when nothing changed.
enum WindowToolbarVisibilityPolicy {
    static func shouldApply(applied: Bool?, desired: Bool) -> Bool {
        applied != desired
    }
}

/// Toggles the host window toolbar visibility (macOS 14 compatible).
///
/// Only the toolbar row is toggled. `titleVisibility` must stay `.visible`:
/// hiding the title lets content draw under the still-present traffic-light /
/// drag strip, so the top of the floating reader chrome (分段 / 摘要 / …)
/// looks tappable but clicks never reach SwiftUI.
struct WindowToolbarVisibility: NSViewRepresentable {
    var visible: Bool

    func makeNSView(context: Context) -> WindowToolbarVisibilityView {
        let view = WindowToolbarVisibilityView()
        view.setDesiredVisible(visible)
        return view
    }

    func updateNSView(_ nsView: WindowToolbarVisibilityView, context: Context) {
        nsView.setDesiredVisible(visible)
    }
}

final class WindowToolbarVisibilityView: NSView {
    private var applied: Bool?
    private var desired = true

    func setDesiredVisible(_ visible: Bool) {
        desired = visible
        applyIfNeeded()
    }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        applied = nil
        applyIfNeeded()
    }

    private func applyIfNeeded() {
        guard WindowToolbarVisibilityPolicy.shouldApply(applied: applied, desired: desired) else {
            return
        }
        guard window != nil else { return }
        DispatchQueue.main.async { [weak self] in
            guard let self, let window = self.window else { return }
            let visible = self.desired
            guard WindowToolbarVisibilityPolicy.shouldApply(applied: self.applied, desired: visible) else {
                return
            }
            window.toolbar?.isVisible = visible
            window.titleVisibility = .visible
            self.applied = visible
        }
    }
}
