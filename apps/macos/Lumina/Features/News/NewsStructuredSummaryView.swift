import SwiftUI

/// Book-library-style renderer for LLM news summary markdown.
struct NewsStructuredSummaryView: View {
    let markdown: String
    var scale: Double = 1.0
    var onFollowUp: ((String) -> Void)?
    var showsBackground: Bool = true

    private var parsed: ParsedNewsStructuredSummary {
        NewsSummaryMarkdown.parseStructured(markdown)
    }

    private func scaled(_ base: CGFloat) -> CGFloat {
        base * CGFloat(scale)
    }

    var body: some View {
        if parsed.hasContent || !parsed.followUps.isEmpty {
            content
        }
    }

    @ViewBuilder
    private var content: some View {
        VStack(alignment: .leading, spacing: LuminaTheme.summarySectionSpacing) {
            if !parsed.sentences.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("总结")
                        .font(.system(size: scaled(LuminaTheme.summaryLabelSize), weight: .semibold))
                        .foregroundStyle(LuminaTheme.textSecondary)
                        .tracking(0.6)

                    VStack(alignment: .leading, spacing: LuminaTheme.summaryLeadParagraphSpacing) {
                        ForEach(Array(parsed.sentences.enumerated()), id: \.offset) { _, sentence in
                            Text(sentence)
                                .font(.system(size: scaled(LuminaTheme.summaryLeadSize), weight: .regular))
                                .foregroundStyle(LuminaTheme.textPrimary)
                                .lineSpacing(scaled(LuminaTheme.summaryLeadLineSpacing))
                                .fixedSize(horizontal: false, vertical: true)
                                .textSelection(.enabled)
                        }
                    }
                }
            }

            if !parsed.bullets.isEmpty {
                summarySection(title: "结构化要点") {
                    VStack(alignment: .leading, spacing: LuminaTheme.summaryBulletItemSpacing) {
                        ForEach(Array(parsed.bullets.enumerated()), id: \.offset) { index, bullet in
                            NewsStructuredBulletRow(index: index + 1, bullet: bullet, scale: scale)
                        }
                    }
                }
            }

            if !parsed.notes.isEmpty {
                summarySection(title: "需要注意") {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(Array(parsed.notes.enumerated()), id: \.offset) { _, note in
                            HStack(alignment: .top, spacing: 8) {
                                Text("·")
                                    .font(.system(size: scaled(LuminaTheme.summaryBulletSize), weight: .semibold))
                                    .foregroundStyle(LuminaTheme.textSecondary)
                                Text(note)
                                    .font(.system(size: scaled(LuminaTheme.summaryBulletSize), weight: .regular))
                                    .foregroundStyle(LuminaTheme.textSecondary)
                                    .lineSpacing(scaled(LuminaTheme.summaryBulletLineSpacing))
                                    .fixedSize(horizontal: false, vertical: true)
                                    .textSelection(.enabled)
                            }
                        }
                    }
                }
            }

            if !parsed.followUps.isEmpty {
                summarySection(title: "你可以接着问") {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(Array(parsed.followUps.enumerated()), id: \.offset) { index, question in
                            if let onFollowUp {
                                Button {
                                    onFollowUp(question)
                                } label: {
                                    FollowUpChip(text: question, index: index + 1)
                                }
                                .buttonStyle(.plain)
                                .accessibilityIdentifier("news.summary.followUp.\(index + 1)")
                            } else {
                                FollowUpChip(text: question, index: index + 1)
                            }
                        }
                    }
                }
            }
        }
        .modifier(SummaryChrome(showsBackground: showsBackground, scale: scale))
    }

    @ViewBuilder
    private func summarySection<Content: View>(
        title: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Divider()
                .background(LuminaTheme.border)

            Text(title)
                .font(.system(size: scaled(LuminaTheme.summaryLabelSize), weight: .semibold))
                .foregroundStyle(LuminaTheme.textSecondary)
                .tracking(0.6)

            content()
        }
    }

    private struct SummaryChrome: ViewModifier {
        let showsBackground: Bool
        let scale: Double

        func body(content: Content) -> some View {
            if showsBackground {
                content
                    .padding(LuminaTheme.summaryPadding)
                    .readingColumn()
                    .background(
                        RoundedRectangle(cornerRadius: LuminaTheme.summaryCornerRadius)
                            .fill(LuminaTheme.accentMuted.opacity(0.45))
                    )
            } else {
                content
                    .readingColumn()
            }
        }
    }
}

private struct NewsStructuredBulletRow: View {
    let index: Int
    let bullet: ParsedBullet
    var scale: Double = 1.0

    private func scaled(_ base: CGFloat) -> CGFloat {
        base * CGFloat(scale)
    }

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            RoundedRectangle(cornerRadius: 1)
                .fill(LuminaTheme.accent.opacity(0.55))
                .frame(width: 2)
                .padding(.top, 4)
                .padding(.bottom, 2)

            VStack(alignment: .leading, spacing: 3) {
                if let label = bullet.label, !label.isEmpty {
                    Text(label)
                        .font(.system(size: scaled(LuminaTheme.summaryBulletSize), weight: .semibold))
                        .foregroundStyle(LuminaTheme.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                }
                Text(bullet.body)
                    .font(.system(size: scaled(LuminaTheme.summaryBulletSize), weight: .regular))
                    .foregroundStyle(
                        bullet.label == nil
                            ? LuminaTheme.textPrimary
                            : LuminaTheme.textSecondary
                    )
                    .lineSpacing(scaled(LuminaTheme.summaryBulletLineSpacing))
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityText)
    }

    private var accessibilityText: String {
        if let label = bullet.label {
            return "\(index). \(label)：\(bullet.body)"
        }
        return "\(index). \(bullet.body)"
    }
}

struct SummarySkimSkeleton: View {
    var scale: Double = 1.0

    private func scaled(_ base: CGFloat) -> CGFloat {
        base * CGFloat(scale)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: LuminaTheme.summarySectionSpacing) {
            Text("总结")
                .font(.system(size: scaled(LuminaTheme.summaryLabelSize), weight: .semibold))
                .foregroundStyle(LuminaTheme.textSecondary)
                .tracking(0.6)

            SourceTextSkeleton(lineCount: 2)

            Text("结构化要点")
                .font(.system(size: scaled(LuminaTheme.summaryLabelSize), weight: .semibold))
                .foregroundStyle(LuminaTheme.textSecondary)
                .tracking(0.6)
                .padding(.top, 4)

            SourceTextSkeleton(lineCount: 3)
        }
        .accessibilityLabel("速读摘要生成中")
    }
}
