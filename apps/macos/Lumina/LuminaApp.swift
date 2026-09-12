import SwiftUI
import AppKit

@main
struct LuminaApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var sidecar = SidecarManager()
    @StateObject private var theme = ThemeManager()
    @StateObject private var core = CoreClient(baseURL: URL(string: "http://127.0.0.1:17432")!)

    var body: some Scene {
        Window("Lumina", id: "main") {
            ContentView()
                .environmentObject(sidecar)
                .environmentObject(core)
                .environmentObject(theme)
                .preferredColorScheme(theme.colorScheme)
                .onAppear {
                    appDelegate.sidecar = sidecar
                    ReadingProgressStore.shared.attach(core: core)
                }
        }
        .defaultSize(width: 1200, height: 800)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("导入书籍…") {
                    NotificationCenter.default.post(name: .luminaImportBook, object: nil)
                }
                .keyboardShortcut("o", modifiers: .command)
            }
            CommandGroup(replacing: .help) {
                Button("Lumina 使用指南") {
                    NotificationCenter.default.post(name: .luminaOpenUsageGuide, object: nil)
                }
            }
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    var sidecar: SidecarManager?

    private static let openFilesDistributedName = Notification.Name(
        "com.lumina.app.openFiles"
    )
    static let openFilesPathsKey = "paths"

    private static var bufferedOpenPaths: [String] = []
    private static let bufferLock = NSLock()
    private static var uiAcceptsOpenFiles = false

    func applicationWillFinishLaunching(_ notification: Notification) {
        guard let bundleID = Bundle.main.bundleIdentifier else { return }
        let others = NSRunningApplication.runningApplications(withBundleIdentifier: bundleID)
            .filter { $0 != NSRunningApplication.current }
        guard let existing = others.first else {
            subscribeToForwardedOpenFiles()
            return
        }
        let paths = Self.pendingOpenPathsFromLaunch()
        if !paths.isEmpty {
            DistributedNotificationCenter.default().postNotificationName(
                Self.openFilesDistributedName,
                object: nil,
                userInfo: [Self.openFilesPathsKey: paths],
                deliverImmediately: true
            )
        }
        existing.activate(options: [.activateAllWindows, .activateIgnoringOtherApps])
        exit(0)
    }

    func application(_ application: NSApplication, open urls: [URL]) {
        deliverOpenPaths(LibraryImportPolicy.pathsToForward(from: urls))
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag {
            for window in sender.windows {
                window.makeKeyAndOrderFront(nil)
            }
        }
        return true
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        Task { @MainActor in
            await ReadingProgressStore.shared.flushAll()
            await sidecar?.stop(userInitiated: false)
            sender.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }

    /// Call when ContentView is ready to receive open-file notifications.
    static func markUIReadyForOpenFiles() {
        bufferLock.lock()
        uiAcceptsOpenFiles = true
        let pending = bufferedOpenPaths
        bufferedOpenPaths = []
        bufferLock.unlock()
        guard !pending.isEmpty else { return }
        NotificationCenter.default.post(
            name: .luminaOpenFiles,
            object: nil,
            userInfo: [openFilesPathsKey: pending]
        )
    }

    private func subscribeToForwardedOpenFiles() {
        DistributedNotificationCenter.default().addObserver(
            forName: Self.openFilesDistributedName,
            object: nil,
            queue: .main
        ) { [weak self] note in
            let paths = (note.userInfo?[Self.openFilesPathsKey] as? [String]) ?? []
            self?.deliverOpenPaths(paths)
        }
    }

    private func deliverOpenPaths(_ paths: [String]) {
        guard !paths.isEmpty else { return }
        Self.bufferLock.lock()
        if Self.uiAcceptsOpenFiles {
            Self.bufferLock.unlock()
            NotificationCenter.default.post(
                name: .luminaOpenFiles,
                object: nil,
                userInfo: [Self.openFilesPathsKey: paths]
            )
            return
        }
        Self.bufferedOpenPaths.append(contentsOf: paths)
        Self.bufferLock.unlock()
    }

    /// Collect paths from the open-documents Apple Event and argv before a duplicate instance exits.
    static func pendingOpenPathsFromLaunch() -> [String] {
        var urls: [URL] = []
        if let event = NSAppleEventManager.shared().currentAppleEvent,
           event.eventClass == AEEventClass(kCoreEventClass),
           event.eventID == AEEventID(kAEOpenDocuments),
           let list = event.paramDescriptor(forKeyword: keyDirectObject) {
            let count = list.numberOfItems
            if count > 0 {
                for index in 1...count {
                    guard let item = list.atIndex(index),
                          let url = item.fileURLValue else { continue }
                    urls.append(url)
                }
            }
        }
        let argPaths = CommandLine.arguments.dropFirst().compactMap { arg -> URL? in
            guard arg.hasPrefix("/") || arg.hasPrefix("~") else { return nil }
            let expanded = (arg as NSString).expandingTildeInPath
            var isDir: ObjCBool = false
            guard FileManager.default.fileExists(atPath: expanded, isDirectory: &isDir),
                  !isDir.boolValue else { return nil }
            return URL(fileURLWithPath: expanded)
        }
        urls.append(contentsOf: argPaths)
        var seen = Set<String>()
        var unique: [URL] = []
        for url in urls {
            let path = url.path
            if seen.insert(path).inserted {
                unique.append(url)
            }
        }
        return LibraryImportPolicy.pathsToForward(from: unique)
    }
}
