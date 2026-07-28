import Foundation
import AppKit

/// First-run helper: guide users to install Ollama (the only external AI runtime).
enum OllamaSetupHelper {
    static let downloadURL = URL(string: "https://ollama.com/download/mac")!

    static func isInstalled() -> Bool {
        let paths = ["/usr/local/bin/ollama", "/opt/homebrew/bin/ollama"]
        return paths.contains { FileManager.default.isExecutableFile(atPath: $0) }
            || shellWhich("ollama") != nil
    }

    static func openDownloadPage() {
        NSWorkspace.shared.open(downloadURL)
    }

    /// Pull recommended model after Ollama is installed (best-effort, background).
    static func pullRecommendedModel(model: String = "qwen3.5:4b") {
        guard let ollama = resolveOllamaPath() else { return }
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: ollama)
        proc.arguments = ["pull", model]
        proc.standardOutput = FileHandle.nullDevice
        proc.standardError = FileHandle.nullDevice
        try? proc.run()
    }

    private static func resolveOllamaPath() -> String? {
        if let p = shellWhich("ollama") { return p }
        for p in ["/usr/local/bin/ollama", "/opt/homebrew/bin/ollama"] {
            if FileManager.default.isExecutableFile(atPath: p) { return p }
        }
        return nil
    }

    private static func shellWhich(_ name: String) -> String? {
        let proc = Process()
        let pipe = Pipe()
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/which")
        proc.arguments = [name]
        proc.standardOutput = pipe
        proc.standardError = FileHandle.nullDevice
        do {
            try proc.run()
            proc.waitUntilExit()
            guard proc.terminationStatus == 0 else { return nil }
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let path = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
            return path?.isEmpty == false ? path : nil
        } catch {
            return nil
        }
    }
}
