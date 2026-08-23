import AppKit
import SwiftUI

/// Layout rules for reader NSTextView so CJK with no spaces cannot explode
/// into one-glyph-per-line when SwiftUI briefly proposes width 0.
enum LuminaTextLayoutSizing {
    static let minLayoutWidth: CGFloat = 8
    static let widthChangeEpsilon: CGFloat = 0.5
    static let placeholderHeight: CGFloat = 1
    /// Used before the first real bounds pass so CJK never lays out at width 0.
    static let fallbackLayoutWidth: CGFloat = 640

    static func shouldEnsureLayout(containerWidth: CGFloat) -> Bool {
        containerWidth >= minLayoutWidth
    }

    static func layoutWidth(for viewWidth: CGFloat) -> CGFloat? {
        viewWidth >= minLayoutWidth ? viewWidth : nil
    }

    static func widthDidChange(from previous: CGFloat, to next: CGFloat) -> Bool {
        abs(next - previous) >= widthChangeEpsilon
    }

    static func intrinsicHeight(usedRectHeight: CGFloat, containerWidth: CGFloat) -> CGFloat {
        guard shouldEnsureLayout(containerWidth: containerWidth) else {
            return placeholderHeight
        }
        return ceil(usedRectHeight)
    }
}

/// Non-selectable display text with AppKit intrinsic height (reader body copy).
struct LuminaSelectableText: NSViewRepresentable {
    let text: String
    var fontSize: CGFloat = LuminaTheme.summaryBulletSize
    var fontWeight: NSFont.Weight = .regular
    var lineSpacing: CGFloat = LuminaTheme.summaryBulletLineSpacing
    var foreground: Color = LuminaTheme.textPrimary

    func makeNSView(context: Context) -> IntrinsicSizingTextContainer {
        let container = IntrinsicSizingTextContainer()
        let textView = LuminaSelectableTextView()
        configure(textView)
        container.embed(textView)
        return container
    }

    func updateNSView(_ container: IntrinsicSizingTextContainer, context: Context) {
        guard let textView = container.textView else { return }
        configure(textView)
    }

    private func configure(_ textView: LuminaSelectableTextView) {
        let paragraphStyle = NSMutableParagraphStyle()
        paragraphStyle.lineSpacing = lineSpacing

        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: fontSize, weight: fontWeight),
            .foregroundColor: NSColor(foreground),
            .paragraphStyle: paragraphStyle,
        ]

        let attributed = NSAttributedString(string: text, attributes: attributes)
        if textView.textStorage?.string != text
            || textView.font?.pointSize != fontSize
            || textView.textColor != NSColor(foreground) {
            textView.textStorage?.setAttributedString(attributed)
            textView.invalidateIntrinsicContentSize()
            textView.superview?.invalidateIntrinsicContentSize()
        }
    }
}

// MARK: - AppKit views

final class LuminaSelectableTextView: NSTextView {
    private var lastLayoutWidth: CGFloat = -1

    override var acceptsFirstResponder: Bool { false }

    override func becomeFirstResponder() -> Bool { false }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func resetCursorRects() {
        addCursorRect(bounds, cursor: .arrow)
    }

    override var intrinsicContentSize: NSSize {
        guard let layoutManager, let textContainer else {
            return super.intrinsicContentSize
        }
        let width = textContainer.containerSize.width
        guard LuminaTextLayoutSizing.shouldEnsureLayout(containerWidth: width) else {
            return NSSize(
                width: NSView.noIntrinsicMetric,
                height: LuminaTextLayoutSizing.placeholderHeight
            )
        }
        layoutManager.ensureLayout(for: textContainer)
        let usedRect = layoutManager.usedRect(for: textContainer)
        return NSSize(
            width: NSView.noIntrinsicMetric,
            height: LuminaTextLayoutSizing.intrinsicHeight(
                usedRectHeight: usedRect.height,
                containerWidth: width
            )
        )
    }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        applyLayoutWidth(bounds.width, invalidate: true)
    }

    override func setFrameSize(_ newSize: NSSize) {
        let widthChanged = LuminaTextLayoutSizing.widthDidChange(
            from: lastLayoutWidth,
            to: newSize.width
        )
        super.setFrameSize(newSize)
        applyLayoutWidth(newSize.width, invalidate: widthChanged)
    }

    func applyLayoutWidth(_ width: CGFloat, invalidate: Bool) {
        guard let textContainer else { return }
        guard let layoutWidth = LuminaTextLayoutSizing.layoutWidth(for: width) else { return }
        let sizeChanged = LuminaTextLayoutSizing.widthDidChange(
            from: textContainer.containerSize.width,
            to: layoutWidth
        )
        guard sizeChanged || lastLayoutWidth < 0 else { return }
        textContainer.containerSize = NSSize(
            width: layoutWidth,
            height: CGFloat.greatestFiniteMagnitude
        )
        lastLayoutWidth = layoutWidth
        if invalidate {
            invalidateIntrinsicContentSize()
        }
    }
}

final class IntrinsicSizingTextContainer: NSView {
    private(set) var textView: LuminaSelectableTextView?

    func embed(_ textView: LuminaSelectableTextView) {
        self.textView = textView
        textView.translatesAutoresizingMaskIntoConstraints = false
        textView.isEditable = false
        textView.isSelectable = false
        textView.drawsBackground = false
        textView.isRichText = false
        textView.textContainerInset = NSSize(width: 0, height: 0)
        textView.textContainer?.lineFragmentPadding = 0
        textView.isVerticallyResizable = true
        textView.isHorizontallyResizable = false
        textView.autoresizingMask = [.width]
        textView.textContainer?.widthTracksTextView = false
        textView.textContainer?.containerSize = NSSize(
            width: LuminaTextLayoutSizing.fallbackLayoutWidth,
            height: CGFloat.greatestFiniteMagnitude
        )

        addSubview(textView)
        NSLayoutConstraint.activate([
            textView.leadingAnchor.constraint(equalTo: leadingAnchor),
            textView.trailingAnchor.constraint(equalTo: trailingAnchor),
            textView.topAnchor.constraint(equalTo: topAnchor),
            textView.bottomAnchor.constraint(equalTo: bottomAnchor),
        ])
    }

    override func layout() {
        super.layout()
        textView?.applyLayoutWidth(bounds.width, invalidate: true)
    }

    override var intrinsicContentSize: NSSize {
        guard let textView else { return super.intrinsicContentSize }
        let textHeight = textView.intrinsicContentSize.height
        return NSSize(width: NSView.noIntrinsicMetric, height: textHeight)
    }
}
