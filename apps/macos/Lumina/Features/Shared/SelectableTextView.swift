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

/// Mouse-selectable display text with AppKit intrinsic height (reader body copy).
struct LuminaSelectableText: NSViewRepresentable {
    let text: String
    var fontSize: CGFloat = LuminaTheme.summaryBulletSize
    var fontWeight: NSFont.Weight = .regular
    var lineSpacing: CGFloat = LuminaTheme.summaryBulletLineSpacing
    var foreground: Color = LuminaTheme.textPrimary
    var highlightUTF16: NSRange? = nil

    func makeNSView(context: Context) -> IntrinsicSizingTextContainer {
        let container = IntrinsicSizingTextContainer()
        let textView = LuminaSelectableTextView()
        configure(textView)
        applySelectionContext(textView, environment: context.environment)
        container.embed(textView)
        return container
    }

    func updateNSView(_ container: IntrinsicSizingTextContainer, context: Context) {
        guard let textView = container.textView else { return }
        configure(textView)
        applySelectionContext(textView, environment: context.environment)
    }

    private func applySelectionContext(
        _ textView: LuminaSelectableTextView,
        environment: EnvironmentValues
    ) {
        textView.onPlainClick = environment.readerBodyTextPlainClick
        textView.noteClient = environment.readerSelectionNoteClient
        textView.noteAnchor = environment.readerSelectionNoteAnchor
        textView.onNoteSaved = environment.readerSelectionNoteSaved
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
        let textChanged = textView.textStorage?.string != text
            || textView.font?.pointSize != fontSize
            || textView.textColor != NSColor(foreground)
        if textChanged {
            textView.textStorage?.setAttributedString(attributed)
            textView.invalidateIntrinsicContentSize()
            textView.superview?.invalidateIntrinsicContentSize()
        }
        Self.applyHighlight(highlightUTF16, on: textView, textChanged: textChanged)
    }

    private static func applyHighlight(
        _ range: NSRange?,
        on textView: LuminaSelectableTextView,
        textChanged: Bool
    ) {
        guard let layoutManager = textView.layoutManager else { return }
        let length = textView.string.utf16.count
        let full = NSRange(location: 0, length: length)
        let previous = textView.appliedHighlightUTF16
        let sameRange = previous == range
        if textChanged || !sameRange {
            if full.length > 0 {
                layoutManager.removeTemporaryAttribute(.backgroundColor, forCharacterRange: full)
            }
            if let range, NSMaxRange(range) <= length, range.length > 0 {
                layoutManager.addTemporaryAttribute(
                    .backgroundColor,
                    value: NSColor(LuminaTheme.accent).withAlphaComponent(0.35),
                    forCharacterRange: range
                )
                textView.appliedHighlightUTF16 = range
                DispatchQueue.main.async {
                    reveal(range, in: textView)
                }
            } else {
                textView.appliedHighlightUTF16 = nil
            }
        }
    }

    private static func reveal(_ range: NSRange, in textView: NSTextView) {
        guard let layoutManager = textView.layoutManager,
              let textContainer = textView.textContainer,
              textView.window != nil
        else { return }
        layoutManager.ensureLayout(for: textContainer)
        let glyphRange = layoutManager.glyphRange(forCharacterRange: range, actualCharacterRange: nil)
        var rect = layoutManager.boundingRect(forGlyphRange: glyphRange, in: textContainer)
        rect.origin.x += textView.textContainerOrigin.x
        rect.origin.y += textView.textContainerOrigin.y
        let windowRect = textView.convert(rect, to: nil)
        NotificationCenter.default.post(
            name: .luminaRevealTextRect,
            object: nil,
            userInfo: ["rect": NSValue(rect: windowRect)]
        )
    }
}

// MARK: - AppKit views

final class LuminaSelectableTextView: NSTextView {
    private var lastLayoutWidth: CGFloat = -1
    var appliedHighlightUTF16: NSRange?

    var appliedLayoutWidth: CGFloat { lastLayoutWidth }

    /// Where a click that turned out not to be a selection goes, so the reading
    /// surface keeps its chrome toggle. See `LuminaBodyTextClickPolicy`.
    var onPlainClick: (() -> Void)?
    var noteClient: CoreClient?
    var noteAnchor: ReaderSelectionNoteAnchor?
    var onNoteSaved: (() -> Void)?

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func resetCursorRects() {
        addCursorRect(bounds, cursor: .iBeam)
    }

    override func mouseDown(with event: NSEvent) {
        let hadSelectionBefore = selectedRange().length > 0
        // NSTextView runs its own tracking loop here and returns after mouse-up.
        super.mouseDown(with: event)
        let selectedText = currentSelectedText
        let outcome = LuminaBodyTextClickPolicy.outcome(
            clickCount: event.clickCount,
            hadSelectionBefore: hadSelectionBefore,
            selectionLengthAfter: selectedRange().length
        )
        if outcome == .plainClick {
            onPlainClick?()
            return
        }
        if outcome == .dismissSelection {
            LuminaSelectionActionPopover.dismiss()
            return
        }
        guard LuminaSelectionActionPolicy.shouldShowMenu(
            clickOutcome: outcome,
            selectedText: selectedText
        ) else { return }
        guard let quote = LuminaSelectionActionPolicy.capturedQuote(from: selectedText) else {
            return
        }
        LuminaSelectionActionPopover.present(
            quote: quote,
            relativeTo: selectionAnchorRect(),
            of: self,
            core: noteClient,
            anchor: noteAnchor,
            onSaved: onNoteSaved
        )
    }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        applyLayoutWidth(bounds.width, invalidate: true)
        if window == nil {
            LuminaSelectionActionPopover.dismissIfPresenting(from: self)
        }
    }

    private var currentSelectedText: String {
        let range = selectedRange()
        guard range.length > 0 else { return "" }
        let ns = string as NSString
        guard range.location + range.length <= ns.length else { return "" }
        return ns.substring(with: range)
    }

    private func selectionAnchorRect() -> NSRect {
        let range = selectedRange()
        var actual = NSRange()
        let screenRect = firstRect(forCharacterRange: range, actualRange: &actual)
        guard let window, screenRect.width > 0 || screenRect.height > 0 else {
            return NSRect(x: bounds.midX, y: bounds.maxY, width: 1, height: 1)
        }
        let windowRect = window.convertFromScreen(screenRect)
        var local = convert(windowRect, from: nil)
        if local.width < 1 { local.size.width = 1 }
        if local.height < 1 { local.size.height = 1 }
        return local
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
        textView.isSelectable = true
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
        guard let textView else { return }
        let widthChanged = LuminaTextLayoutSizing.widthDidChange(
            from: textView.appliedLayoutWidth,
            to: bounds.width
        )
        textView.applyLayoutWidth(bounds.width, invalidate: widthChanged)
    }

    override var intrinsicContentSize: NSSize {
        guard let textView else { return super.intrinsicContentSize }
        let textHeight = textView.intrinsicContentSize.height
        return NSSize(width: NSView.noIntrinsicMetric, height: textHeight)
    }
}
