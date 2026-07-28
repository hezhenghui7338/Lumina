import Foundation

@MainActor
final class SidecarManager: ObservableObject {
    @Published var baseURL = URL(string: "http://127.0.0.1:17432")!
    @Published var isRunning = false
    @Published var launchError: String?
    private var process: Process?

    private let host = "127.0.0.1"
    private let port = 17432

    func ensureRunning() async {
        if await isHealthy() {
            isRunning = true
            launchError = nil
            return
        }
        launchSidecar()
        for _ in 0..<60 {
            try? await Task.sleep(nanoseconds: 250_000_000)
            if await isHealthy() {
                isRunning = true
                launchError = nil
                return
            }
        }
        if !isRunning {
            launchError = launchError ?? "AI 引擎启动超时，请重启 Lumina。"
        }
    }

    private func isHealthy() async -> Bool {
        guard let url = URL(string: "\(baseURL.absoluteString)/health") else { return false }
        do {
            let (_, resp) = try await URLSession.shared.data(from: url)
            return (resp as? HTTPURLResponse)?.statusCode == 200
        } catch {
            return false
        }
    }

    private func launchSidecar() {
        guard process == nil else { return }

        var env = ProcessInfo.processInfo.environment
        env["LUMINA_DATA_DIR"] = defaultDataDirectory()

        let proc = Process()
        proc.environment = env

        if let bundled = bundledSidecarExecutable() {
            proc.executableURL = bundled
            proc.currentDirectoryURL = bundled.deletingLastPathComponent()
            proc.arguments = ["--host", host, "--port", "\(port)"]
        } else if let devDir = resolveDevCoreDirectory() {
            proc.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            proc.arguments = ["uv", "run", "lumina-core", "--host", host, "--port", "\(port)"]
            proc.currentDirectoryURL = devDir
        } else {
            launchError = """
            未找到内置 AI 引擎。请从官网下载完整安装包，或使用开发者模式设置 LUMINA_CORE_DIR。
            """
            return
        }

        proc.standardOutput = FileHandle.nullDevice
        proc.standardError = FileHandle.nullDevice
        do {
            try proc.run()
            process = proc
        } catch {
            launchError = "无法启动 AI 引擎：\(error.localizedDescription)"
        }
    }

    /// Release build: Contents/Resources/lumina-core/lumina-core
    private func bundledSidecarExecutable() -> URL? {
        guard let resources = Bundle.main.resourceURL else { return nil }
        let exe = resources
            .appendingPathComponent("lumina-core", isDirectory: true)
            .appendingPathComponent("lumina-core")
        return FileManager.default.isExecutableFile(atPath: exe.path) ? exe : nil
    }

    /// Dev only: uv run from repo when LUMINA_CORE_DIR or sibling packages/lumina-core exists.
    private func resolveDevCoreDirectory() -> URL? {
        #if DEBUG
        if let override = ProcessInfo.processInfo.environment["LUMINA_CORE_DIR"] {
            let url = URL(fileURLWithPath: override)
            if FileManager.default.fileExists(atPath: url.path) { return url }
        }
        let cwd = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        let candidates = [
            cwd.appendingPathComponent("packages/lumina-core"),
            cwd.deletingLastPathComponent().appendingPathComponent("packages/lumina-core"),
            cwd.deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("packages/lumina-core"),
            URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("code/Lumina/packages/lumina-core"),
        ]
        return candidates.first { FileManager.default.fileExists(atPath: $0.path) }
        #else
        if let override = ProcessInfo.processInfo.environment["LUMINA_CORE_DIR"] {
            let url = URL(fileURLWithPath: override)
            if FileManager.default.fileExists(atPath: url.path) { return url }
        }
        return nil
        #endif
    }

    private func defaultDataDirectory() -> String {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        return base.appendingPathComponent("Lumina").path
    }
}
