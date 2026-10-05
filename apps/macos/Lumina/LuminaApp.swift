import SwiftUI
import AppKit

@main
struct LuminaApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var sidecar = SidecarManager()
    @StateObject private var theme = ThemeManager()
    @StateObject private var core = CoreClient(baseURL: URL(string: "http://127.0.0.1:17432")!)

    var body: some Scene {
        // WindowGroup (not single Window): file-open launches that only hit
        // AppDelegate.application(_:open:) otherwise may never materialize UI.
        // matching "lumina" → only our reveal URL opens a scene; file opens stay in AppDelegate.
        WindowGroup("Lumina", id: MainWindowRevealPolicy.mainWindowId) {
            ContentView()
                .environmentObject(sidecar)
                .environmentObject(core)
                .environmentObject(theme)
                .preferredColorScheme(theme.colorScheme)
                .background(MainWindowRevealBridge())
                .onAppear {
                    appDelegate.sidecar = sidecar
                    ReadingProgressStore.shared.attach(core: core)
                    ShortcutKeyMonitor.install()
                }
        }
        .defaultSize(width: 1200, height: 800)
        .handlesExternalEvents(matching: Set([MainWindowRevealPolicy.urlScheme]))
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("导入书籍…") {
                    NotificationCenter.default.post(name: .luminaImportBook, object: nil)
                }
                // Shortcut: ShortcutStore / ShortcutKeyMonitor (default ⌘O; settings 可改)
            }
            CommandGroup(replacing: .help) {
                Button("Lumina 使用指南") {
                    NotificationCenter.default.post(name: .luminaOpenUsageGuide, object: nil)
                }
            }
            CommandGroup(after: .windowList) {
                Button("显示主窗口") {
                    AppDelegate.revealMainWindow()
                }
            }
        }
    }
}

/// Holds `@Environment(\.openWindow)` so AppDelegate can recreate the main scene.
private struct MainWindowRevealBridge: View {
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        Color.clear
            .frame(width: 0, height: 0)
            .accessibilityHidden(true)
            .onReceive(NotificationCenter.default.publisher(for: .luminaRevealMainWindow)) { _ in
                openWindow(id: MainWindowRevealPolicy.mainWindowId)
            }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    var sidecar: SidecarManager?

    private static let openFilesDistributedName = Notification.Name(
        "com.lumina.app.openFiles"
    )
    static let openFilesPathsKey = "paths"
    static let openFilesRevealKey = "reveal"

    private static var bufferedOpenPaths: [String] = []
    private static let bufferLock = NSLock()
    private static var uiAcceptsOpenFiles = false
    private static var isOpeningRevealURL = false

    func applicationWillFinishLaunching(_ notification: Notification) {
        guard let bundleID = Bundle.main.bundleIdentifier else { return }
        let others = NSRunningApplication.runningApplications(withBundleIdentifier: bundleID)
            .filter { $0 != NSRunningApplication.current && $0.isFinishedLaunching }
        guard let existing = others.first else {
            subscribeToForwardedOpenFiles()
            return
        }
        let paths = Self.pendingOpenPathsFromLaunch()
        let reveal = MainWindowRevealPolicy.shouldPostRevealWithForwardedPaths(paths)
        DistributedNotificationCenter.default().postNotificationName(
            Self.openFilesDistributedName,
            object: nil,
            userInfo: MainWindowRevealPolicy.distributedUserInfo(paths: paths, reveal: reveal),
            deliverImmediately: true
        )
        existing.activate(options: [.activateAllWindows, .activateIgnoringOtherApps])
        exit(0)
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        LuminaLayoutPerf.installWindowObserversIfNeeded()
        // File-open cold start can finish launch with no key window; reveal once.
        DispatchQueue.main.async {
            Self.revealMainWindow()
        }
    }

    func application(_ application: NSApplication, open urls: [URL]) {
        let files = urls.filter(\.isFileURL)
        let revealOnly = urls.contains(where: MainWindowRevealPolicy.isRevealURL) && files.isEmpty
        if !files.isEmpty {
            deliverOpenPaths(LibraryImportPolicy.pathsToForward(from: files))
        }
        if revealOnly {
            DispatchQueue.main.async {
                Self.revealMainWindow()
            }
            return
        }
        if !files.isEmpty {
            Self.revealMainWindow()
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        NSApp.activate(ignoringOtherApps: true)
        if flag {
            Self.revealMainWindow()
            return true
        }
        // No visible windows: return true so WindowGroup creates one.
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
        revealMainWindow()
    }

    static func revealMainWindow() {
        NSApp.activate(ignoringOtherApps: true)
        let windows = NSApp.windows
        let states = windows.map(windowState)
        dismissHelpTags(windows: windows, states: states)
        switch MainWindowRevealPolicy.action(for: states) {
        case .orderFrontExisting:
            orderFrontContentWindows(windows: windows, states: states)
        case .requestOpenMainWindow:
            NotificationCenter.default.post(name: .luminaRevealMainWindow, object: nil)
            // Bridge may be unmounted (all windows closed). Open via URL so
            // WindowGroup.handlesExternalEvents can create a scene.
            guard !isOpeningRevealURL else { return }
            let stillMissing = !states.contains(where: MainWindowRevealPolicy.countsAsMainWindow)
            guard stillMissing else { return }
            isOpeningRevealURL = true
            NSWorkspace.shared.open(MainWindowRevealPolicy.revealURL)
            DispatchQueue.main.async {
                isOpeningRevealURL = false
            }
        }
    }

    private static func windowState(_ window: NSWindow) -> MainWindowRevealPolicy.WindowState {
        MainWindowRevealPolicy.WindowState(
            isVisible: window.isVisible,
            isMiniaturized: window.isMiniaturized,
            isHelpTag: MainWindowRevealPolicy.isHelpTagWindow(
                className: NSStringFromClass(type(of: window))
            ),
            isPanel: window is NSPanel
        )
    }

    /// Order tooltip panels out before any `makeKey`. A help tag left visible
    /// becomes the only thing on screen after Finder「打开方式」.
    private static func dismissHelpTags(
        windows: [NSWindow],
        states: [MainWindowRevealPolicy.WindowState]
    ) {
        for (window, state) in zip(windows, states)
        where MainWindowRevealPolicy.revealStep(for: state) == .dismissHelpTag {
            window.orderOut(nil)
        }
        abortDisplayedToolTip()
    }

    /// `NSToolTipManager` is the AppKit object that owns the yellow `.help()` panel.
    /// There is no public dismiss. Ordering every window key leaves the last
    /// string (「点击预览新分界」) on screen; abort hides that panel.
    private static func abortDisplayedToolTip() {
        let names = ["NSToolTipManager", "_NSToolTipManager"]
        let shared = NSSelectorFromString("sharedToolTipManager")
        let abort = NSSelectorFromString("abortToolTip")
        for name in names {
            guard let cls = NSClassFromString(name) as? NSObject.Type,
                  cls.responds(to: shared),
                  let manager = cls.perform(shared)?.takeUnretainedValue() as? NSObject,
                  manager.responds(to: abort) else { continue }
            manager.perform(abort)
            return
        }
    }

    /// Panels first, ordinary windows last, so the main window ends up key.
    private static func orderFrontContentWindows(
        windows: [NSWindow],
        states: [MainWindowRevealPolicy.WindowState]
    ) {
        var panels: [NSWindow] = []
        var ordinary: [NSWindow] = []
        for (window, state) in zip(windows, states) {
            guard MainWindowRevealPolicy.revealStep(for: state) == .orderFront else { continue }
            if state.isPanel {
                panels.append(window)
            } else {
                ordinary.append(window)
            }
        }
        for window in panels {
            window.deminiaturize(nil)
            window.orderFront(nil)
        }
        for window in ordinary {
            window.deminiaturize(nil)
            window.makeKeyAndOrderFront(nil)
        }
    }

    private func subscribeToForwardedOpenFiles() {
        DistributedNotificationCenter.default().addObserver(
            forName: Self.openFilesDistributedName,
            object: nil,
            queue: .main
        ) { [weak self] note in
            let paths = (note.userInfo?[Self.openFilesPathsKey] as? [String]) ?? []
            let reveal = (note.userInfo?[Self.openFilesRevealKey] as? Bool)
                ?? MainWindowRevealPolicy.shouldPostRevealWithForwardedPaths(paths)
            self?.deliverOpenPaths(paths)
            if reveal {
                Self.revealMainWindow()
            }
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
