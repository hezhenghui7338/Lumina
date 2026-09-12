import Foundation
import Darwin

@MainActor
final class SidecarManager: ObservableObject {
    @Published var baseURL = URL(string: "http://127.0.0.1:17432")!
    @Published var isRunning = false
    @Published var isBootstrapping = false
    @Published var userStopped = false
    @Published var launchError: String?
    /// Product-ready after cold-start gate phases (PRD §3.5).
    @Published var productReady = false
    @Published var coldStartPhases = ColdStartPhaseSnapshot.initial
    @Published var coldStartStartedAt = Date()
    private var process: Process?
    private var lastKnownPID: Int32?
    private var coldStartPollTask: Task<Void, Never>?

    private let host = "127.0.0.1"
    private let port = 17432
    private let maxLaunchAttempts = 5

    private lazy var probeSession: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = SidecarReadiness.probeTimeoutSeconds
        config.timeoutIntervalForResource = SidecarReadiness.probeTimeoutSeconds
        return URLSession(configuration: config)
    }()

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
        let uptimeMs: Int?

        enum CodingKeys: String, CodingKey {
            case status
            case pid
            case chunkerVersion = "chunker_version"
            case coreVersion = "core_version"
            case executable
            case startedAt = "started_at"
            case uptimeMs = "uptime_ms"
        }
    }

    private struct StartupStatusDTO: Decodable {
        let engine: String?
        let data: String?
        let cache: String?
        let news: String?
        let newsDetail: String?

        enum CodingKeys: String, CodingKey {
            case engine, data, cache, news
            case newsDetail = "news_detail"
        }
    }

    var engineStatus: SidecarEngineStatus {
        SidecarReadiness.engineStatus(
            isRunning: isRunning,
            isBootstrapping: isBootstrapping,
            userStopped: userStopped,
            launchError: launchError
        )
    }

    var engineStatusLabel: String {
        SidecarReadiness.statusLabel(engineStatus)
    }

    deinit {
        process?.terminate()
    }

    func ensureRunning() async {
        guard SidecarReadiness.shouldAutoStart(userStopped: userStopped) else {
            isRunning = false
            return
        }

        if isBootstrapping {
            while isBootstrapping {
                try? await Task.sleep(nanoseconds: 100_000_000)
            }
            return
        }

        isBootstrapping = true
        launchError = nil
        defer { isBootstrapping = false }

        if let proc = process, !proc.isRunning {
            process = nil
        }

        if process != nil, process?.isRunning == true, await isHealthy() {
            isRunning = true
            return
        }

        let health = await healthStatus()
        if let pid = health?.pid { lastKnownPID = pid }
        let listenerPID = await legacyListenerPID()
        let portOccupied = health != nil || listenerPID != nil
        let replaceOrphan: Bool
        if let health {
            let bundled = bundledSidecarExecutable()
            replaceOrphan = SidecarReadiness.shouldReplaceOrphan(
                chunkerVersion: health.chunkerVersion,
                coreVersion: health.coreVersion,
                expectedCoreVersion: expectedCoreVersion,
                hasBundledSidecar: bundled != nil,
                orphanExecutable: health.executable,
                bundledExecutable: bundled?.path,
                orphanStartedAt: health.startedAt.map { Date(timeIntervalSince1970: TimeInterval($0)) },
                bundledModifiedAt: bundledSidecarModifiedAt()
            )
        } else {
            replaceOrphan = false
        }

        let healthResponded = health != nil
        if SidecarReadiness.shouldReuseLeftover(
            healthResponded: healthResponded,
            shouldReplaceOrphan: replaceOrphan
        ), process == nil {
            isRunning = true
            launchError = nil
            return
        }

        if SidecarReadiness.shouldKillListenerBeforeLaunch(
            healthResponded: healthResponded,
            shouldReplaceOrphan: replaceOrphan,
            portOccupied: portOccupied
        ) {
            await terminateListener(reportedPID: health?.pid)
        }

        var lastError: String?
        for attempt in 1...maxLaunchAttempts {
            let spawnAt = Date()
            let outcome = launchSidecar()
            switch outcome {
            case .fatalError(let message):
                isRunning = false
                launchError = message
                appendHostLog("launch fatal: \(message)")
                return
            case .retryableError(let message):
                lastError = message
                appendHostLog("launch retryable: \(message)")
            case .started:
                let poll = await pollUntilReady(spawnAt: spawnAt)
                switch poll {
                case .ready:
                    isRunning = true
                    launchError = nil
                    return
                case .failed(let message, let retryable):
                    lastError = message
                    await terminateListener(reportedPID: process.flatMap { Int32($0.processIdentifier) })
                    if !retryable {
                        isRunning = false
                        launchError = message
                        return
                    }
                }
            }

            if attempt < maxLaunchAttempts {
                try? await Task.sleep(nanoseconds: 750_000_000)
            }
        }

        isRunning = false
        launchError = lastError ?? SidecarReadiness.messageTimeout
    }

    private enum PollResult {
        case ready
        /// retryable=false for identity mismatch (relaunching the same binary cannot help).
        case failed(String, retryable: Bool)
    }

    /// Probe immediately, then back off. Incompatible health / exited process fail-fast.
    private func pollUntilReady(spawnAt: Date) async -> PollResult {
        let budget = SidecarReadiness.healthPollBudgetSeconds
        var probeIndex = 0
        var firstHealthMs: Int?
        while Date().timeIntervalSince(spawnAt) < budget {
            let health = await healthStatus()
            if health != nil, firstHealthMs == nil {
                firstHealthMs = Int(Date().timeIntervalSince(spawnAt) * 1000)
            }
            let compatible = health.map {
                SidecarReadiness.isCompatible(
                    chunkerVersion: $0.chunkerVersion,
                    coreVersion: $0.coreVersion,
                    expectedCoreVersion: expectedCoreVersion
                )
            } ?? false
            if let health, let pid = health.pid { lastKnownPID = pid }
            let processRunning = process.map(\.isRunning)
            let decision = SidecarReadiness.evaluateHealthPoll(
                healthResponded: health != nil,
                compatible: compatible,
                processStillRunning: processRunning
            )
            switch decision {
            case .ready:
                let readyMs = Int(Date().timeIntervalSince(spawnAt) * 1000)
                appendHostLog(
                    "ready spawn_to_first_health_ms=\(firstHealthMs ?? readyMs) spawn_to_ready_ms=\(readyMs) uptime_ms=\(health?.uptimeMs.map(String.init) ?? "?")"
                )
                return .ready
            case .incompatible:
                let detail = SidecarReadiness.incompatibleDetailMessage(
                    chunkerVersion: health?.chunkerVersion,
                    coreVersion: health?.coreVersion,
                    expectedCoreVersion: expectedCoreVersion
                )
                appendHostLog(
                    "incompatible after \(Int(Date().timeIntervalSince(spawnAt) * 1000))ms: \(detail)"
                )
                return .failed(detail, retryable: false)
            case .processExited:
                let msg = SidecarReadiness.messageProcessExited
                appendHostLog("process exited after \(Int(Date().timeIntervalSince(spawnAt) * 1000))ms")
                return .failed(msg, retryable: true)
            case .keepWaiting:
                let delay = SidecarReadiness.healthPollDelayNanoseconds(afterProbeIndex: probeIndex)
                probeIndex += 1
                try? await Task.sleep(nanoseconds: delay)
            }
        }
        appendHostLog(
            "timeout after \(Int(Date().timeIntervalSince(spawnAt) * 1000))ms first_health_ms=\(firstHealthMs.map(String.init) ?? "none")"
        )
        return .failed(SidecarReadiness.messageTimeout, retryable: true)
    }

    private func appendHostLog(_ message: String) {
        let logsDir = FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask).first!
            .appendingPathComponent("Logs/Lumina", isDirectory: true)
        let logURL = logsDir.appendingPathComponent("sidecar.log")
        let line = "[sidecar-host] \(ISO8601DateFormatter().string(from: Date())) \(message)\n"
        guard let data = line.data(using: .utf8) else { return }
        do {
            try FileManager.default.createDirectory(at: logsDir, withIntermediateDirectories: true)
            if !FileManager.default.fileExists(atPath: logURL.path) {
                FileManager.default.createFile(atPath: logURL.path, contents: nil)
            }
            let handle = try FileHandle(forWritingTo: logURL)
            defer { try? handle.close() }
            try handle.seekToEnd()
            try handle.write(contentsOf: data)
        } catch {
            // Best-effort diagnostics only.
        }
    }

    /// Wait for ensureRunning to finish; true when healthy, false on failure.
    func waitUntilReady() async -> Bool {
        if userStopped { return false }
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

    func stop(userInitiated: Bool) async {
        if userInitiated {
            userStopped = true
        }
        coldStartPollTask?.cancel()
        coldStartPollTask = nil
        // Keep productReady on user stop so Settings stays reachable to restart.
        if !userInitiated {
            productReady = false
            coldStartPhases = .initial
        }
        await requestShutdown()
        let ownedPID = process.flatMap { $0.isRunning ? Int32($0.processIdentifier) : nil }
        let listenerPID = await legacyListenerPID()
        await terminatePIDs(
            [ownedPID, lastKnownPID, listenerPID].compactMap { $0 }
        )
        process = nil
        lastKnownPID = nil
        isRunning = false
        if userInitiated {
            launchError = nil
        }
    }

    func restart() async {
        userStopped = false
        launchError = nil
        await stop(userInitiated: false)
        await ensureRunningAndProductReady()
    }

    /// Spawn / reuse sidecar, then wait until data/cache/news phases are terminal.
    func ensureRunningAndProductReady() async {
        coldStartStartedAt = Date()
        productReady = false
        coldStartPhases = ColdStartReadiness.merge(
            engineDone: false,
            data: "pending",
            cache: "pending",
            news: "pending",
            newsDetail: nil
        )
        await ensureRunning()
        guard isRunning else {
            coldStartPhases.engine = .pending
            return
        }
        coldStartPhases = ColdStartReadiness.merge(
            engineDone: true,
            data: "running",
            cache: "pending",
            news: "pending",
            newsDetail: nil
        )
        await pollUntilProductReady()
    }

    private func pollUntilProductReady() async {
        coldStartPollTask?.cancel()
        let task = Task { @MainActor in
            while !Task.isCancelled {
                if let dto = await startupStatus() {
                    let snap = ColdStartReadiness.merge(
                        engineDone: true,
                        data: dto.data,
                        cache: dto.cache,
                        news: dto.news,
                        newsDetail: dto.newsDetail
                    )
                    coldStartPhases = snap
                    if ColdStartReadiness.isProductReady(snap) {
                        productReady = true
                        return
                    }
                }
                try? await Task.sleep(
                    nanoseconds: ColdStartReadiness.statusPollIntervalNanoseconds
                )
            }
        }
        coldStartPollTask = task
        await task.value
    }

    private func startupStatus() async -> StartupStatusDTO? {
        var request = URLRequest(url: baseURL.appendingPathComponent("startup/status"))
        request.timeoutInterval = SidecarReadiness.probeTimeoutSeconds
        do {
            let (data, response) = try await probeSession.data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                return nil
            }
            return try JSONDecoder().decode(StartupStatusDTO.self, from: data)
        } catch {
            return nil
        }
    }

    private var expectedCoreVersion: String {
        let raw = (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String) ?? ""
        return SidecarReadiness.normalizeVersion(raw)
    }

    private func bundledSidecarModifiedAt() -> Date? {
        guard let bundled = bundledSidecarExecutable() else { return nil }
        let attrs = try? FileManager.default.attributesOfItem(atPath: bundled.path)
        return attrs?[.modificationDate] as? Date
    }

    private func isHealthy() async -> Bool {
        guard let health = await healthStatus() else { return false }
        if let pid = health.pid { lastKnownPID = pid }
        return SidecarReadiness.isCompatible(
            chunkerVersion: health.chunkerVersion,
            coreVersion: health.coreVersion,
            expectedCoreVersion: expectedCoreVersion
        )
    }

    private func healthStatus() async -> HealthStatus? {
        guard let url = URL(string: "\(baseURL.absoluteString)/health") else { return nil }
        do {
            let (data, resp) = try await probeSession.data(from: url)
            guard (resp as? HTTPURLResponse)?.statusCode == 200 else { return nil }
            let health = try JSONDecoder().decode(HealthStatus.self, from: data)
            return health.status == "ok" ? health : nil
        } catch {
            return nil
        }
    }

    private func requestShutdown() async {
        guard let url = URL(string: "\(baseURL.absoluteString)/shutdown") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = SidecarReadiness.probeTimeoutSeconds
        _ = try? await probeSession.data(for: request)
    }

    private func terminateListener(reportedPID: Int32?) async {
        let listenerPID = await legacyListenerPID()
        await terminatePIDs([reportedPID, lastKnownPID, listenerPID].compactMap { $0 })
        process?.terminate()
        process = nil
    }

    private func terminatePIDs(_ pids: [Int32]) async {
        let unique = Array(Set(pids.filter { $0 > 1 }))
        guard !unique.isEmpty else { return }
        var tree: [Int32] = []
        for pid in unique {
            tree.append(contentsOf: await descendantPIDs(of: pid))
            tree.append(pid)
        }
        let all = Array(Set(tree.filter { $0 > 1 }))
        for pid in all {
            Darwin.kill(pid, SIGTERM)
        }
        for _ in 0..<20 {
            try? await Task.sleep(nanoseconds: 100_000_000)
            if await healthStatus() == nil, await legacyListenerPID() == nil {
                return
            }
        }
        for pid in all {
            Darwin.kill(pid, SIGKILL)
        }
        try? await Task.sleep(nanoseconds: 100_000_000)
    }

    private func descendantPIDs(of pid: Int32) async -> [Int32] {
        var found: [Int32] = []
        var queue: [Int32] = [pid]
        var seen: Set<Int32> = []
        while let current = queue.first {
            queue.removeFirst()
            guard seen.insert(current).inserted else { continue }
            let children = await directChildPIDs(of: current)
            found.append(contentsOf: children)
            queue.append(contentsOf: children)
        }
        return found
    }

    private func directChildPIDs(of pid: Int32) async -> [Int32] {
        await Task.detached(priority: .utility) {
            let process = Process()
            let output = Pipe()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/pgrep")
            process.arguments = ["-P", "\(pid)"]
            process.standardOutput = output
            process.standardError = FileHandle.nullDevice
            do {
                try process.run()
                process.waitUntilExit()
                guard process.terminationStatus == 0 else { return [] }
                let data = output.fileHandleForReading.readDataToEndOfFile()
                return String(decoding: data, as: UTF8.self)
                    .split(whereSeparator: \.isWhitespace)
                    .compactMap { Int32($0) }
                    .filter { $0 > 1 }
            } catch {
                return []
            }
        }.value
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
        proc.terminationHandler = { [weak self] finished in
            Task { @MainActor in
                guard let self, self.process === finished else { return }
                self.process = nil
                if self.isRunning {
                    self.isRunning = false
                }
            }
        }
        do {
            try proc.run()
            process = proc
            lastKnownPID = Int32(proc.processIdentifier)
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
