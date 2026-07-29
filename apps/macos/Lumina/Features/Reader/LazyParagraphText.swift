import SwiftUI

enum TextChunkSplitter {
    static func chunks(from text: String, maxChunkSize: Int = 1200) -> [String] {
        guard !text.isEmpty else { return [] }
        let paragraphs = text.components(separatedBy: "\n\n")
        var result: [String] = []
        for para in paragraphs {
            let trimmed = para.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { continue }
            if trimmed.count <= maxChunkSize {
                result.append(trimmed)
            } else {
                result.append(contentsOf: splitLongParagraph(trimmed, maxSize: maxChunkSize))
            }
        }
        if result.isEmpty {
            result = splitLongParagraph(text, maxSize: maxChunkSize)
        }
        return result
    }

    private static func splitLongParagraph(_ text: String, maxSize: Int) -> [String] {
        var chunks: [String] = []
        var remaining = text
        while !remaining.isEmpty {
            if remaining.count <= maxSize {
                chunks.append(remaining)
                break
            }
            let slice = String(remaining.prefix(maxSize))
            let delimiters = ["。", "！", "？", ". ", "! ", "? ", "\n"]
            var splitAt = maxSize
            for delimiter in delimiters {
                if let range = slice.range(of: delimiter, options: .backwards) {
                    let pos = slice.distance(from: slice.startIndex, to: range.upperBound)
                    if pos > maxSize / 3 {
                        splitAt = pos
                        break
                    }
                }
            }
            chunks.append(String(remaining.prefix(splitAt)))
            remaining = String(remaining.dropFirst(splitAt))
                .trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return chunks
    }
}

/// Renders long text as lazy paragraph chunks inside a ScrollView (WeChat Reading style).
struct LazyParagraphText: View {
    let text: String
    var fontSize: CGFloat = LuminaTheme.summaryBulletSize
    var lineSpacing: CGFloat = LuminaTheme.summaryBulletLineSpacing
    var foreground: Color = LuminaTheme.textSecondary

    private var chunks: [String] {
        TextChunkSplitter.chunks(from: text)
    }

    var body: some View {
        LazyVStack(alignment: .leading, spacing: lineSpacing) {
            ForEach(Array(chunks.enumerated()), id: \.offset) { _, chunk in
                Text(chunk)
                    .font(.system(size: fontSize))
                    .foregroundStyle(foreground)
                    .lineSpacing(lineSpacing)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
        }
    }
}

struct SourceTextSkeleton: View {
    var lineCount: Int = 4

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(0..<lineCount, id: \.self) { index in
                RoundedRectangle(cornerRadius: 4)
                    .fill(LuminaTheme.border.opacity(0.45))
                    .frame(height: 14)
                    .frame(maxWidth: index == lineCount - 1 ? 180 : .infinity)
            }
        }
        .accessibilityLabel("原文加载中")
    }
}
