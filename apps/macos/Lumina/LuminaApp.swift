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
                .onReceive(NotificationCenter.default.publisher(for: NSApplication.willTerminateNotification)) { _ in
                    sidecar.stop()
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
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationWillFinishLaunching(_ notification: Notification) {
        guard let bundleID = Bundle.main.bundleIdentifier else { return }
        let others = NSRunningApplication.runningApplications(withBundleIdentifier: bundleID)
            .filter { $0 != NSRunningApplication.current }
        guard let existing = others.first else { return }
        existing.activate(options: [.activateAllWindows, .activateIgnoringOtherApps])
        exit(0)
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag {
            for window in sender.windows {
                window.makeKeyAndOrderFront(nil)
            }
        }
        return true
    }
}
