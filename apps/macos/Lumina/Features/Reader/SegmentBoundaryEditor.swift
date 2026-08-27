import AppKit
import SwiftUI

struct SegmentBoundarySheet: View {
    let bookId: String
    let leftIdx: Int
    let core: CoreClient
    var onApplied: (SegmentBoundaryMoveResult, String, String) -> Void
    var onCancel: () -> Void

    @State private var concat = ""
    @State private var originalCut = 0
    @State private var currentCut = 0
    @State private var candidateOffsets: [Int] = []
    @State private var isLoading = true
    @State private var isSaving = false
    @State private var loadError: String?

    private var canSave: Bool {
        SegmentBoundaryOffset.canSave(
            previewCut: currentCut,
            originalCut: originalCut,
            totalChars: concat.unicodeScalars.count,
            isSaving: isSaving
        )
    }

    private var leftText: String {
        SegmentBoundaryOffset.split(concat, unicodeOffset: currentCut).0
    }

    private var rightText: String {
        SegmentBoundaryOffset.split(concat, unicodeOffset: currentCut).1
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("调整分段")
                .font(.title2.weight(.semibold))
            Text("点击正文中要作为新分界的位置。切点会吸附到最近的句子或段落。点「保存」才落库并重新摘要这两段；取消不保存。")
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            if isLoading {
                ProgressView("正在加载原文…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if concat.isEmpty {
                Text(loadError ?? "这两段没有可调整的正文")
                    .foregroundStyle(.orange)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
            } else {
                editorBody
            }

            HStack {
                Spacer()
                Button("取消", role: .cancel) { onCancel() }
                    .disabled(isSaving)
                Button("保存") {
                    Task { await save() }
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
                .disabled(!canSave)
            }
        }
        .padding(24)
        .frame(width: 720, height: 620)
        .interactiveDismissDisabled(isSaving)
        .task { await load() }
    }

    @ViewBuilder
    private var editorBody: some View {
        HStack {
            Text("段 \(leftIdx + 1) · \(leftText.unicodeScalars.count) 字")
            Spacer()
            Text("段 \(leftIdx + 2) · \(rightText.unicodeScalars.count) 字")
        }
        .font(.callout)
        .foregroundStyle(.secondary)

        ZStack {
            SegmentBoundaryClickText(
                text: concat,
                currentCut: currentCut,
                isEnabled: !isSaving,
                onClickUTF16: { utf16 in
                    guard !isSaving else { return }
                    preview(atUTF16: utf16)
                }
            )
            .help("点击预览新分界")
            .accessibilityLabel("拼接原文，点击预览分界")
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(LuminaTheme.border, lineWidth: 1)
            )
            .opacity(isSaving ? 0.45 : 1)

            if isSaving {
                ProgressView("正在保存…")
                    .padding(12)
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
            }
        }

        if let loadError {
            Text(loadError)
                .font(.callout)
                .foregroundStyle(.orange)
        }
    }

    private func load() async {
        isLoading = true
        loadError = nil
        do {
            async let leftTask = core.getSegment(bookId: bookId, idx: leftIdx)
            async let rightTask = core.getSegment(bookId: bookId, idx: leftIdx + 1)
            async let previewTask = core.fetchSegmentBoundary(bookId: bookId, idx: leftIdx)
            let left = try await leftTask
            let right = try await rightTask
            let leftRaw = left.raw_text ?? ""
            let rightRaw = right.raw_text ?? ""
            concat = leftRaw + rightRaw
            originalCut = leftRaw.unicodeScalars.count
            currentCut = originalCut
            candidateOffsets = ((try? await previewTask)?.candidates.map(\.offset)) ?? []
            if concat.isEmpty {
                loadError = "这两段没有可调整的正文"
            }
        } catch {
            loadError = error.localizedDescription
        }
        isLoading = false
    }

    private func preview(atUTF16 utf16Index: Int) {
        let tapped = SegmentBoundaryOffset.unicodeOffset(utf16Index: utf16Index, in: concat)
        let offset = SegmentBoundaryOffset.nearestOffset(tapped, among: candidateOffsets)
        let total = concat.unicodeScalars.count
        if offset <= 0 || offset >= total {
            loadError = "调整后两侧都必须保留正文"
            return
        }
        loadError = nil
        currentCut = offset
    }

    private func save() async {
        guard canSave else { return }
        isSaving = true
        loadError = nil
        do {
            let result = try await core.moveSegmentBoundary(
                bookId: bookId,
                idx: leftIdx,
                leftCharCount: currentCut
            )
            let split = SegmentBoundaryOffset.split(
                concat,
                unicodeOffset: result.left_char_count
            )
            onApplied(result, split.0, split.1)
        } catch {
            loadError = error.localizedDescription
            isSaving = false
        }
    }
}

private struct SegmentBoundaryClickText: NSViewRepresentable {
    let text: String
    let currentCut: Int
    var isEnabled: Bool
    var onClickUTF16: (Int) -> Void

    func makeNSView(context: Context) -> NSScrollView {
        let scroll = NSScrollView()
        scroll.hasVerticalScroller = true
        scroll.hasHorizontalScroller = false
        scroll.autohidesScrollers = true
        scroll.borderType = .noBorder
        scroll.drawsBackground = false
        scroll.automaticallyAdjustsContentInsets = false

        let textView = SegmentBoundaryClickTextView()
        textView.minSize = .zero
        textView.maxSize = NSSize(
            width: CGFloat.greatestFiniteMagnitude,
            height: CGFloat.greatestFiniteMagnitude
        )
        textView.isEditable = false
        textView.isSelectable = true
        textView.isRichText = true
        textView.drawsBackground = true
        textView.backgroundColor = NSColor(LuminaTheme.surface)
        textView.textContainerInset = NSSize(width: 12, height: 12)
        textView.isVerticallyResizable = true
        textView.isHorizontallyResizable = false
        textView.autoresizingMask = [.width]
        textView.textContainer?.widthTracksTextView = false
        textView.textContainer?.lineFragmentPadding = 0
        textView.textContainer?.containerSize = NSSize(
            width: LuminaTextLayoutSizing.fallbackLayoutWidth,
            height: CGFloat.greatestFiniteMagnitude
        )
        textView.clicksEnabled = isEnabled
        textView.onClickUTF16 = onClickUTF16
        applyBody(to: textView)

        scroll.documentView = textView
        return scroll
    }

    func updateNSView(_ scroll: NSScrollView, context: Context) {
        guard let textView = scroll.documentView as? SegmentBoundaryClickTextView else { return }
        textView.clicksEnabled = isEnabled
        textView.onClickUTF16 = onClickUTF16
        applyBody(to: textView)
        let width = scroll.contentSize.width
        if width > 0 {
            var frame = textView.frame
            if abs(frame.width - width) >= LuminaTextLayoutSizing.widthChangeEpsilon {
                frame.size.width = width
                textView.frame = frame
            }
            textView.applyLayoutWidth(width)
        }
    }

    private func applyBody(to textView: SegmentBoundaryClickTextView) {
        let attributed = Self.attributedConcat(text: text, cut: currentCut)
        if textView.textStorage?.string != text
            || textView.appliedCut != currentCut
        {
            textView.textStorage?.setAttributedString(attributed)
            textView.appliedCut = currentCut
        }
    }

    private static func attributedConcat(text: String, cut: Int) -> NSAttributedString {
        let ns = text as NSString
        let result = NSMutableAttributedString(string: text)
        let paragraph = NSMutableParagraphStyle()
        paragraph.lineSpacing = 4
        let full = NSRange(location: 0, length: ns.length)
        result.addAttributes(
            [
                .font: NSFont.systemFont(ofSize: NSFont.systemFontSize),
                .foregroundColor: NSColor(LuminaTheme.textPrimary),
                .paragraphStyle: paragraph,
            ],
            range: full
        )
        let cutUTF16 = SegmentBoundaryOffset.utf16Index(forUnicodeOffset: cut, in: text)
        if cutUTF16 > 0, ns.length > 0 {
            result.addAttribute(
                .backgroundColor,
                value: NSColor(LuminaTheme.accentMuted).withAlphaComponent(0.55),
                range: NSRange(location: 0, length: min(cutUTF16, ns.length))
            )
        }
        return result
    }
}

private final class SegmentBoundaryClickTextView: NSTextView {
    var clicksEnabled = true
    var onClickUTF16: ((Int) -> Void)?
    var appliedCut: Int = -1
    private var lastLayoutWidth: CGFloat = -1

    override func mouseDown(with event: NSEvent) {
        let local = convert(event.locationInWindow, from: nil)
        super.mouseDown(with: event)
        guard clicksEnabled, event.clickCount == 1, selectedRange().length == 0 else { return }
        onClickUTF16?(characterIndexForInsertion(at: local))
    }

    override func setFrameSize(_ newSize: NSSize) {
        super.setFrameSize(newSize)
        applyLayoutWidth(newSize.width)
    }

    func applyLayoutWidth(_ width: CGFloat) {
        guard let textContainer else { return }
        let usable = max(0, width - textContainerInset.width * 2)
        guard let layoutWidth = LuminaTextLayoutSizing.layoutWidth(for: usable) else { return }
        let changed = LuminaTextLayoutSizing.widthDidChange(
            from: lastLayoutWidth,
            to: layoutWidth
        )
        guard changed || lastLayoutWidth < 0 else { return }
        textContainer.containerSize = NSSize(
            width: layoutWidth,
            height: CGFloat.greatestFiniteMagnitude
        )
        lastLayoutWidth = layoutWidth
    }
}
