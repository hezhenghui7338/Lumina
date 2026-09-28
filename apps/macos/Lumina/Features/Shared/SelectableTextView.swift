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
    /// Debounce rapid width changes (system fullscreen / live resize) so every
    /// animation frame does not sync-ensureLayout long CJK on MainActor.
    static let widthSettleNanoseconds: UInt64 = 80_000_000

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

    /// First layout must measure immediately; subsequent width churn is deferred.
    static func shouldInvalidateIntrinsicsImmediately(isFirstLayout: Bool) -> Bool {
        isFirstLayout
    }

    static var widthSettleSeconds: TimeInterval {
        Double(widthSettleNanoseconds) / 1_000_000_000
    }
}

/// Invalidates deferred NSTextView intrinsic work when search seeks far
/// (old neighbour layouts must not ensureLayout after the jump).
enum LuminaTextLayoutGeneration {
    private(set) static var current: UInt64 = 0

    static func bump() {
        current &+= 1
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
    /// Search uses a stronger tint; listen follow-along uses a lighter bar.
    var highlightStyle: TextHighlightStyle = .search

    enum TextHighlightStyle: Equatable {
        case search
        case listen

        var backgroundNSColor: NSColor {
            switch self {
            case .search:
                return NSColor(LuminaTheme.accent).withAlphaComponent(0.35)
            case .listen:
                return NSColor(LuminaTheme.listenFollowHighlight)
            }
        }
    }

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
            || abs(textView.appliedLineSpacing - lineSpacing) > 0.001
        if textChanged {
            textView.textStorage?.setAttributedString(attributed)
            textView.appliedLineSpacing = lineSpacing
            textView.invalidateIntrinsicContentSizeNow()
        }
        Self.applyHighlight(
            highlightUTF16,
            style: highlightStyle,
            on: textView,
            textChanged: textChanged
        )
    }

    private static func applyHighlight(
        _ range: NSRange?,
        style: TextHighlightStyle,
        on textView: LuminaSelectableTextView,
        textChanged: Bool
    ) {
        guard let layoutManager = textView.layoutManager else { return }
        let length = textView.string.utf16.count
        let full = NSRange(location: 0, length: length)
        let previous = textView.appliedHighlightUTF16
        let previousStyle = textView.appliedHighlightStyle
        let sameRange = previous == range && previousStyle == style
        if textChanged || !sameRange {
            if full.length > 0 {
                layoutManager.removeTemporaryAttribute(.backgroundColor, forCharacterRange: full)
            }
            if let range, NSMaxRange(range) <= length, range.length > 0 {
                layoutManager.addTemporaryAttribute(
                    .backgroundColor,
                    value: style.backgroundNSColor,
                    forCharacterRange: range
                )
                textView.appliedHighlightUTF16 = range
                textView.appliedHighlightStyle = style
                // Search jumps to the hit; listen follow-along must not scroll
                // (PRD §5.3.1 / ListenFollowHighlightPolicy.scrollsUtteranceIntoView).
                if style == .search {
                    DispatchQueue.main.async {
                        reveal(range, in: textView)
                    }
                }
            } else {
                textView.appliedHighlightUTF16 = nil
                textView.appliedHighlightStyle = nil
            }
        }
    }

    private static func reveal(_ range: NSRange, in textView: NSTextView) {
        guard let layoutManager = textView.layoutManager,
              let textContainer = textView.textContainer,
              textView.window != nil
        else { return }
        // Bound layout to the hit — full-container ensureLayout freezes long CJK
        // segments on every search-next.
        layoutManager.ensureGlyphs(forCharacterRange: range)
        let glyphRange = layoutManager.glyphRange(
            forCharacterRange: range,
            actualCharacterRange: nil
        )
        guard glyphRange.location != NSNotFound, glyphRange.length > 0 else { return }
        layoutManager.ensureLayout(forGlyphRange: glyphRange)
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
    private var settledIntrinsicHeight: CGFloat?
    private var intrinsicInvalidationPending = false
    private var pendingInvalidateWorkItem: DispatchWorkItem?
    var appliedHighlightUTF16: NSRange?
    var appliedHighlightStyle: LuminaSelectableText.TextHighlightStyle?
    var appliedLineSpacing: CGFloat = 0

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
        if window == nil {
            LuminaSelectionActionPopover.dismissIfPresenting(from: self)
            pendingInvalidateWorkItem?.cancel()
            pendingInvalidateWorkItem = nil
            intrinsicInvalidationPending = false
            return
        }
        // Align with layout(): only invalidate when width actually changed.
        // Unconditional invalidate:true freezes on system fullscreen space switches.
        let widthChanged = LuminaTextLayoutSizing.widthDidChange(
            from: lastLayoutWidth,
            to: bounds.width
        )
        applyLayoutWidth(bounds.width, invalidate: widthChanged)
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
        if intrinsicInvalidationPending, let settled = settledIntrinsicHeight {
            return NSSize(width: NSView.noIntrinsicMetric, height: settled)
        }
        layoutManager.ensureLayout(for: textContainer)
        let usedRect = layoutManager.usedRect(for: textContainer)
        let height = LuminaTextLayoutSizing.intrinsicHeight(
            usedRectHeight: usedRect.height,
            containerWidth: width
        )
        settledIntrinsicHeight = height
        return NSSize(
            width: NSView.noIntrinsicMetric,
            height: height
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
        let isFirstLayout = lastLayoutWidth < 0
        let sizeChanged = LuminaTextLayoutSizing.widthDidChange(
            from: textContainer.containerSize.width,
            to: layoutWidth
        )
        guard sizeChanged || isFirstLayout else { return }
        textContainer.containerSize = NSSize(
            width: layoutWidth,
            height: CGFloat.greatestFiniteMagnitude
        )
        lastLayoutWidth = layoutWidth
        if invalidate {
            if LuminaTextLayoutSizing.shouldInvalidateIntrinsicsImmediately(
                isFirstLayout: isFirstLayout
            ) {
                invalidateIntrinsicContentSizeNow()
            } else {
                scheduleDebouncedIntrinsicInvalidation()
            }
        }
    }

    func invalidateIntrinsicContentSizeNow() {
        pendingInvalidateWorkItem?.cancel()
        pendingInvalidateWorkItem = nil
        intrinsicInvalidationPending = false
        invalidateIntrinsicContentSize()
        superview?.invalidateIntrinsicContentSize()
    }

    private func scheduleDebouncedIntrinsicInvalidation() {
        intrinsicInvalidationPending = true
        pendingInvalidateWorkItem?.cancel()
        let generation = LuminaTextLayoutGeneration.current
        let work = DispatchWorkItem { [weak self] in
            guard let self else { return }
            self.intrinsicInvalidationPending = false
            self.pendingInvalidateWorkItem = nil
            // Search far-seek bumped generation: skip stale ensureLayout.
            guard generation == LuminaTextLayoutGeneration.current else { return }
            self.invalidateIntrinsicContentSize()
            self.superview?.invalidateIntrinsicContentSize()
        }
        pendingInvalidateWorkItem = work
        DispatchQueue.main.asyncAfter(
            deadline: .now() + LuminaTextLayoutSizing.widthSettleSeconds,
            execute: work
        )
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
