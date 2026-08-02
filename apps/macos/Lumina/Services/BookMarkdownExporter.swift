import AppKit
import SwiftUI
import UniformTypeIdentifiers

enum ExportFeedback: Identifiable {
    case success(URL)
    case cancelled
    case error(String)

    var id: String {
        switch self {
        case .success(let url):
            return "success-\(url.path)"
        case .cancelled:
            return "cancelled"
        case .error(let message):
            return "error-\(message)"
        }
    }
}

struct MarkdownExportDocument: FileDocument {
    static var readableContentTypes: [UTType] { [.plainText] }

    var text: String

    init(text: String) {
        self.text = text
    }

    init(configuration: ReadConfiguration) throws {
        text = ""
    }

    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
        FileWrapper(regularFileWithContents: Data(text.utf8))
    }
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

    static func defaultFilename(for bookTitle: String) -> String {
        "\(sanitizeFilename(bookTitle))-summary.md"
    }

    static func feedback(from result: Result<URL, Error>) -> ExportFeedback {
        switch result {
        case .success(let url):
            return .success(url)
        case .failure(let error) where isUserCancellation(error):
            return .cancelled
        case .failure(let error):
            return .error(error.localizedDescription)
        }
    }

    /// Fallback when SwiftUI `fileExporter` fails (matches import flow).
    @MainActor
    static func presentSavePanelFallback(markdown: String, bookTitle: String) -> ExportFeedback {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = defaultFilename(for: bookTitle)
        panel.allowedContentTypes = [.plainText]
        panel.canCreateDirectories = true

        NSApp.activate(ignoringOtherApps: true)
        guard panel.runModal() == .OK, let url = panel.url else {
            return .cancelled
        }

        do {
            try markdown.write(to: url, atomically: true, encoding: .utf8)
            return .success(url)
        } catch {
            return .error("保存失败：\(error.localizedDescription)")
        }
    }

    static func isUserCancellation(_ error: Error) -> Bool {
        if error is CancellationError { return true }
        let nsError = error as NSError
        return nsError.domain == NSCocoaErrorDomain && nsError.code == NSUserCancelledError
    }

    private static func sanitizeFilename(_ title: String) -> String {
        let invalid = CharacterSet(charactersIn: "/:\\?%*|\"<>")
        let cleaned = title.components(separatedBy: invalid).joined(separator: "-")
        let trimmed = cleaned.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? "summary" : trimmed
    }
}

extension View {
    func exportFeedbackAlert(_ feedback: Binding<ExportFeedback?>) -> some View {
        alert(item: feedback) { item in
            switch item {
            case .success(let url):
                Alert(
                    title: Text("导出成功"),
                    message: Text("已保存至\n\(url.path)"),
                    primaryButton: .default(Text("在 Finder 中显示")) {
                        NSWorkspace.shared.activateFileViewerSelecting([url])
                    },
                    secondaryButton: .cancel(Text("好"))
                )
            case .cancelled:
                Alert(
                    title: Text("已取消保存"),
                    dismissButton: .cancel(Text("好"))
                )
            case .error(let message):
                Alert(
                    title: Text("导出失败"),
                    message: Text(message),
                    dismissButton: .cancel(Text("好"))
                )
            }
        }
    }
}
