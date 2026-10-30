import SwiftUI

/// Book-level AI intro card placed before segment 0. Not a product segment.
struct IntroReadingBlock: View {
    let contentMode: ReaderContentMode
    let intro: BookIntro
    var onFollowUp: ((String) -> Void)?
    var onRetry: (() -> Void)?

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

            panelBody
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
                    showsHeader: false
                )
            }
        default:
            EmptyView()
        }
    }

    @ViewBuilder
    private var sourceBody: some View {
        let text = (intro.source_text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty {
            Text("暂无公开介绍原文")
                .font(.system(size: theme.scaled(LuminaTheme.summaryBulletSize)))
                .foregroundStyle(paper.textSecondary)
        } else {
            LuminaSelectableText(
                text: text,
                fontSize: theme.scaled(LuminaTheme.summaryBulletSize),
                lineSpacing: theme.lineSpaced(LuminaTheme.summaryBulletLineSpacing),
                foreground: paper.textPrimary
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
