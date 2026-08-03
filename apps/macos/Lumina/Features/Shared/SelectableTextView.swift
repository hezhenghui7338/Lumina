import AppKit
import SwiftUI

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
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func resetCursorRects() {
        addCursorRect(bounds, cursor: .arrow)
    }

    override var intrinsicContentSize: NSSize {
        guard let layoutManager, let textContainer else {
            return super.intrinsicContentSize
        }
        layoutManager.ensureLayout(for: textContainer)
        let usedRect = layoutManager.usedRect(for: textContainer)
        return NSSize(width: NSView.noIntrinsicMetric, height: ceil(usedRect.height))
    }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        invalidateIntrinsicContentSize()
    }

    override func setFrameSize(_ newSize: NSSize) {
        super.setFrameSize(newSize)
        invalidateIntrinsicContentSize()
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
        textView.textContainer?.widthTracksTextView = true
        textView.textContainer?.containerSize = NSSize(
            width: 0,
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
        invalidateIntrinsicContentSize()
    }

    override var intrinsicContentSize: NSSize {
        guard let textView else { return super.intrinsicContentSize }
        let textHeight = textView.intrinsicContentSize.height
        return NSSize(width: NSView.noIntrinsicMetric, height: textHeight)
    }
}
