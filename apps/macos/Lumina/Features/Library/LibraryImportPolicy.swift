import Foundation

/// Shared whitelist and open-with classification for library import (macOS).
enum LibraryImportPolicy {
    static let supportedExtensions: Set<String> = [
        "txt", "text", "md", "markdown", "mdown", "mkd", "log",
        "pdf", "epub", "mobi", "azw", "azw3",
        "html", "htm", "xhtml", "rtf", "docx", "odt", "fb2",
    ]

    struct Classification: Equatable {
        var supportedPaths: [String]
        var unsupportedNames: [String]

        var isEmpty: Bool {
            supportedPaths.isEmpty && unsupportedNames.isEmpty
        }
    }

    static func isSupported(pathExtension: String) -> Bool {
        supportedExtensions.contains(pathExtension.lowercased())
    }

    static func classify(paths: [String]) -> Classification {
        var supported: [String] = []
        var unsupported: [String] = []
        for path in paths {
            let name = (path as NSString).lastPathComponent
            let ext = (path as NSString).pathExtension
            if isSupported(pathExtension: ext) {
                supported.append(path)
            } else {
                unsupported.append(name.isEmpty ? path : name)
            }
        }
        return Classification(supportedPaths: supported, unsupportedNames: unsupported)
    }

    static func unsupportedMessage(names: [String]) -> String {
        guard !names.isEmpty else { return "格式不支持" }
        if names.count == 1 {
            return "格式不支持：\(names[0])"
        }
        let preview = names.prefix(5).joined(separator: "、")
        let suffix = names.count > 5 ? " 等 \(names.count) 个文件" : ""
        return "格式不支持：\(preview)\(suffix)"
    }

    /// Absolute paths to hand off to an already-running instance (receiver classifies).
    static func pathsToForward(from urls: [URL]) -> [String] {
        urls.map { $0.path }.filter { !$0.isEmpty }
    }
}
