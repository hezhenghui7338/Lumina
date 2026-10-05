import SwiftUI
import AppKit
import ImageIO

struct BookRatingStars: View {
    let rating: Int?
    let onTap: (Int) -> Void

    var body: some View {
        HStack(spacing: 2) {
            Text("评分")
                .font(.caption2)
                .foregroundStyle(LuminaTheme.textSecondary)
            ForEach(1...5, id: \.self) { star in
                Button {
                    onTap(star)
                } label: {
                    Image(systemName: (rating ?? 0) >= star ? "star.fill" : "star")
                        .font(.caption2)
                        .foregroundStyle((rating ?? 0) >= star ? Color.orange : LuminaTheme.textSecondary)
                        .frame(width: 14, height: 14)
                }
                .buttonStyle(.borderless)
                .accessibilityLabel(starLabel(star))
            }
        }
        .help(rating.map { "\($0) 星，再点该星清除" } ?? "未评分，排序按 3 星")
    }

    private func starLabel(_ star: Int) -> String {
        if rating == star { return "清除评分" }
        return "评为 \(star) 星"
    }
}

struct BookCard: View {
    let book: BookSummary
    let isClassifying: Bool
    var ingestProgress: IngestProgress?
    var isSelectionMode: Bool = false
    var isChecked: Bool = false
    var coverURL: URL? = nil
    var onToggleCheck: (() -> Void)? = nil
    let onOpen: () -> Void
    let onToggleFavorite: () -> Void
    let onRename: () -> Void
    let onReclassify: () -> Void
    let onResegment: () -> Void
    let onExport: () -> Void
    let onDelete: () -> Void
    var onRate: ((Int) -> Void)? = nil
    var onStartSummarize: ((SummaryTier) -> Void)? = nil
    var onStopSummarize: (() -> Void)? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button(action: handleTap) {
                VStack(alignment: .leading, spacing: 8) {
                    ZStack(alignment: .topTrailing) {
                        cover
                        if isSelectionMode {
                            Image(systemName: isChecked ? "checkmark.circle.fill" : "circle")
                                .font(.title3)
                                .foregroundStyle(isChecked ? LuminaTheme.accent : .white.opacity(0.9))
                                .padding(8)
                        } else if book.isFavorite {
                            Image(systemName: "star.fill")
                                .font(.caption)
                                .foregroundStyle(.yellow)
                                .padding(8)
                        }
                    }
                    VStack(alignment: .leading, spacing: 4) {
                        Text(book.title)
                            .font(.headline)
                            .foregroundStyle(LuminaTheme.textPrimary)
                            .lineLimit(2)
                            .multilineTextAlignment(.leading)
                        Text(statusLine)
                            .font(.caption)
                            .foregroundStyle(LuminaTheme.textSecondary)
                            .lineLimit(2)
                            .frame(
                                maxWidth: .infinity,
                                minHeight: BookshelfGridCardMetrics.statusReservedHeight,
                                alignment: .topLeading
                            )
                        if showsProgressMeter {
                            progressMeter
                                .frame(height: BookshelfGridCardMetrics.meterReservedHeight)
                        }
                        HStack(spacing: 6) {
                            BookSummaryStateBadge(book: book)
                            Text(book.segmentCountLabel)
                            if let category = book.category, !category.isEmpty {
                                Text(category)
                            }
                        }
                        .font(.caption2)
                        .foregroundStyle(LuminaTheme.textSecondary)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            if let onRate {
                BookRatingStars(rating: book.starRating, onTap: onRate)
            }
        }
        .contextMenu { contextMenu }
    }

    private var showsProgressMeter: Bool {
        book.isSegmenting || (book.summaryTotal > 0 && !book.hasCompletedSummary)
    }

    @ViewBuilder
    private var progressMeter: some View {
        if book.isSegmenting {
            LibraryIngestMeter(progress: ingestProgress)
        } else {
            LibraryIngestMeter(
                fraction: Double(book.summaryReady) / Double(book.summaryTotal)
            )
        }
    }

    private var statusLine: String {
        if book.isSegmenting {
            return ingestProgress?.label ?? book.summaryFacetLabel
        }
        if book.isIngestFailed {
            return book.statusLabel
        }
        if book.summaryTotal > 0, !book.hasCompletedSummary {
            return book.progressLabel
        }
        return book.readingStatusLabel
    }

    private var cover: some View {
        RoundedRectangle(cornerRadius: 8, style: .continuous)
            .fill(Self.coverColor(for: book.category))
            .aspectRatio(3 / 4, contentMode: .fit)
            .overlay(alignment: .leading) {
                Rectangle()
                    .fill(.black.opacity(0.18))
                    .frame(width: 3)
            }
            .overlay {
                if let coverURL {
                    BookCoverImage(url: coverURL) {
                        coverTypography
                            .padding(EdgeInsets(top: 12, leading: 14, bottom: 12, trailing: 12))
                            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                    }
                    .accessibilityHidden(true)
                } else {
                    coverTypography
                        .padding(EdgeInsets(top: 12, leading: 14, bottom: 12, trailing: 12))
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                        .accessibilityHidden(true)
                }
            }
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(LuminaTheme.border, lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private var coverTypography: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(book.title)
                .font(.system(size: 17, weight: .semibold, design: .serif))
                .foregroundStyle(.white.opacity(0.95))
                .multilineTextAlignment(.leading)
                .lineLimit(5)
                .minimumScaleFactor(0.75)
                .frame(maxWidth: .infinity, alignment: .leading)
            Spacer(minLength: 0)
            if let author = book.author?.trimmingCharacters(in: .whitespacesAndNewlines),
               !author.isEmpty {
                Text(author)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(.white.opacity(0.82))
                    .lineLimit(2)
            }
        }
    }

    @ViewBuilder
    private var contextMenu: some View {
        bookLibraryContextMenu(
            book: book,
            onToggleFavorite: onToggleFavorite,
            onRename: onRename,
            onReclassify: onReclassify,
            onResegment: onResegment,
            onExport: onExport,
            onDelete: onDelete,
            onStartSummarize: onStartSummarize,
            onStopSummarize: onStopSummarize
        )
    }

    private func handleTap() {
        if isSelectionMode {
            onToggleCheck?()
        } else {
            onOpen()
        }
    }

    static func coverColor(for category: String?) -> Color {
        switch category {
        case "文学": return Color(red: 0.72, green: 0.38, blue: 0.32)
        case "历史": return Color(red: 0.55, green: 0.42, blue: 0.28)
        case "科技": return Color(red: 0.28, green: 0.45, blue: 0.62)
        case "哲学": return Color(red: 0.42, green: 0.36, blue: 0.58)
        case "经济": return Color(red: 0.28, green: 0.52, blue: 0.42)
        case "传记": return Color(red: 0.62, green: 0.42, blue: 0.28)
        default: return Color(red: 0.45, green: 0.46, blue: 0.50)
        }
    }
}

/// Determinate meter only. A spinning progress indicator on macOS
/// (NSProgressIndicator) can steal clicks from other bookshelf cards.
struct LibraryIngestMeter: View {
    var fraction: Double
    var dimmed: Bool

    init(progress: IngestProgress?) {
        let total = progress?.total ?? 0
        if total > 0, let page = progress?.page {
            fraction = min(1, max(0, Double(page) / Double(total)))
            dimmed = false
        } else {
            fraction = 0
            dimmed = true
        }
    }

    init(fraction: Double) {
        self.fraction = min(1, max(0, fraction))
        dimmed = false
    }

    var body: some View {
        ProgressView(value: fraction)
            .controlSize(.small)
            .tint(LuminaTheme.accent)
            .opacity(dimmed ? 0.45 : 1)
    }
}

/// Process-wide image cache so bookshelf poll / EnvironmentObject redraws do not
/// flash empty→image on every refresh. Full-resolution bitmaps are not kept:
/// a page of print-sized covers is tens of megabytes each, and an unbounded
/// cache of them is what pushed the app past 3GB overnight.
enum BookCoverImageCache {
    /// Card covers are ~150pt; 480px covers 3× retina without the print bitmap.
    static let coverMaxPixel = 480
    /// Inline figures can be content-width; still far below a 2700px scan.
    static let illustrationMaxPixel = 1400
    static let byteBudget = 32 * 1024 * 1024
    static let countLimit = 48

    static let images = NSCache<NSURL, NSImage>()
    private static let lock = NSLock()
    private static var failed = Set<NSURL>()
    private static let limitsReady: Bool = {
        images.countLimit = countLimit
        images.totalCostLimit = byteBudget
        return true
    }()
    /// Do not park full JPEG/PNG bodies in URLCache.shared next to the bitmaps.
    private static let session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.urlCache = nil
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        return URLSession(configuration: config)
    }()

    static func cacheKey(url: URL, maxPixel: Int) -> NSURL {
        guard var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            return url as NSURL
        }
        components.fragment = "px\(maxPixel)"
        return (components.url ?? url) as NSURL
    }

    static func image(for url: URL, maxPixel: Int) -> NSImage? {
        _ = limitsReady
        return images.object(forKey: cacheKey(url: url, maxPixel: maxPixel))
    }

    static func store(_ image: NSImage, for url: URL, maxPixel: Int) {
        _ = limitsReady
        let cost = max(1, Int(image.size.width * image.size.height * 4))
        images.setObject(image, forKey: cacheKey(url: url, maxPixel: maxPixel), cost: cost)
        lock.lock()
        failed.remove(url as NSURL)
        lock.unlock()
    }

    /// Decode a display-sized thumbnail so a print-resolution cover is not kept.
    static func thumbnail(data: Data, maxPixel: Int) -> NSImage? {
        let sourceOptions = [kCGImageSourceShouldCache: false] as CFDictionary
        guard let source = CGImageSourceCreateWithData(data as CFData, sourceOptions) else {
            return nil
        }
        let thumbOptions: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: max(1, maxPixel),
            kCGImageSourceShouldCacheImmediately: true,
        ]
        guard let cg = CGImageSourceCreateThumbnailAtIndex(source, 0, thumbOptions as CFDictionary) else {
            return nil
        }
        return NSImage(cgImage: cg, size: NSSize(width: cg.width, height: cg.height))
    }

    static func loadThumbnail(url: URL, maxPixel: Int) async -> NSImage? {
        if let cached = image(for: url, maxPixel: maxPixel) { return cached }
        if hasFailed(url) { return nil }
        do {
            let (data, response) = try await session.data(from: url)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                markFailed(url)
                return nil
            }
            guard let loaded = thumbnail(data: data, maxPixel: maxPixel) else {
                markFailed(url)
                return nil
            }
            store(loaded, for: url, maxPixel: maxPixel)
            return loaded
        } catch {
            markFailed(url)
            return nil
        }
    }

    static func markFailed(_ url: URL) {
        lock.lock()
        failed.insert(url as NSURL)
        lock.unlock()
    }

    static func hasFailed(_ url: URL) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        return failed.contains(url as NSURL)
    }
}

/// Stable cover loader: keeps the last successful image across parent re-renders.
struct BookCoverImage<Placeholder: View>: View {
    let url: URL
    var maxPixel: Int = BookCoverImageCache.coverMaxPixel
    var fillsFrame: Bool = true
    @ViewBuilder var placeholder: () -> Placeholder
    @State private var image: NSImage?

    var body: some View {
        ZStack {
            if let image {
                Image(nsImage: image)
                    .resizable()
                    .aspectRatio(contentMode: fillsFrame ? .fill : .fit)
            } else {
                placeholder()
            }
        }
        .task(id: "\(url.absoluteString)#\(maxPixel)") {
            image = await BookCoverImageCache.loadThumbnail(url: url, maxPixel: maxPixel)
        }
    }
}
