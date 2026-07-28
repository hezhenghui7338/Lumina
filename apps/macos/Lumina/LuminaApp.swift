import SwiftUI

@main
struct LuminaApp: App {
    @StateObject private var sidecar = SidecarManager()
    @StateObject private var theme = ThemeManager()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(sidecar)
                .environmentObject(CoreClient(baseURL: sidecar.baseURL))
                .environmentObject(theme)
                .preferredColorScheme(theme.colorScheme)
                .task { await sidecar.ensureRunning() }
        }
        .defaultSize(width: 1200, height: 800)
    }
}
