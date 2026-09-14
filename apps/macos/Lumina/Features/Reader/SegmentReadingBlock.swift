import AppKit
import SwiftUI

/// Trailing items in the per-segment header, left-to-right after the spacer.
/// Source char meta sits immediately left of panel toggle; turn buttons stay
/// last so their click target does not shift with progress/regenerate width.
enum SegmentHeaderTrailingItem: Hashable {
    case contentMeta
    case panelToggle
    case progress
    case regenerateSummary
    case turnButtons
}

enum SegmentHeaderLayoutPolicy {
    static func trailingItems(
        showsContentMeta: Bool,
        isSummaryInProgress: Bool,
        showsRegenerate: Bool,
        showsTurnButtons: Bool
    ) -> [SegmentHeaderTrailingItem] {
        var items: [SegmentHeaderTrailingItem] = []
        if showsContentMeta { items.append(.contentMeta) }
        items.append(.panelToggle)
        if isSummaryInProgress { items.append(.progress) }
        if showsRegenerate { items.append(.regenerateSummary) }
        if showsTurnButtons { items.append(.turnButtons) }
        return items
    }
}

/// Segment header meta left of「切换原文」: source char count only (no segment index).
enum SegmentContentMetaPolicy {
    static func label(charCount: Int?) -> String? {
        guard let charCount, charCount > 0 else { return nil }
        return "原文 · 约 \(formatCount(charCount)) 字"
    }

    static func formatCount(_ count: Int) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        return formatter.string(from: NSNumber(value: count)) ?? "\(count)"
    }
}

private struct SegmentPanelContentHeightKey: PreferenceKey {
    static var defaultValue: CGFloat = 0

    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = max(value, nextValue())
    }
}

/// Single segment in the continuous reading feed: summary, placeholder, and optional source text.
struct SegmentReadingBlock: View, Equatable {
    let contentMode: ReaderContentMode
    let segment: SegmentRow
    let segmentTotal: Int
    let isLast: Bool
    let isHighlighted: Bool
    let isSourceExpanded: Bool
    let isSummaryExpanded: Bool
    let sourceBody: SegmentSourceBody?
    let isSourceLoading: Bool
    let isSourceRefreshing: Bool
    let needsTranslation: Bool
    var parsedSummary: ParsedSummary?
    var isSummaryLoading: Bool = false
    var summaryProgressMessage: String?
    var runningMetrics: SegmentRunningMetrics?
    var fontScale: Double = 1.0
    var paper: ReaderPaper = .white
    var onToggleSource: () -> Void
    var onToggleSummary: () -> Void
    var onFollowUp: (String) -> Void
    var onRetrySummary: (SummaryTier) -> Void
    var canGoPrev: Bool = false
    var canGoNext: Bool = false
    var onPrevSegment: () -> Void = {}
    var onNextSegment: () -> Void = {}
    var onAdjustBoundary: (() -> Void)? = nil
    var onSourceAppear: (() -> Void)?
    var onSummaryAppear: (() -> Void)?
    var originalHighlightUTF16: NSRange? = nil

    @State private var lockedViewportHeight: CGFloat?
    @State private var measuredContentHeight: CGFloat = LuminaTheme.segmentContentMinHeight

    private func scaled(_ base: CGFloat) -> CGFloat {
        base * CGFloat(fontScale)
    }

    var body: some View {
        Group {
            VStack(alignment: .leading, spacing: LuminaTheme.summarySectionSpacing) {
                segmentHeaderRow

                contentPanel
            }
            .padding(LuminaTheme.summaryPadding)
            .readingColumn()
            .background(
                isHighlighted
                    ? paper.card.opacity(0.35)
                    : Color.clear
            )
            .animation(.easeOut(duration: 0.4), value: isHighlighted)
            .onAppear {
                if contentMode == .original {
                    onSourceAppear?()
                } else {
                    onSummaryAppear?()
                }
            }

            if !isLast {
                segmentBoundarySeparator
            }
        }
        .environment(\.readerPaper, paper)
    }

    private var segmentBoundarySeparator: some View {
        HStack(spacing: 8) {
            Rectangle()
                .fill(paper.border)
                .frame(height: 1)

            if let onAdjustBoundary {
                Button(action: onAdjustBoundary) {
                    Image(systemName: "rectangle.split.1x2")
                        .font(.system(size: LuminaTheme.summaryLabelSize, weight: .semibold))
                        .foregroundStyle(LuminaTheme.accent)
                        .frame(minWidth: 24, minHeight: 24)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help("调整与下一段的边界")
                .accessibilityLabel("调整与下一段的边界")
                .accessibilityIdentifier("lumina.reader.control.adjustBoundary")
            }

            Rectangle()
                .fill(paper.border)
                .frame(height: 1)
        }
        .absorbsReaderChromeClicks()
        .padding(.vertical, 12)
    }

    private var showingSource: Bool {
        ListenChromePolicy.isShowingOriginal(
            contentMode: contentMode,
            sourceExpanded: isSourceExpanded,
            summaryExpanded: isSummaryExpanded
        )
    }

    private var showsSourceBox: Bool {
        contentMode == .summary && isSourceExpanded
    }

    private var shouldMeasureSummaryHeight: Bool {
        contentMode == .summary && !isSourceExpanded
    }

    private var viewportHeight: CGFloat {
        ReaderSegmentPanelHeight.boxedViewportHeight(
            measured: measuredContentHeight,
            locked: lockedViewportHeight
        )
    }

    @ViewBuilder
    private var contentPanel: some View {
        if showsSourceBox {
            boxedSourcePanel
        } else {
            plainContentPanel
        }
    }

    @ViewBuilder
    private var plainContentPanel: some View {
        VStack(alignment: .leading, spacing: 0) {
            panelBody(showingSource: showingSource)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(summaryHeightMeasurement)

            panelCopyButton
                .padding(.top, 10)
        }
        .readingColumn()
        .onPreferenceChange(SegmentPanelContentHeightKey.self, perform: handleSummaryHeightChange)
    }

    @ViewBuilder
    private var boxedSourcePanel: some View {
        VStack(alignment: .leading, spacing: 0) {
            ScrollView {
                sourceBodyContent(showHeader: false)
                    .padding(LuminaTheme.summaryPadding)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(height: viewportHeight)

            Divider()
                .background(paper.border)

            panelCopyButton
                .padding(.horizontal, LuminaTheme.summaryPadding)
                .padding(.vertical, 10)
        }
        .readingColumn()
        .background(
            RoundedRectangle(cornerRadius: LuminaTheme.summaryCornerRadius)
                .fill(paper.card.opacity(0.45))
        )
        .clipShape(RoundedRectangle(cornerRadius: LuminaTheme.summaryCornerRadius))
    }

    @ViewBuilder
    private var summaryHeightMeasurement: some View {
        if shouldMeasureSummaryHeight {
            GeometryReader { proxy in
                Color.clear.preference(
                    key: SegmentPanelContentHeightKey.self,
                    value: proxy.size.height
                )
            }
        }
    }

    private var panelToggleButton: some View {
        Button(toggleTitle(showingSource: showingSource), action: togglePanelContent)
            .buttonStyle(.bordered)
            .controlSize(.small)
            .help(showingSource ? "切换回摘要" : "切换到原文")
            .accessibilityIdentifier("lumina.reader.control.panelToggle")
            .absorbsReaderChromeClicks()
    }

    private var panelCopyButton: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            if let leading = panelFooterLeadingLabel {
                Text(leading)
                    .font(.system(size: LuminaTheme.summaryLabelSize - 1))
                    .foregroundStyle(paper.textSecondary.opacity(0.85))
                    .textSelection(.enabled)
                    .lineLimit(1)
                    .minimumScaleFactor(0.75)
            }

            Spacer(minLength: 0)

            Button(action: copyCurrentPanel) {
                Text("复制")
                    .font(.system(size: LuminaTheme.summaryLabelSize, weight: .semibold))
                    .foregroundStyle(paper.textSecondary)
                    .tracking(0.6)
            }
            .buttonStyle(.plain)
            .disabled(!canCopyCurrentPanel)
            .help(showingSource ? "复制本段原文" : "复制本段摘要")
            .accessibilityIdentifier("lumina.reader.control.copyPanel")
        }
        .absorbsReaderChromeClicks()
    }

    private var canCopyCurrentPanel: Bool {
        copyablePanelText() != nil
    }

    private func copyCurrentPanel() {
        guard let text = copyablePanelText() else { return }
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString(text, forType: .string)
    }

    private func copyablePanelText() -> String? {
        if showingSource {
            return copyableSourceText()
        }
        return copyableSummaryText()
    }

    private func copyableSourceText() -> String? {
        guard let body = sourceBody else { return nil }
        var parts: [String] = []
        if !body.rawText.isEmpty {
            if needsTranslation {
                parts.append("原文\n\(body.rawText)")
            } else {
                parts.append(body.rawText)
            }
        }
        if needsTranslation, !body.translation.isEmpty {
            parts.append("译文\n\(body.translation)")
        }
        let text = parts.joined(separator: "\n\n")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty ? nil : text
    }

    private func copyableSummaryText() -> String? {
        let summary = parsedSummary
            ?? segment.summary_json.flatMap { ParsedSummary(json: $0) }
        guard let summary, summary.hasContent else { return nil }
        let text = summary.copyablePlainText
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty ? nil : text
    }

    private func handleSummaryHeightChange(_ height: CGFloat) {
        guard shouldMeasureSummaryHeight else { return }
        guard ReaderSegmentPanelHeight.shouldCommitMeasurement(
            current: measuredContentHeight,
            incoming: height
        ) else { return }
        measuredContentHeight = height
        let locked = ReaderSegmentPanelHeight.clamp(height)
        if lockedViewportHeight != locked {
            lockedViewportHeight = locked
        }
    }

    @ViewBuilder
    private func panelBody(showingSource: Bool) -> some View {
        if showingSource {
            sourceBodyContent(showHeader: false)
        } else {
            summaryContent(showsBackground: false)
        }
    }

    private func togglePanelContent() {
        switch contentMode {
        case .summary:
            onToggleSource()
        case .original:
            onToggleSummary()
        }
    }

    private func toggleTitle(showingSource: Bool) -> String {
        showingSource ? "切换摘要" : "切换原文"
    }

    @ViewBuilder
    private func summaryContent(showsBackground: Bool) -> some View {
        if let parsedSummary {
            SummaryBlock(
                parsedSummary: parsedSummary,
                rawJSON: nil,
                provider: segment.summary_provider,
                model: segment.summary_model,
                fallbackAnchor: segment.anchor_label,
                summaryDurationS: segment.summary_duration_s,
                summaryLlmAttempts: segment.summary_llm_attempts,
                onFollowUp: onFollowUp,
                showsBackground: showsBackground,
                showsHeader: false,
                showsAttribution: false
            )
        } else if isSummaryLoading || segment.summary_status == "running" {
            summaryLoadingSkeleton
        } else if !(segment.summary_json ?? "").isEmpty {
            Text("摘要格式异常，请重试")
                .font(.system(size: scaled(LuminaTheme.summaryBulletSize)))
                .foregroundStyle(paper.textSecondary)
        } else {
            summaryPlaceholder
        }
    }

    private var summaryPlaceholderMinHeight: CGFloat {
        SegmentSummaryPlaceholderHeight.reserved(charCount: effectiveCharCount)
    }

    private var summaryLoadingSkeleton: some View {
        SourceTextSkeleton(lineCount: 5)
            .frame(minHeight: summaryPlaceholderMinHeight, alignment: .top)
            .accessibilityLabel(
                segment.summary_status == "running" ? "摘要生成中" : "摘要加载中"
            )
    }

    private var trailingHeaderItems: [SegmentHeaderTrailingItem] {
        SegmentHeaderLayoutPolicy.trailingItems(
            showsContentMeta: segmentContentMetaLabel != nil,
            isSummaryInProgress: isSummaryInProgress,
            showsRegenerate: showsRegenerateSummaryButton,
            showsTurnButtons: showsSegmentTurnButtons
        )
    }

    private var segmentContentMetaLabel: String? {
        SegmentContentMetaPolicy.label(charCount: effectiveCharCount)
    }

    /// Bottom-left of the panel: summary attribution only (char meta lives in the header).
    private var panelFooterLeadingLabel: String? {
        showingSource ? nil : summaryAttributionLabel
    }

    private var summaryAttributionLabel: String? {
        SummaryAttributionPolicy.label(
            provider: segment.summary_provider,
            model: segment.summary_model,
            durationS: segment.summary_duration_s,
            llmAttempts: segment.summary_llm_attempts
        )
    }

    @ViewBuilder
    private var segmentHeaderRow: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(SegmentReadingHeaderTitle.title(
                idx: segment.idx,
                segmentTotal: segmentTotal,
                chapter: segment.chapter,
                label: segment.label
            ))
            .font(.system(size: LuminaTheme.summaryLabelSize, weight: .medium))
            .foregroundStyle(paper.textSecondary)
            .lineLimit(1)
            .textSelection(.enabled)

            Spacer(minLength: 8)

            ForEach(trailingHeaderItems, id: \.self) { item in
                trailingHeaderItemView(item)
            }
        }
    }

    @ViewBuilder
    private func trailingHeaderItemView(_ item: SegmentHeaderTrailingItem) -> some View {
        switch item {
        case .contentMeta:
            if let meta = segmentContentMetaLabel {
                Text(meta)
                    .font(.system(size: LuminaTheme.summaryLabelSize - 1))
                    .foregroundStyle(paper.textSecondary.opacity(0.85))
                    .textSelection(.enabled)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
        case .panelToggle:
            panelToggleButton
        case .progress:
            HStack(spacing: 6) {
                ProgressView()
                    .controlSize(.mini)
                progressStatusView
                    .font(.system(size: LuminaTheme.summaryLabelSize - 1))
                    .foregroundStyle(paper.textSecondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
            .lineLimit(1)
        case .regenerateSummary:
            regenerateSummaryButton
        case .turnButtons:
            segmentTurnButtons
        }
    }

    @ViewBuilder
    private var progressStatusView: some View {
        if isSummaryInProgress, runningMetrics != nil {
            TimelineView(.periodic(from: .now, by: 1)) { context in
                progressLabel(progressText(at: context.date))
            }
        } else {
            progressLabel(progressText(at: Date()))
        }
    }

    private func progressLabel(_ text: String) -> some View {
        Text(text)
            .lineLimit(1)
            .minimumScaleFactor(0.8)
    }

    private func progressText(at now: Date) -> String {
        if let summaryProgressMessage, !summaryProgressMessage.isEmpty {
            return summaryProgressMessage
        }
        if let runningMetrics {
            return SummaryMetricsFormatter.inProgressLabel(
                startedAt: runningMetrics.startedAt,
                llmAttempt: runningMetrics.llmAttempt,
                maxLlmAttempts: runningMetrics.maxLlmAttempts,
                now: now
            )
        }
        return "摘要生成中…"
    }

    private var isSummaryInProgress: Bool {
        segment.summary_status == "running"
    }

    private var hasSummaryContent: Bool {
        if parsedSummary != nil { return true }
        if let summary = segment.summary_json, !summary.isEmpty { return true }
        return false
    }

    private var showsRegenerateSummaryButton: Bool {
        segment.summary_status == "ready" && hasSummaryContent
    }

    private var generateSummaryButton: some View {
        summaryTierButton(
            title: "生成摘要",
            identifier: "lumina.reader.control.generateSummary",
            advancedIdentifier: "lumina.reader.control.generateAdvancedSummary"
        )
    }

    private var regenerateSummaryButton: some View {
        summaryTierButton(
            title: "重新摘要",
            identifier: "lumina.reader.control.regenerateSummary",
            advancedIdentifier: "lumina.reader.control.regenerateAdvancedSummary"
        )
    }

    private var showsSegmentTurnButtons: Bool {
        segmentTotal > 1
    }

    private var segmentTurnButtons: some View {
        HStack(spacing: 4) {
            segmentTurnButton(
                systemImage: "arrow.left",
                help: "上一段（\(ShortcutStore.shared.display(for: .prevSegment))）",
                accessibilityName: "上一段",
                identifier: "lumina.reader.control.prevSegment",
                enabled: canGoPrev,
                action: onPrevSegment
            )
            segmentTurnButton(
                systemImage: "arrow.right",
                help: "下一段（\(ShortcutStore.shared.display(for: .nextSegment))）",
                accessibilityName: "下一段",
                identifier: "lumina.reader.control.nextSegment",
                enabled: canGoNext,
                action: onNextSegment
            )
        }
        .fixedSize()
        .absorbsReaderChromeClicks()
    }

    private func segmentTurnButton(
        systemImage: String,
        help: String,
        accessibilityName: String,
        identifier: String,
        enabled: Bool,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Image(systemName: systemImage)
        }
        .buttonStyle(.bordered)
        .controlSize(.small)
        .disabled(!enabled)
        .help(help)
        .accessibilityLabel(accessibilityName)
        .accessibilityIdentifier(identifier)
    }

    private func summaryTierButton(
        title: String,
        identifier: String,
        advancedIdentifier: String
    ) -> some View {
        Button(title) {
            onRetrySummary(.normal)
        }
        .buttonStyle(.bordered)
        .controlSize(.small)
        .help("点击生成正常摘要；右键可选高级摘要")
        .contextMenu {
            Button("高级摘要") {
                onRetrySummary(.advanced)
            }
            .accessibilityIdentifier(advancedIdentifier)
        }
        .accessibilityIdentifier(identifier)
        .accessibilityAction(named: "高级摘要") {
            onRetrySummary(.advanced)
        }
    }

    private var failureMessage: String {
        if let summaryProgressMessage, !summaryProgressMessage.isEmpty {
            return summaryProgressMessage
        }
        return SummaryMetricsFormatter.failureLabel(
            durationS: segment.summary_duration_s,
            retryCount: segment.retry_count
        )
    }

    private var effectiveCharCount: Int? {
        if let charCount = segment.char_count, charCount > 0 {
            return charCount
        }
        if let body = sourceBody, !body.rawText.isEmpty {
            return body.rawText.count
        }
        return nil
    }

    @ViewBuilder
    private var summaryPlaceholder: some View {
        switch segment.summary_status {
        case "failed", "error":
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 10) {
                    Image(systemName: "exclamationmark.circle")
                        .foregroundStyle(.red)
                    Text(failureMessage)
                        .font(.system(size: scaled(LuminaTheme.summaryBulletSize)))
                        .foregroundStyle(paper.textSecondary)
                        .lineLimit(3)
                }
                regenerateSummaryButton
            }
            .readingColumn()
        case "pending":
            VStack(alignment: .leading, spacing: 8) {
                Text("尚无摘要")
                    .font(.system(size: scaled(LuminaTheme.summaryBulletSize)))
                    .foregroundStyle(paper.textSecondary)
                generateSummaryButton
            }
            .frame(minHeight: summaryPlaceholderMinHeight, alignment: .top)
            .readingColumn()
        default:
            Text("尚无摘要")
                .font(.system(size: scaled(LuminaTheme.summaryBulletSize)))
                .foregroundStyle(paper.textSecondary)
                .frame(minHeight: summaryPlaceholderMinHeight, alignment: .top)
                .readingColumn()
        }
    }

    @ViewBuilder
    private func sourceBodyContent(showHeader: Bool) -> some View {
        if showHeader, let meta = SegmentContentMetaPolicy.label(charCount: effectiveCharCount) {
            Text(meta)
                .font(.system(size: LuminaTheme.summaryLabelSize - 1))
                .foregroundStyle(paper.textSecondary.opacity(0.85))
                .textSelection(.enabled)
        }

        if let body = sourceBody {
            if !body.rawText.isEmpty {
                if needsTranslation {
                    sourceTextLabel("原文")
                }
                LuminaSelectableText(
                    text: body.rawText,
                    fontSize: scaled(LuminaTheme.summaryBulletSize),
                    lineSpacing: scaled(LuminaTheme.summaryBulletLineSpacing),
                    foreground: paper.textSecondary,
                    highlightUTF16: originalHighlightUTF16
                )
            }
            if needsTranslation {
                if isSourceRefreshing && body.translation.isEmpty {
                    SourceTextSkeleton(lineCount: 3)
                } else if !body.translation.isEmpty {
                    sourceTextLabel("译文")
                    LuminaSelectableText(
                        text: body.translation,
                        fontSize: scaled(LuminaTheme.summaryBulletSize),
                        lineSpacing: scaled(LuminaTheme.summaryBulletLineSpacing),
                        foreground: paper.textSecondary.opacity(0.85)
                    )
                }
            }
            if body.rawText.isEmpty && body.translation.isEmpty && !isSourceLoading {
                Text("暂无原文")
                    .font(.system(size: scaled(LuminaTheme.summaryBulletSize)))
                    .foregroundStyle(paper.textSecondary)
            }
        } else if isSourceLoading {
            SourceTextSkeleton()
        } else {
            Text("原文加载失败")
                .font(.system(size: scaled(LuminaTheme.summaryBulletSize)))
                .foregroundStyle(paper.textSecondary)
        }
    }

    private func sourceTextLabel(_ title: String) -> some View {
        Text(title)
            .font(.system(size: LuminaTheme.summaryLabelSize, weight: .semibold))
            .foregroundStyle(paper.textSecondary)
            .tracking(0.6)
            .padding(.top, 4)
    }

    static func == (lhs: SegmentReadingBlock, rhs: SegmentReadingBlock) -> Bool {
        lhs.contentMode == rhs.contentMode
            && lhs.segment == rhs.segment
            && lhs.segmentTotal == rhs.segmentTotal
            && lhs.isLast == rhs.isLast
            && lhs.isHighlighted == rhs.isHighlighted
            && lhs.isSourceExpanded == rhs.isSourceExpanded
            && lhs.isSummaryExpanded == rhs.isSummaryExpanded
            && lhs.sourceBody == rhs.sourceBody
            && lhs.isSourceLoading == rhs.isSourceLoading
            && lhs.isSourceRefreshing == rhs.isSourceRefreshing
            && lhs.needsTranslation == rhs.needsTranslation
            && lhs.parsedSummary == rhs.parsedSummary
            && lhs.isSummaryLoading == rhs.isSummaryLoading
            && lhs.summaryProgressMessage == rhs.summaryProgressMessage
            && lhs.runningMetrics == rhs.runningMetrics
            && lhs.fontScale == rhs.fontScale
            && lhs.paper == rhs.paper
            && lhs.canGoPrev == rhs.canGoPrev
            && lhs.canGoNext == rhs.canGoNext
            && lhs.originalHighlightUTF16 == rhs.originalHighlightUTF16
    }
}
