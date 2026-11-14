import SwiftUI

/// First reading item, followed by body segment 0.
struct IntroReadingBlock: View {
    let contentMode: ReaderContentMode
    let intro: BookIntro
    var onFollowUp: ((String) -> Void)?
    var onRetry: (() -> Void)?
    var onNext: (() -> Void)?
    var listenHighlight: ListenHighlightAnchor? = nil

    @EnvironmentObject private var theme: ThemeManager
    @Environment(\.readerPaper) private var paper

    private var parsedSummary: ParsedSummary? {
        guard let json = intro.summaryJSONString else { return nil }
        return ParsedSummary(json: json)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: LuminaTheme.summarySectionSpacing) {
            Text("AI 导读")
                .font(.system(size: LuminaTheme.summaryLabelSize, weight: .semibold))
                .foregroundStyle(paper.textSecondary)
                .tracking(0.6)
                .listenFollowHighlight(listenHighlight == .segmentTitle)

            panelBody
            if let onNext {
                HStack {
                    Spacer()
                    Button("开始正文", action: onNext)
                        .buttonStyle(.borderless)
                }
            }
        }
        .padding(LuminaTheme.summaryPadding)
        .readingColumn()
        .accessibilityIdentifier("lumina.reader.intro")
    }

    @ViewBuilder
    private var panelBody: some View {
        switch intro.status {
        case "pending":
            VStack(alignment: .leading, spacing: 8) {
                Text("正在获取 AI 导读…")
                    .font(.system(size: theme.scaled(LuminaTheme.summaryBulletSize)))
                    .foregroundStyle(paper.textSecondary)
                SourceTextSkeleton(lineCount: 4)
            }
        case "failed":
            VStack(alignment: .leading, spacing: 8) {
                Text(intro.error?.isEmpty == false ? intro.error! : "AI 导读生成失败")
                    .font(.system(size: theme.scaled(LuminaTheme.summaryBulletSize)))
                    .foregroundStyle(paper.textSecondary)
                if let onRetry {
                    Button("重新获取") { onRetry() }
                        .buttonStyle(.borderless)
                }
            }
        case "ready":
            if contentMode == .original {
                sourceBody
            } else {
                SummaryBlock(
                    parsedSummary: parsedSummary,
                    rawJSON: intro.summaryJSONString,
                    fallbackAnchor: "AI导读",
                    onFollowUp: onFollowUp,
                    showsHeader: false,
                    listenHighlight: listenHighlight
                )
            }
        default:
            VStack(alignment: .leading, spacing: 8) {
                Text(intro.status == "skipped"
                    ? "暂未获取到 AI 导读，可重新获取或继续阅读正文。"
                    : "先读 AI 导读，了解本书背景、主题与阅读提示。")
                    .font(.system(size: theme.scaled(LuminaTheme.summaryBulletSize)))
                    .foregroundStyle(paper.textSecondary)
                if let onRetry {
                    Button("获取 AI 导读", action: onRetry)
                        .buttonStyle(.borderless)
                }
            }
        }
    }

    @ViewBuilder
    private var sourceBody: some View {
        let text = intro.source_text ?? ""
        if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            Text("暂无公开介绍原文")
                .font(.system(size: theme.scaled(LuminaTheme.summaryBulletSize)))
                .foregroundStyle(paper.textSecondary)
        } else {
            LuminaSelectableText(
                text: text,
                fontSize: theme.scaled(LuminaTheme.summaryBulletSize),
                lineSpacing: theme.lineSpaced(LuminaTheme.summaryBulletLineSpacing),
                foreground: paper.textPrimary,
                highlightUTF16: listenHighlight?.originalNSRange,
                highlightStyle: .listen
            )
            if let citations = intro.citations, !citations.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("来源")
                        .font(.system(size: LuminaTheme.summaryLabelSize, weight: .semibold))
                        .foregroundStyle(paper.textSecondary)
                    ForEach(Array(citations.enumerated()), id: \.offset) { _, cite in
                        if let url = cite.url, let link = URL(string: url) {
                            Link(cite.title?.isEmpty == false ? cite.title! : url, destination: link)
                                .font(.system(size: theme.scaled(LuminaTheme.summaryLabelSize)))
                        } else if let title = cite.title, !title.isEmpty {
                            Text(title)
                                .font(.system(size: theme.scaled(LuminaTheme.summaryLabelSize)))
                                .foregroundStyle(paper.textSecondary)
                        }
                    }
                }
                .padding(.top, 8)
            }
        }
    }
}
