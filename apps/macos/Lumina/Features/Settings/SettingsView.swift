import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var core: CoreClient
    @EnvironmentObject private var theme: ThemeManager
    @State private var settings: AppSettings?
    @State private var ollamaStatus: OllamaStatus?
    @State private var error: String?
    @State private var saving = false

    var body: some View {
        Form {
            if let settings {
                Section("阅读") {
                    Picker("目标语言", selection: binding(\.target_language)) {
                        Text("简体中文").tag("zh-CN")
                        Text("English").tag("en-US")
                        Text("日本語").tag("ja-JP")
                    }
                    Toggle("联网搜索", isOn: binding(\.web_search_enabled))
                }

                Section("外观") {
                    Picker("主题", selection: $theme.appearance) {
                        ForEach(AppearanceMode.allCases) { mode in
                            Text(mode.label).tag(mode)
                        }
                    }
                }

                Section("Ollama") {
                    if let status = ollamaStatus {
                        LabeledContent("状态", value: status.ready ? "就绪" : "未就绪")
                        LabeledContent("推荐模型", value: status.model)
                        LabeledContent("内存", value: status.ram_gb)
                        if let msg = status.message, !msg.isEmpty, !status.ready {
                            Text(msg).font(.caption).foregroundStyle(.secondary)
                        }
                    } else {
                        ProgressView()
                    }
                }
            } else if let error {
                ContentUnavailableView("无法加载设置", systemImage: "gearshape", description: Text(error))
            } else {
                ProgressView("加载设置…")
            }
        }
        .formStyle(.grouped)
        .navigationTitle("设置")
        .task { await load() }
        .onChange(of: settings?.target_language) { _, _ in Task { await save() } }
        .onChange(of: settings?.web_search_enabled) { _, _ in Task { await save() } }
    }

    private func binding(_ keyPath: WritableKeyPath<AppSettings, String>) -> Binding<String> {
        Binding(
            get: { settings?[keyPath: keyPath] ?? "" },
            set: { settings?[keyPath: keyPath] = $0 }
        )
    }

    private func binding(_ keyPath: WritableKeyPath<AppSettings, Bool>) -> Binding<Bool> {
        Binding(
            get: { settings?[keyPath: keyPath] ?? false },
            set: { settings?[keyPath: keyPath] = $0 }
        )
    }

    private func load() async {
        do {
            settings = try await core.fetchSettings()
            ollamaStatus = try await core.fetchOllamaStatus()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func save() async {
        guard let settings, !saving else { return }
        saving = true
        defer { saving = false }
        do {
            self.settings = try await core.updateSettings(
                targetLanguage: settings.target_language,
                webSearchEnabled: settings.web_search_enabled
            )
        } catch {
            self.error = error.localizedDescription
        }
    }
}

struct AppSettings: Codable {
    var target_language: String
    var web_search_enabled: Bool
}

struct OllamaStatus: Codable {
    let installed: Bool
    let served: Bool
    let model: String
    let model_ready: Bool
    let ram_gb: String
    let message: String?

    var ready: Bool { served && model_ready }
}
