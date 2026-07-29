import AppKit
import UniformTypeIdentifiers

enum BookExportOutcome: Equatable {
    case saved(URL)
    case cancelled
}

struct PendingBookExport: Equatable {
    let markdown: String
    let bookTitle: String
}

enum BookMarkdownExporter {
    static func fetchMarkdown(
        core: CoreClient,
        bookId: String,
        summaryReadyCount: Int,
        includeNotes: Bool
    ) async throws -> String {
        guard summaryReadyCount > 0 else {
            throw NSError(
                domain: "Lumina",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "尚无可用摘要，请先完成摘要生成"]
            )
        }

        let md = try await core.exportMarkdown(bookId: bookId, includeNotes: includeNotes)
        guard !md.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw NSError(
                domain: "Lumina",
                code: 2,
                userInfo: [NSLocalizedDescriptionKey: "导出内容为空，请稍后重试"]
            )
        }
        return md
    }

    @MainActor
    static func presentSavePanel(markdown: String, bookTitle: String) async throws -> BookExportOutcome {
        let panel = NSSavePanel()
        let baseName = sanitizeFilename(bookTitle)
        panel.nameFieldStringValue = "\(baseName)-summary.md"
        panel.allowedContentTypes = [.plainText]

        let response: NSApplication.ModalResponse
        if let window = NSApp.mainWindow ?? NSApp.keyWindow {
            response = await withCheckedContinuation { continuation in
                panel.beginSheetModal(for: window) { response in
                    continuation.resume(returning: response)
                }
            }
        } else {
            response = await panel.begin()
        }

        guard response == .OK, let url = panel.url else {
            return .cancelled
        }

        do {
            try markdown.write(to: url, atomically: true, encoding: .utf8)
        } catch {
            throw NSError(
                domain: "Lumina",
                code: 3,
                userInfo: [
                    NSLocalizedDescriptionKey: "保存失败：\(error.localizedDescription)",
                ]
            )
        }

        return .saved(url)
    }

    private static func sanitizeFilename(_ title: String) -> String {
        let invalid = CharacterSet(charactersIn: "/:\\?%*|\"<>")
        let cleaned = title.components(separatedBy: invalid).joined(separator: "-")
        let trimmed = cleaned.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? "summary" : trimmed
    }
}
