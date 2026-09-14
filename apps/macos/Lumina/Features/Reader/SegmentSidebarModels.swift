import SwiftUI

// MARK: - Models

struct SidebarSegmentItem: Identifiable, Equatable {
    let id: String
    let idx: Int
    let title: String?
    let summaryPreview: String?
    let bulletLabelsLine: String?
    let summaryStatus: String

    var headline: String {
        SegmentCatalogHeadlineText.joined(idx: idx, title: title)
    }

    static func make(from segment: SegmentRow, grouped: Bool = false) -> SidebarSegmentItem {
        let labels = (segment.bullet_labels ?? []).compactMap { raw -> String? in
            let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            return text.isEmpty ? nil : text
        }

        return SidebarSegmentItem(
            id: segment.id,
            idx: segment.idx,
            title: SegmentCatalogHeadlineText.title(
                chapter: grouped ? nil : segment.chapter,
                label: segment.label
            ),
            summaryPreview: SegmentCatalogPreview.line(summaryPreview: segment.summary_preview),
            bulletLabelsLine: labels.isEmpty ? nil : labels.joined(separator: " · "),
            summaryStatus: segment.summary_status
        )
    }
}

enum SegmentCatalogHeadlineText {
    static func title(chapter: String?, label: String?) -> String? {
        let chapter = SegmentOutlinePolicy.stripSectionMark(chapter ?? "")
        if !chapter.isEmpty { return chapter }
        let label = label?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !label.isEmpty { return label }
        return nil
    }

    static func joined(idx: Int, title: String?) -> String {
        if let title, !title.isEmpty {
            return "段 \(idx + 1) · \(title)"
        }
        return "段 \(idx + 1)"
    }
}

enum SegmentCatalogTypography {
    static let headline: Font = .body.weight(.medium)
    static let summary: Font = .body
    static let points: Font = .callout
    static let rowSpacing: CGFloat = 6
}

struct SegmentCatalogHeadline: View {
    let idx: Int
    let title: String?

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 0) {
            Text("段 \(idx + 1)")
                .fixedSize(horizontal: true, vertical: false)
                .layoutPriority(1)
            if let title, !title.isEmpty {
                Text(" · ")
                    .fixedSize(horizontal: true, vertical: false)
                    .layoutPriority(1)
                Text(title)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
        }
        .font(SegmentCatalogTypography.headline)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Catalog overlay copy. Must be a real summary sentence, not the 2–8 char
/// inferred `label` prefix Ollama summaries fall back to.
enum SegmentCatalogPreview {
    static let maxChars = 160
    static let previewLineLimit = 1

    static func line(summaryPreview: String?) -> String? {
        let preview = summaryPreview?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return preview.isEmpty ? nil : preview
    }

    static func fromSummaryJSON(_ json: String?, maxChars: Int = maxChars) -> String? {
        guard let json, let data = json.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return nil }

        if let sentences = obj["sentences"] as? [Any] {
            for item in sentences {
                let text = (item as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                if !text.isEmpty { return clip(text, maxChars: maxChars) }
            }
        }

        let bullets = SegmentReadyEventParser.parseBullets(json)
        guard !bullets.isEmpty else { return nil }
        return clip(bullets.joined(separator: " · "), maxChars: maxChars)
    }

    static func clip(_ text: String, maxChars: Int) -> String {
        guard maxChars > 0 else { return "" }
        if text.count <= maxChars { return text }
        if maxChars == 1 { return "…" }
        return String(text.prefix(maxChars - 1)) + "…"
    }
}

struct IndexedWindow<Item> {
    let items: [Item]
    let aboveCount: Int
    let belowCount: Int
    let startIndex: Int
    let totalCount: Int

    var isEmpty: Bool { totalCount == 0 }
}

enum SegmentRenderWindow {
    static let scrollAnimateThreshold = 15
    /// 主阅读区摘要/原文 prefetch 半径（段数）
    static let readBuffer = 4

    static func slice<Item>(
        _ all: [Item],
        centerIndex: Int,
        buffer: Int
    ) -> IndexedWindow<Item> {
        guard !all.isEmpty else {
            return IndexedWindow(
                items: [],
                aboveCount: 0,
                belowCount: 0,
                startIndex: 0,
                totalCount: 0
            )
        }
        let clampedCenter = min(max(0, centerIndex), all.count - 1)
        let start = max(0, clampedCenter - buffer)
        let end = min(all.count - 1, clampedCenter + buffer)
        return IndexedWindow(
            items: Array(all[start...end]),
            aboveCount: start,
            belowCount: all.count - 1 - end,
            startIndex: start,
            totalCount: all.count
        )
    }

    static func centerIndex(forSegmentIdx idx: Int, in segments: [SegmentRow]) -> Int {
        segments.firstIndex(where: { $0.idx == idx }) ?? 0
    }

    static func segmentIndexDelta(from currentIdx: Int?, to targetIdx: Int, in segments: [SegmentRow]) -> Int {
        guard let currentIdx,
              let from = segments.firstIndex(where: { $0.idx == currentIdx }),
              let to = segments.firstIndex(where: { $0.idx == targetIdx })
        else {
            return Int.max
        }
        return abs(to - from)
    }
}

// MARK: - Row View

struct SegmentCatalogRowLines: View {
    let idx: Int
    var title: String?
    var summaryPreview: String?
    var bulletLabelsLine: String?

    var body: some View {
        VStack(alignment: .leading, spacing: SegmentCatalogTypography.rowSpacing) {
            SegmentCatalogHeadline(idx: idx, title: title)
            if let summaryPreview {
                Text(summaryPreview)
                    .font(SegmentCatalogTypography.summary)
                    .foregroundStyle(.secondary)
                    .lineLimit(SegmentCatalogPreview.previewLineLimit)
                    .truncationMode(.tail)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            if let bulletLabelsLine {
                Text(bulletLabelsLine)
                    .font(SegmentCatalogTypography.points)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.tail)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct SegmentSidebarRowView: View, Equatable {
    let item: SidebarSegmentItem
    let isSelected: Bool

    static func == (lhs: SegmentSidebarRowView, rhs: SegmentSidebarRowView) -> Bool {
        lhs.item == rhs.item && lhs.isSelected == rhs.isSelected
    }

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            statusIcon
            SegmentCatalogRowLines(
                idx: item.idx,
                title: item.title,
                summaryPreview: item.summaryPreview,
                bulletLabelsLine: item.bulletLabelsLine
            )
        }
        .padding(.vertical, 8)
        .padding(.horizontal, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            isSelected
                ? LuminaTheme.listSelectionBackground
                : Color.clear
        )
    }

    @ViewBuilder
    private var statusIcon: some View {
        Group {
            if isSelected {
                Image(systemName: "largecircle.fill.circle")
                    .foregroundStyle(LuminaTheme.accent)
            } else {
                switch item.summaryStatus {
                case "ready":
                    Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                case "running":
                    Image(systemName: "circle.lefthalf.filled").foregroundStyle(LuminaTheme.accent)
                case "failed", "error":
                    Image(systemName: "exclamationmark.circle").foregroundStyle(.red)
                default:
                    Image(systemName: "circle").foregroundStyle(.secondary)
                }
            }
        }
        .font(.body)
        .frame(width: 20, alignment: .center)
    }
}
