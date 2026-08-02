import AppKit
import SwiftUI

/// Selectable, non-editable text with a selection context menu for copy and deep chat.
struct LuminaSelectableText: NSViewRepresentable {
    let text: String
    var fontSize: CGFloat = LuminaTheme.summaryBulletSize
    var fontWeight: NSFont.Weight = .regular
    var lineSpacing: CGFloat = LuminaTheme.summaryBulletLineSpacing
    var foreground: Color = LuminaTheme.textPrimary
    var onSendToChat: ((String) -> Void)?

    func makeCoordinator() -> Coordinator {
        Coordinator(onSendToChat: onSendToChat)
    }

    func makeNSView(context: Context) -> IntrinsicSizingTextContainer {
        let container = IntrinsicSizingTextContainer()
        let textView = LuminaSelectableTextView()
        textView.delegate = context.coordinator
        context.coordinator.textView = textView
        configure(textView)
        container.embed(textView)
        return container
    }

    func updateNSView(_ container: IntrinsicSizingTextContainer, context: Context) {
        guard let textView = container.textView else { return }
        context.coordinator.onSendToChat = onSendToChat
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

    final class Coordinator: NSObject, NSTextViewDelegate {
        weak var textView: LuminaSelectableTextView?
        var onSendToChat: ((String) -> Void)?

        init(onSendToChat: ((String) -> Void)?) {
            self.onSendToChat = onSendToChat
        }

        func textView(_ textView: NSTextView, menu: NSMenu, for event: NSEvent, at charIndex: Int) -> NSMenu? {
            guard textView.selectedRange().length > 0 else { return menu }

            var insertIndex = 0

            let copyItem = NSMenuItem(title: "复制", action: #selector(NSText.copy(_:)), keyEquivalent: "")
            copyItem.target = textView
            menu.insertItem(copyItem, at: insertIndex)
            insertIndex += 1

            if onSendToChat != nil {
                let sendItem = NSMenuItem(
                    title: "发送到深聊",
                    action: #selector(Coordinator.sendToChat(_:)),
                    keyEquivalent: ""
                )
                sendItem.target = self
                menu.insertItem(sendItem, at: insertIndex)
                insertIndex += 1
            }

            if insertIndex > 0 {
                menu.insertItem(NSMenuItem.separator(), at: insertIndex)
            }

            return menu
        }

        @objc func sendToChat(_ sender: Any?) {
            guard let textView, textView.selectedRange().length > 0 else { return }
            let selected = (textView.string as NSString).substring(with: textView.selectedRange())
            let trimmed = selected.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { return }
            onSendToChat?(trimmed)
        }
    }
}

// MARK: - AppKit views

extension Notification.Name {
    /// Posted when the user single-clicks selectable reading text (drag < 5pt).
    static let luminaToggleReaderChrome = Notification.Name("luminaToggleReaderChrome")
}

final class LuminaSelectableTextView: NSTextView {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

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
        textView.isSelectable = true
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
