import Foundation
import Darwin

@MainActor
final class SidecarManager: ObservableObject {
    @Published var baseURL = URL(string: "http://127.0.0.1:17432")!
    @Published var isRunning = false
    @Published var isBootstrapping = false
    @Published var launchError: String?
    private var process: Process?

    private let host = "127.0.0.1"
    private let port = 17432
    private let maxLaunchAttempts = 5
    private let healthPollAttempts = 120
    private let healthPollDelayNs: UInt64 = 250_000_000

    private enum LaunchOutcome {
        case started
        case fatalError(String)
        case retryableError(String)
    }

    private struct HealthStatus: Decodable {
        let status: String
        let pid: Int32?
        let chunkerVersion: String?
        let coreVersion: String?
        let executable: String?
        let startedAt: Int?

        enum CodingKeys: String, CodingKey {
            case status
            case pid
            case chunkerVersion = "chunker_version"
            case coreVersion = "core_version"
            case executable
            case startedAt = "started_at"
        }
    }

    deinit {
        process?.terminate()
    }

    func ensureRunning() async {
        if isBootstrapping {
            while isBootstrapping {
                try? await Task.sleep(nanoseconds: 100_000_000)
            }
            return
        }

        isBootstrapping = true
        launchError = nil
        defer { isBootstrapping = false }

        if process != nil, await isHealthy() {
            isRunning = true
            return
        }

        // Reuse a leftover process only when it is this app version and this
        // bundled binary. Chunker version matching is not enough: ingest fixes
        // ship without bumping CHUNKER_VERSION, and in-place rebuilds keep the
        // same marketing version.
        if process == nil, let health = await healthStatus() {
            let bundled = bundledSidecarExecutable()
            if SidecarReadiness.shouldReplaceOrphan(
                chunkerVersion: health.chunkerVersion,
                coreVersion: health.coreVersion,
                expectedCoreVersion: expectedCoreVersion,
                hasBundledSidecar: bundled != nil,
                orphanExecutable: health.executable,
                bundledExecutable: bundled?.path,
                orphanStartedAt: health.startedAt.map { Date(timeIntervalSince1970: TimeInterval($0)) },
                bundledModifiedAt: bundledSidecarModifiedAt()
            ) {
                await terminateStaleSidecar(health)
            } else {
                isRunning = true
                launchError = nil
                return
            }
        }

        var lastError: String?
        for attempt in 1...maxLaunchAttempts {
            let outcome = launchSidecar()
            switch outcome {
            case .fatalError(let message):
                isRunning = false
                launchError = message
                return
            case .retryableError(let message):
                lastError = message
            case .started:
                for _ in 0..<healthPollAttempts {
                    try? await Task.sleep(nanoseconds: healthPollDelayNs)
                    if await isHealthy() {
                        isRunning = true
                        launchError = nil
                        return
                    }
                }
                lastError = "AI 引擎启动超时，请重试或退出。"
            }

            if attempt < maxLaunchAttempts {
                try? await Task.sleep(nanoseconds: 750_000_000)
            }
        }

        isRunning = false
        launchError = lastError ?? "AI 引擎启动超时，请重试或退出。"
    }

    /// Wait for ensureRunning to finish; true when healthy, false on failure.
    func waitUntilReady() async -> Bool {
        if isRunning { return true }
        if launchError != nil { return false }

        var sawBootstrapStart = isBootstrapping
        if !isBootstrapping {
            for _ in 0..<50 {
                if isRunning { return true }
                if isBootstrapping {
                    sawBootstrapStart = true
                    break
                }
                if launchError != nil { return false }
                try? await Task.sleep(nanoseconds: 100_000_000)
            }
        }

        if SidecarReadiness.shouldInvokeEnsureRunning(
            isRunning: isRunning,
            isBootstrapping: isBootstrapping,
            launchError: launchError,
            sawBootstrapStart: sawBootstrapStart
        ) {
            await ensureRunning()
        }

        while isBootstrapping {
            if isRunning { return true }
            try? await Task.sleep(nanoseconds: 100_000_000)
        }

        return SidecarReadiness.isReady(isRunning: isRunning, launchError: launchError)
    }

    func stop() {
        process?.terminate()
        process = nil
        isRunning = false
    }

    private var expectedCoreVersion: String {
        (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String) ?? ""
    }

    private func bundledSidecarModifiedAt() -> Date? {
        guard let bundled = bundledSidecarExecutable() else { return nil }
        let attrs = try? FileManager.default.attributesOfItem(atPath: bundled.path)
        return attrs?[.modificationDate] as? Date
    }

    private func isHealthy() async -> Bool {
        guard let health = await healthStatus() else { return false }
        return SidecarReadiness.isCompatible(
            chunkerVersion: health.chunkerVersion,
            coreVersion: health.coreVersion,
            expectedCoreVersion: expectedCoreVersion
        )
    }

    private func healthStatus() async -> HealthStatus? {
        guard let url = URL(string: "\(baseURL.absoluteString)/health") else { return nil }
        do {
            let (data, resp) = try await URLSession.shared.data(from: url)
            guard (resp as? HTTPURLResponse)?.statusCode == 200 else { return nil }
            let health = try JSONDecoder().decode(HealthStatus.self, from: data)
            return health.status == "ok" ? health : nil
        } catch {
            return nil
        }
    }

    private func terminateStaleSidecar(_ health: HealthStatus) async {
        let stalePID: Int32?
        if let reportedPID = health.pid {
            stalePID = reportedPID
        } else {
            stalePID = await legacyListenerPID()
        }
        guard let stalePID, stalePID > 1 else { return }
        Darwin.kill(stalePID, SIGTERM)
        for _ in 0..<20 {
            try? await Task.sleep(nanoseconds: 100_000_000)
            if await healthStatus() == nil { return }
        }
        Darwin.kill(stalePID, SIGKILL)
    }

    private func legacyListenerPID() async -> Int32? {
        let targetPort = port
        return await Task.detached(priority: .utility) {
            let process = Process()
            let output = Pipe()
            process.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
            process.arguments = [
                "-nP",
                "-iTCP:\(targetPort)",
                "-sTCP:LISTEN",
                "-t",
            ]
            process.standardOutput = output
            process.standardError = FileHandle.nullDevice
            do {
                try process.run()
                process.waitUntilExit()
                guard process.terminationStatus == 0 else { return nil }
                let data = output.fileHandleForReading.readDataToEndOfFile()
                let value = String(decoding: data, as: UTF8.self)
                    .split(whereSeparator: \.isWhitespace)
                    .first
                return value.flatMap { Int32($0) }
            } catch {
                return nil
            }
        }.value
    }

    private func launchSidecar() -> LaunchOutcome {
        process?.terminate()
        process = nil

        var env = ProcessInfo.processInfo.environment
        env["LUMINA_DATA_DIR"] = defaultDataDirectory()
        env["PATH"] = augmentedPATH(env["PATH"])
        // Local Ollama (127.0.0.1:11434) must not go through Clash/Surge/etc. or httpx gets HTTP 502.
        for key in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"] {
            env.removeValue(forKey: key)
        }

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
            return .fatalError("""
            未找到内置 AI 引擎。请从官网下载完整安装包，或使用开发者模式设置 LUMINA_CORE_DIR。
            """)
        }

        proc.standardOutput = FileHandle.nullDevice
        proc.standardError = openSidecarLogHandle() ?? FileHandle.nullDevice
        do {
            try proc.run()
            process = proc
            return .started
        } catch {
            return .retryableError("无法启动 AI 引擎：\(error.localizedDescription)")
        }
    }

    private func openSidecarLogHandle() -> FileHandle? {
        let logsDir = FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask).first!
            .appendingPathComponent("Logs/Lumina", isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: logsDir, withIntermediateDirectories: true)
            let logURL = logsDir.appendingPathComponent("sidecar.log")
            if !FileManager.default.fileExists(atPath: logURL.path) {
                FileManager.default.createFile(atPath: logURL.path, contents: nil)
            }
            let handle = try FileHandle(forWritingTo: logURL)
            try handle.seekToEnd()
            return handle
        } catch {
            return nil
        }
    }

    private func augmentedPATH(_ current: String?) -> String {
        let extras = [
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/Applications/Ollama.app/Contents/Resources",
        ]
        var parts = (current ?? "/usr/bin:/bin:/usr/sbin:/sbin")
            .split(separator: ":")
            .map(String.init)
        for extra in extras.reversed() {
            if !parts.contains(extra) {
                parts.insert(extra, at: 0)
            }
        }
        return parts.joined(separator: ":")
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
