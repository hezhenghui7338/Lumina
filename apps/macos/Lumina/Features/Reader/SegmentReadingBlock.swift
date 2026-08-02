import SwiftUI

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
    var onToggleSource: () -> Void
    var onToggleSummary: () -> Void
    var onFollowUp: (String) -> Void
    var onRetrySummary: () -> Void
    var onSendToChat: ((String) -> Void)?
    var onSourceAppear: (() -> Void)?
    var onSummaryAppear: (() -> Void)?

    @State private var lockedViewportHeight: CGFloat?
    @State private var measuredContentHeight: CGFloat = LuminaTheme.segmentContentMinHeight

    var body: some View {
        VStack(alignment: .leading, spacing: LuminaTheme.summarySectionSpacing) {
            segmentHeaderRow

            contentPanel
        }
        .padding(LuminaTheme.summaryPadding)
        .readingColumn()
        .background(
            isHighlighted
                ? LuminaTheme.accentMuted.opacity(0.35)
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
            Divider()
                .background(LuminaTheme.border)
                .padding(.vertical, 24)
        }
    }

    private var showingSource: Bool {
        switch contentMode {
        case .summary:
            isSourceExpanded
        case .original:
            !isSummaryExpanded
        }
    }

    private var showsSourceBox: Bool {
        contentMode == .summary && isSourceExpanded
    }

    private var shouldMeasureSummaryHeight: Bool {
        contentMode == .summary && !isSourceExpanded
    }

    private var viewportHeight: CGFloat {
        lockedViewportHeight ?? clampHeight(measuredContentHeight)
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

            panelToggleButton
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
                .background(LuminaTheme.border)

            panelToggleButton
                .padding(.horizontal, LuminaTheme.summaryPadding)
                .padding(.vertical, 10)
        }
        .readingColumn()
        .background(
            RoundedRectangle(cornerRadius: LuminaTheme.summaryCornerRadius)
                .fill(LuminaTheme.accentMuted.opacity(0.45))
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
        Button(action: togglePanelContent) {
            Text(toggleTitle(showingSource: showingSource))
                .font(.system(size: LuminaTheme.summaryLabelSize, weight: .semibold))
                .foregroundStyle(LuminaTheme.textSecondary)
                .tracking(0.6)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .buttonStyle(.plain)
    }

    private func handleSummaryHeightChange(_ height: CGFloat) {
        guard height > 0, shouldMeasureSummaryHeight else { return }
        measuredContentHeight = height
        lockedViewportHeight = clampHeight(height)
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

    private func clampHeight(_ height: CGFloat) -> CGFloat {
        min(
            max(height, LuminaTheme.segmentContentMinHeight),
            LuminaTheme.segmentContentMaxHeight
        )
    }

    @ViewBuilder
    private func summaryContent(showsBackground: Bool) -> some View {
        if let parsedSummary {
            SummaryBlock(
                parsedSummary: parsedSummary,
                rawJSON: segment.summary_json,
                provider: segment.summary_provider,
                model: segment.summary_model,
                charCount: effectiveCharCount,
                segmentIndex: segment.idx,
                segmentTotal: segmentTotal,
                fallbackAnchor: segment.anchor_label,
                summaryDurationS: segment.summary_duration_s,
                summaryLlmAttempts: segment.summary_llm_attempts,
                onFollowUp: onFollowUp,
                showsBackground: showsBackground
            )
        } else if isSummaryLoading {
            summaryLoadingSkeleton
        } else if let summary = segment.summary_json, !summary.isEmpty {
            SummaryBlock(
                parsedSummary: nil,
                rawJSON: summary,
                provider: segment.summary_provider,
                model: segment.summary_model,
                summaryDurationS: segment.summary_duration_s,
                summaryLlmAttempts: segment.summary_llm_attempts,
                onFollowUp: onFollowUp,
                onSendToChat: onSendToChat,
                showsBackground: showsBackground,
                showsHeader: false
            )
        } else {
            summaryPlaceholder
        }
    }

    private var summaryLoadingMinHeight: CGFloat {
        guard let count = effectiveCharCount, count > 0 else { return 200 }
        return min(max(CGFloat(count) / 6, 200), 600)
    }

    private var summaryLoadingSkeleton: some View {
        SourceTextSkeleton(lineCount: 5)
            .frame(minHeight: summaryLoadingMinHeight, alignment: .top)
            .accessibilityLabel("摘要加载中")
    }

    @ViewBuilder
    private var segmentHeaderRow: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            if let anchor = resolvedAnchorText {
                Text(anchor)
                    .font(.system(size: LuminaTheme.summaryLabelSize, weight: .medium))
                    .foregroundStyle(LuminaTheme.textSecondary)
                    .lineLimit(1)
                    .textSelection(.enabled)
            }

            Spacer(minLength: 8)

            if isSummaryInProgress {
                HStack(spacing: 6) {
                    ProgressView()
                        .controlSize(.mini)
                    progressStatusView
                        .font(.system(size: LuminaTheme.summaryLabelSize - 1))
                        .foregroundStyle(LuminaTheme.textSecondary)
                        .lineLimit(1)
                }
            }

            if let count = effectiveCharCount, count > 0 {
                Text("约 \(Self.formatCount(count)) 字")
                    .font(.system(size: LuminaTheme.summaryLabelSize - 1))
                    .foregroundStyle(LuminaTheme.textSecondary.opacity(0.85))
                    .textSelection(.enabled)
            }

            if segmentTotal > 0 {
                Text("段 \(segment.idx + 1)/\(segmentTotal)")
                    .font(.system(size: LuminaTheme.summaryLabelSize - 1))
                    .foregroundStyle(LuminaTheme.textSecondary.opacity(0.85))
                    .textSelection(.enabled)
            }
        }
    }

    private var resolvedAnchorText: String? {
        let raw: String? = {
            if let summary = segment.summary_json, !summary.isEmpty,
               let parsed = ParsedSummary(json: summary),
               let anchor = parsed.anchor, !anchor.isEmpty {
                return anchor
            }
            if let label = segment.anchor_label, !label.isEmpty {
                return label
            }
            return nil
        }()
        guard let raw else { return nil }
        return raw.hasPrefix("〔") ? raw : "〔\(raw)〕"
    }

    @ViewBuilder
    private var progressStatusView: some View {
        if isSummaryInProgress, runningMetrics != nil {
            TimelineView(.periodic(from: .now, by: 1)) { context in
                Text(progressText(at: context.date))
            }
        } else {
            Text(progressText(at: Date()))
        }
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
        switch segment.summary_status {
        case "pending", "running": true
        default: false
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
        VStack(alignment: .leading, spacing: 8) {
            switch segment.summary_status {
            case "running", "pending":
                EmptyView()
            case "failed", "error":
                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 10) {
                        Image(systemName: "exclamationmark.circle")
                            .foregroundStyle(.red)
                        Text(failureMessage)
                            .font(.system(size: LuminaTheme.summaryBulletSize))
                            .foregroundStyle(LuminaTheme.textSecondary)
                            .lineLimit(3)
                    }
                    Button("重试", action: onRetrySummary)
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                }
            default:
                Text("尚无摘要")
                    .font(.system(size: LuminaTheme.summaryBulletSize))
                    .foregroundStyle(LuminaTheme.textSecondary)
            }
        }
        .readingColumn()
    }

    @ViewBuilder
    private func sourceBodyContent(showHeader: Bool) -> some View {
        if showHeader, let count = effectiveCharCount, count > 0 {
            Text("原文 · 约 \(Self.formatCount(count)) 字")
                .font(.system(size: LuminaTheme.summaryLabelSize - 1))
                .foregroundStyle(LuminaTheme.textSecondary.opacity(0.85))
                .textSelection(.enabled)
        }

        if let body = sourceBody {
            if !body.rawText.isEmpty {
                if needsTranslation {
                    sourceTextLabel("原文")
                }
                LuminaSelectableText(
                    text: body.rawText,
                    foreground: LuminaTheme.textSecondary,
                    onSendToChat: onSendToChat
                )
            }
            if needsTranslation {
                if isSourceRefreshing && body.translation.isEmpty {
                    SourceTextSkeleton(lineCount: 3)
                } else if !body.translation.isEmpty {
                    sourceTextLabel("译文")
                    LuminaSelectableText(
                        text: body.translation,
                        foreground: LuminaTheme.textSecondary.opacity(0.85),
                        onSendToChat: onSendToChat
                    )
                }
            }
            if body.rawText.isEmpty && body.translation.isEmpty && !isSourceLoading {
                Text("暂无原文")
                    .font(.system(size: LuminaTheme.summaryBulletSize))
                    .foregroundStyle(LuminaTheme.textSecondary)
            }
        } else if isSourceLoading {
            SourceTextSkeleton()
        } else {
            Text("原文加载失败")
                .font(.system(size: LuminaTheme.summaryBulletSize))
                .foregroundStyle(LuminaTheme.textSecondary)
        }
    }

    private func sourceTextLabel(_ title: String) -> some View {
        Text(title)
            .font(.system(size: LuminaTheme.summaryLabelSize, weight: .semibold))
            .foregroundStyle(LuminaTheme.textSecondary)
            .tracking(0.6)
            .padding(.top, 4)
    }

    private static func formatCount(_ count: Int) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        return formatter.string(from: NSNumber(value: count)) ?? "\(count)"
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
    }
}
