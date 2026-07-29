import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var core: CoreClient
    @EnvironmentObject private var sidecar: SidecarManager
    @EnvironmentObject private var theme: ThemeManager
    @State private var settings: AppSettings?
    @State private var error: String?
    @State private var saving = false
    @State private var tavilyAPIKey = ""
    @State private var tavilyKeyConfigured = false
    @State private var resourceAPIKeys: [String: String] = [:]
    @State private var resourceKeyConfigured: Set<String> = []
    @State private var editingResource: ModelResourceSettings?
    @State private var showingAddResource = false
    @State private var resourceStatuses: [String: ResourceStatus] = [:]
    @State private var loadingResourceStatuses = false

    var body: some View {
        Form {
            if let settings {
                Section("阅读") {
                    Picker("目标语言", selection: binding(\.target_language)) {
                        Text("简体中文").tag("zh-CN")
                        Text("English").tag("en-US")
                        Text("日本語").tag("ja-JP")
                    }
                }

                webSearchSection(settings: settings)

                apiResourcesSection(settings: settings)

                prioritySection(
                    title: "深聊",
                    route: chatRouteBinding,
                    footer: "按顺序尝试，失败或超时自动 fallback 到下一资源。"
                )

                prioritySection(
                    title: "摘要",
                    route: summarizeRouteBinding,
                    footer: "翻译与摘要共用此优先级链。靠前的资源优先使用。各资源的并发在 API 资源编辑中配置。"
                )

                Section("外观") {
                    Picker("主题", selection: $theme.appearance) {
                        ForEach(AppearanceMode.allCases) { mode in
                            Text(mode.label).tag(mode)
                        }
                    }
                }

                Section {
                    NavigationLink("RSS 信源") {
                        NewsSourcesSettingsView()
                    }
                } header: {
                    Text("资讯")
                } footer: {
                    Text("管理订阅源；可添加 RSSHub 等自定义 RSS 地址。")
                }

                Section("关于") {
                    HStack(spacing: 14) {
                        Image("LuminaMark")
                            .resizable()
                            .scaledToFit()
                            .frame(width: 48, height: 48)
                            .accessibilityHidden(true)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Lumina")
                                .font(.headline)
                            Text("Local AI Reading Companion")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Text("版本 \(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.2.0")")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                    }
                    .padding(.vertical, 4)
                    Link("GitHub 仓库", destination: AppLinks.githubRepository)
                        .font(.caption)
                    Link("反馈问题", destination: AppLinks.githubIssues)
                        .font(.caption)
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
        .refreshable { await refreshResourceStatuses() }
        .onChange(of: settings?.target_language) { _, _ in Task { await save() } }
        .onChange(of: settings?.web_search_provider) { _, _ in Task { await save() } }
        .sheet(item: $editingResource) { resource in
            ResourceEditorSheet(
                resource: resourceBinding(for: resource.id),
                apiKey: resourceKeyBinding(for: resource.id),
                keyConfigured: keyConfigured(for: resource.id),
                core: core,
                onSave: { Task { await save() } }
            )
        }
        .sheet(isPresented: $showingAddResource) {
            AddResourceSheet(
                onAdd: { newResource in
                    guard var s = settings else { return }
                    s.models.resources.append(newResource)
                    settings = s
                    showingAddResource = false
                    Task { await save() }
                },
                onCancel: { showingAddResource = false }
            )
        }
    }

    @ViewBuilder
    private func webSearchSection(settings: AppSettings) -> some View {
        Section {
            Picker("检索后端", selection: binding(\.web_search_provider)) {
                Text("ddgs（免费）").tag("ddgs")
                Text("Tavily（效果更好）").tag("tavily")
            }
            if settings.web_search_provider == "tavily" {
                SecureField(
                    tavilyKeyConfigured && tavilyAPIKey.isEmpty
                        ? "已保存（输入新 Key 可替换）"
                        : "Tavily API Key",
                    text: $tavilyAPIKey
                )
                .onSubmit { Task { await save() } }
                Button("保存 Tavily Key") {
                    Task { await save() }
                }
            }
        } header: {
            Text("联网搜索")
        } footer: {
            Text("免费默认 ddgs；要更稳的检索结果建议配置 Tavily。")
        }
    }

    @ViewBuilder
    private func apiResourcesSection(settings: AppSettings) -> some View {
        Section {
            ForEach(settings.models.resources) { resource in
                apiResourceRow(resource)
            }
            Button("添加自定义资源") {
                showingAddResource = true
            }
        } header: {
            Text("API 资源")
        } footer: {
            Text("Ollama 只是 API 的一种。在此配置各 endpoint，再在下方深聊/摘要入口关联优先级。")
        }
    }

    private func apiResourceRow(_ resource: ModelResourceSettings) -> some View {
        Button {
            editingResource = resource
        } label: {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(resourceDisplayName(resource))
                        .foregroundStyle(.primary)
                    Text("\(resource.model.isEmpty ? "未设模型" : resource.model) · \(resource.provider)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                resourceStatusBadge(for: resource.id)
                if resourceNeedsKey(resource) {
                    Text(keyConfigured(for: resource.id) ? "Key 已存" : "需 Key")
                        .font(.caption2)
                        .foregroundStyle(keyConfigured(for: resource.id) ? Color.secondary : Color.orange)
                }
                Image(systemName: "chevron.right")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private func prioritySection(
        title: String,
        route: Binding<ProfileRouteSettings>,
        footer: String
    ) -> some View {
        Section {
            if route.wrappedValue.priority.isEmpty {
                Text("未配置资源")
                    .foregroundStyle(.secondary)
            }
            ForEach(Array(route.wrappedValue.priority.enumerated()), id: \.element) { index, resourceId in
                if let resource = settings?.models.resource(id: resourceId) {
                    HStack {
                        Text("\(index + 1).")
                            .foregroundStyle(.secondary)
                            .frame(width: 20, alignment: .trailing)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(resourceDisplayName(resource))
                            Text(resource.model)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        if resourceStatuses[resourceId]?.ready == false {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .font(.caption)
                                .foregroundStyle(.orange)
                                .help(resourceStatuses[resourceId]?.message ?? "资源未就绪")
                        }
                        HStack(spacing: 4) {
                            Button {
                                movePriority(in: route, from: index, direction: -1)
                            } label: {
                                Image(systemName: "chevron.up")
                            }
                            .disabled(index == 0)
                            Button {
                                movePriority(in: route, from: index, direction: 1)
                            } label: {
                                Image(systemName: "chevron.down")
                            }
                            .disabled(index >= route.wrappedValue.priority.count - 1)
                            Button(role: .destructive) {
                                removePriority(route: route, at: index)
                            } label: {
                                Image(systemName: "minus.circle")
                            }
                        }
                        .buttonStyle(.borderless)
                    }
                }
            }
            Menu("添加资源到链") {
                let available = availableResources(for: route.wrappedValue)
                if available.isEmpty {
                    Button("暂无可用资源（请先配置并确保连通）") {}
                        .disabled(true)
                } else {
                    ForEach(available) { resource in
                        Button(resourceDisplayName(resource)) {
                            appendPriority(route: route, resourceId: resource.id)
                        }
                    }
                }
            }
        } header: {
            Text(title)
        } footer: {
            Text(footer)
        }
    }

    private var chatRouteBinding: Binding<ProfileRouteSettings> {
        routeBinding(\.chat)
    }

    private var summarizeRouteBinding: Binding<ProfileRouteSettings> {
        routeBinding(\.summarize)
    }

    private func routeBinding(_ keyPath: WritableKeyPath<ModelsSettings, ProfileRouteSettings>) -> Binding<ProfileRouteSettings> {
        Binding(
            get: { settings?.models[keyPath: keyPath] ?? ProfileRouteSettings() },
            set: { newValue in
                guard var s = settings else { return }
                s.models[keyPath: keyPath] = newValue
                settings = s
            }
        )
    }

    private func resourceBinding(for id: String) -> Binding<ModelResourceSettings> {
        Binding(
            get: {
                settings?.models.resource(id: id) ?? ModelResourceSettings(id: id, provider: "openai")
            },
            set: { newValue in
                guard var s = settings,
                      let index = s.models.resources.firstIndex(where: { $0.id == id }) else { return }
                s.models.resources[index] = newValue
                settings = s
            }
        )
    }

    private func resourceKeyBinding(for id: String) -> Binding<String> {
        Binding(
            get: { resourceAPIKeys[id] ?? "" },
            set: { resourceAPIKeys[id] = $0 }
        )
    }

    private func binding(_ keyPath: WritableKeyPath<AppSettings, String>) -> Binding<String> {
        Binding(
            get: { settings?[keyPath: keyPath] ?? "" },
            set: { settings?[keyPath: keyPath] = $0 }
        )
    }

    private func resourceDisplayName(_ resource: ModelResourceSettings) -> String {
        ModelProviderKind.from(provider: resource.provider, baseURL: resource.base_url).label
            + " (\(resource.id))"
    }

    private func resourceNeedsKey(_ resource: ModelResourceSettings) -> Bool {
        ModelProviderKind.from(provider: resource.provider, baseURL: resource.base_url).needsAPIKey
    }

    private func keyConfigured(for id: String) -> Bool {
        resourceKeyConfigured.contains(id)
    }

    @ViewBuilder
    private func resourceStatusBadge(for resourceId: String) -> some View {
        if loadingResourceStatuses, resourceStatuses[resourceId] == nil {
            Text("检测中…")
                .font(.caption2)
                .foregroundStyle(.secondary)
        } else if let status = resourceStatuses[resourceId] {
            Text(status.ready ? "可用" : "未就绪")
                .font(.caption2)
                .foregroundStyle(status.ready ? Color.green : Color.orange)
                .help(status.message ?? "")
        }
    }

    private func availableResources(for route: ProfileRouteSettings) -> [ModelResourceSettings] {
        guard let settings else { return [] }
        let used = Set(route.priority)
        return settings.models.resources.filter { resource in
            !used.contains(resource.id) && resourceStatuses[resource.id]?.ready == true
        }
    }

    private func appendPriority(route: Binding<ProfileRouteSettings>, resourceId: String) {
        var next = route.wrappedValue
        guard !next.priority.contains(resourceId) else { return }
        next.priority.append(resourceId)
        route.wrappedValue = next
        Task { await save() }
    }

    private func removePriority(route: Binding<ProfileRouteSettings>, at index: Int) {
        var next = route.wrappedValue
        guard next.priority.indices.contains(index) else { return }
        next.priority.remove(at: index)
        route.wrappedValue = next
        Task { await save() }
    }

    private func movePriority(
        in route: Binding<ProfileRouteSettings>,
        from index: Int,
        direction: Int
    ) {
        var next = route.wrappedValue
        let target = index + direction
        guard next.priority.indices.contains(index), next.priority.indices.contains(target) else { return }
        next.priority.swapAt(index, target)
        route.wrappedValue = next
        Task { await save() }
    }

    private func syncKeyState(from models: ModelsSettings) {
        resourceKeyConfigured = []
        for resource in models.resources where resource.api_key == "***" {
            resourceKeyConfigured.insert(resource.id)
        }
    }

    private func load() async {
        guard await sidecar.waitUntilReady() else { return }
        do {
            let loaded = try await core.fetchSettings()
            settings = loaded
            syncKeyState(from: loaded.models)
            tavilyKeyConfigured = loaded.tavily_api_key == "***"
            tavilyAPIKey = ""
            resourceAPIKeys = [:]
            await refreshResourceStatuses()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func refreshResourceStatuses() async {
        loadingResourceStatuses = true
        defer { loadingResourceStatuses = false }
        guard await sidecar.waitUntilReady() else { return }
        if let statuses = try? await core.fetchAllResourceStatus() {
            resourceStatuses = Dictionary(uniqueKeysWithValues: statuses.map { ($0.resource_id, $0) })
        }
    }

    private func applyResourceKeys(to settings: inout AppSettings) {
        for index in settings.models.resources.indices {
            let id = settings.models.resources[index].id
            if let typed = resourceAPIKeys[id], !typed.isEmpty {
                settings.models.resources[index].api_key = typed
                resourceKeyConfigured.insert(id)
            } else if resourceKeyConfigured.contains(id) {
                settings.models.resources[index].api_key = "***"
            } else {
                settings.models.resources[index].api_key = nil
            }
        }
    }

    private func save() async {
        guard var settings, !saving else { return }
        saving = true
        defer { saving = false }

        applyResourceKeys(to: &settings)

        var tavilyToSend: String? = nil
        if !tavilyAPIKey.isEmpty {
            tavilyToSend = tavilyAPIKey
            tavilyKeyConfigured = true
        } else if tavilyKeyConfigured {
            tavilyToSend = "***"
        }

        do {
            let updated = try await core.updateSettings(
                targetLanguage: settings.target_language,
                webSearchProvider: settings.web_search_provider,
                tavilyAPIKey: tavilyToSend,
                models: settings.models
            )
            self.settings = updated
            syncKeyState(from: updated.models)
            tavilyAPIKey = ""
            resourceAPIKeys = [:]
            tavilyKeyConfigured = updated.tavily_api_key == "***"
            await refreshResourceStatuses()
        } catch {
            self.error = error.localizedDescription
        }
    }
}

// MARK: - Resource editor

private struct ResourceEditorSheet: View {
    @Binding var resource: ModelResourceSettings
    @Binding var apiKey: String
    let keyConfigured: Bool
    let core: CoreClient
    let onSave: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var resourceStatus: ResourceStatus?
    @State private var refreshingStatus = false
    @State private var pullingModel = false
    @State private var probeFeedback: String?

    private var kind: ModelProviderKind {
        ModelProviderKind.from(provider: resource.provider, baseURL: resource.base_url)
    }

    var body: some View {
        NavigationStack {
            Form {
                Picker("类型", selection: providerKindBinding) {
                    ForEach(ModelProviderKind.allCases) { item in
                        Text(item.label).tag(item)
                    }
                }
                TextField(kind.modelPlaceholder, text: $resource.model)
                if kind.showsBaseURL {
                    TextField("Base URL", text: $resource.base_url)
                }
                if kind.needsAPIKey {
                    SecureField(
                        keyConfigured && apiKey.isEmpty ? "已保存（输入新 Key 可替换）" : "API Key",
                        text: $apiKey
                    )
                }
                Section {
                    Stepper(value: concurrencyBinding, in: kind.concurrencyRange) {
                        Text("并发：\(resource.effectiveConcurrency)")
                    }
                } footer: {
                    Text(kind.concurrencyHint)
                }
                probeControls
            }
            .navigationTitle(resource.id)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") {
                        onSave()
                        dismiss()
                    }
                }
            }
            .task {
                await refreshResourceStatus()
            }
        }
        .frame(minWidth: 420, minHeight: resource.provider == "ollama" ? 520 : 360)
    }

    private var concurrencyBinding: Binding<Int> {
        Binding(
            get: { resource.effectiveConcurrency },
            set: { newValue in
                let upper = kind.concurrencyRange.upperBound
                resource.concurrency = min(upper, Swift.max(1, newValue))
            }
        )
    }

    private var providerKindBinding: Binding<ModelProviderKind> {
        Binding(
            get: { kind },
            set: { newKind in
                resource.provider = newKind.storedProvider
                resource.base_url = newKind.defaultBaseURL
                if resource.model.isEmpty || ModelProviderKind.isPresetModel(resource.model) {
                    resource.model = newKind.defaultModel
                }
                if resource.concurrency == nil || resource.concurrency == 0 {
                    resource.concurrency = newKind.defaultConcurrency
                }
            }
        )
    }

    @ViewBuilder
    private var probeControls: some View {
        Section("连通性") {
            if refreshingStatus, resourceStatus == nil {
                ProgressView("正在检测…")
            } else if let status = resourceStatus {
                LabeledContent("状态", value: status.ready ? "可用" : "未就绪")
                if resource.provider == "ollama" {
                    LabeledContent("服务", value: status.probe_ok ? "已连通" : "未连通")
                    LabeledContent(
                        "探测地址",
                        value: status.base_url?.isEmpty == false ? (status.base_url ?? "") : "http://127.0.0.1:11434"
                    )
                    if let ram = status.ram_gb, !ram.isEmpty, ram != "—" {
                        LabeledContent("内存", value: ram)
                    }
                } else if kind.needsAPIKey {
                    LabeledContent("API Key", value: status.key_configured ? "已配置" : "未配置")
                }
                if !status.displayMessage.isEmpty {
                    Text(status.displayMessage)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                let models = status.installed_models ?? status.available_models ?? []
                if !models.isEmpty {
                    Picker("可用模型", selection: Binding(
                        get: { models.contains(resource.model) ? resource.model : "" },
                        set: { if !$0.isEmpty { resource.model = $0 } }
                    )) {
                        Text("选择…").tag("")
                        ForEach(models, id: \.self) { name in
                            Text(name).tag(name)
                        }
                    }
                }
                if let feedback = probeFeedback, !feedback.isEmpty {
                    Text(feedback).font(.caption).foregroundStyle(.secondary)
                }
                HStack {
                    Button(refreshingStatus ? "测试中…" : "测试连通性") {
                        Task { await testConnectivity() }
                    }
                    .disabled(refreshingStatus || pullingModel)
                    if resource.provider == "ollama" {
                        if !OllamaSetupHelper.isInstalled() {
                            Button("安装 Ollama") { OllamaSetupHelper.openDownloadPage() }
                        }
                        if status.probe_ok, !status.model_ready {
                            Button(pullingModel ? "下载中…" : "下载模型") {
                                OllamaSetupHelper.pullRecommendedModel(model: resource.model)
                                pullingModel = true
                            }
                        }
                    }
                }
            }
        }
    }

    private func refreshResourceStatus() async {
        refreshingStatus = true
        defer { refreshingStatus = false }
        if let status = try? await core.fetchResourceStatus(resourceId: resource.id) {
            resourceStatus = status
            if status.ready { pullingModel = false }
        }
    }

    private func testConnectivity() async {
        probeFeedback = nil
        await refreshResourceStatus()
        guard let status = resourceStatus else {
            probeFeedback = "无法获取状态"
            return
        }
        if status.ready {
            probeFeedback = "已连通，资源可用"
        } else if status.probe_ok, resource.provider == "ollama", !status.model_ready {
            probeFeedback = status.displayMessage.isEmpty ? "已连通，模型未下载" : status.displayMessage
        } else {
            probeFeedback = status.displayMessage
        }
    }
}

private struct AddResourceSheet: View {
    let onAdd: (ModelResourceSettings) -> Void
    let onCancel: () -> Void
    @State private var id = ""
    @State private var kind: ModelProviderKind = .custom
    @State private var model = ""
    @State private var baseURL = ""

    var body: some View {
        NavigationStack {
            Form {
                TextField("资源 ID（小写）", text: $id)
                Picker("类型", selection: $kind) {
                    ForEach(ModelProviderKind.allCases) { item in
                        Text(item.label).tag(item)
                    }
                }
                TextField(kind.modelPlaceholder, text: $model)
                if kind.showsBaseURL || kind == .custom {
                    TextField("Base URL", text: $baseURL)
                }
            }
            .navigationTitle("添加资源")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消", action: onCancel)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("添加") {
                        let rid = id.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
                        guard !rid.isEmpty else { return }
                        onAdd(
                            ModelResourceSettings(
                                id: rid,
                                provider: kind.storedProvider,
                                base_url: baseURL.isEmpty ? kind.defaultBaseURL : baseURL,
                                model: model.isEmpty ? kind.defaultModel : model,
                                concurrency: kind.defaultConcurrency
                            )
                        )
                    }
                    .disabled(id.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
        .frame(minWidth: 380, minHeight: 260)
    }
}

// MARK: - Models

struct AppSettings: Codable {
    var target_language: String
    var web_search_provider: String
    var tavily_api_key: String?
    var models: ModelsSettings

    init(
        target_language: String,
        web_search_provider: String = "ddgs",
        tavily_api_key: String? = nil,
        models: ModelsSettings = .defaults
    ) {
        self.target_language = target_language
        self.web_search_provider = web_search_provider
        self.tavily_api_key = tavily_api_key
        self.models = models
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        target_language = try c.decode(String.self, forKey: .target_language)
        web_search_provider = try c.decodeIfPresent(String.self, forKey: .web_search_provider) ?? "ddgs"
        tavily_api_key = try c.decodeIfPresent(String.self, forKey: .tavily_api_key)
        models = try c.decodeIfPresent(ModelsSettings.self, forKey: .models) ?? .defaults
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(target_language, forKey: .target_language)
        try c.encode(web_search_provider, forKey: .web_search_provider)
        try c.encodeIfPresent(tavily_api_key, forKey: .tavily_api_key)
        try c.encode(models, forKey: .models)
    }

    enum CodingKeys: String, CodingKey {
        case target_language, web_search_provider, tavily_api_key, models
    }
}

struct ModelsSettings: Codable {
    var resources: [ModelResourceSettings]
    var chat: ProfileRouteSettings
    var summarize: ProfileRouteSettings
    var translate: ProfileRouteSettings?

    static var defaults: ModelsSettings {
        ModelsSettings(
            resources: [
                ModelResourceSettings(id: "ollama", provider: "ollama", base_url: "http://127.0.0.1:11434", model: "qwen3.5:4b", concurrency: 2),
                ModelResourceSettings(id: "openai", provider: "openai", base_url: "https://api.openai.com/v1", model: "gpt-4o-mini", concurrency: 4),
                ModelResourceSettings(id: "openrouter", provider: "openrouter", base_url: "https://openrouter.ai/api/v1", model: "anthropic/claude-sonnet-4", concurrency: 4),
                ModelResourceSettings(id: "cursor", provider: "cursor", model: "composer-2.5", concurrency: 8),
            ],
            chat: ProfileRouteSettings(priority: ["openai", "ollama"]),
            summarize: ProfileRouteSettings(priority: ["ollama", "openrouter"])
        )
    }

    func resource(id: String) -> ModelResourceSettings? {
        resources.first { $0.id == id }
    }

    var summarizeUsesOllama: Bool {
        summarize.priority.contains { rid in
            resource(id: rid)?.provider == "ollama"
        }
    }

    var summarizeUsesCloud: Bool {
        guard let first = summarize.priority.first else { return false }
        return resource(id: first)?.provider != "ollama"
    }
}

struct ModelResourceSettings: Codable, Identifiable, Equatable {
    var id: String
    var provider: String
    var base_url: String
    var model: String
    var api_key: String?
    var chat_timeout: Double?
    var concurrency: Int?

    init(
        id: String,
        provider: String,
        base_url: String = "",
        model: String = "",
        api_key: String? = nil,
        chat_timeout: Double? = 12,
        concurrency: Int? = nil
    ) {
        self.id = id
        self.provider = provider
        self.base_url = base_url
        self.model = model
        self.api_key = api_key
        self.chat_timeout = chat_timeout
        self.concurrency = concurrency
    }

    var effectiveConcurrency: Int {
        if let concurrency, concurrency > 0 {
            return concurrency
        }
        return ModelProviderKind.from(provider: provider, baseURL: base_url).defaultConcurrency
    }
}

struct ProfileRouteSettings: Codable, Equatable {
    var priority: [String]

    init(priority: [String] = []) {
        self.priority = priority
    }
}

enum ModelProviderKind: String, CaseIterable, Identifiable {
    case ollama
    case openai
    case openrouter
    case cursor
    case aiping
    case custom

    var id: String { rawValue }

    var label: String {
        switch self {
        case .ollama: return "Ollama"
        case .openai: return "OpenAI"
        case .openrouter: return "OpenRouter"
        case .cursor: return "Cursor"
        case .aiping: return "AiPing"
        case .custom: return "自定义"
        }
    }

    var storedProvider: String {
        switch self {
        case .ollama: return "ollama"
        case .openai: return "openai"
        case .openrouter: return "openrouter"
        case .cursor: return "cursor"
        case .aiping: return "aiping"
        case .custom: return "openai"
        }
    }

    var defaultBaseURL: String {
        switch self {
        case .ollama: return "http://127.0.0.1:11434"
        case .openai: return "https://api.openai.com/v1"
        case .openrouter: return "https://openrouter.ai/api/v1"
        case .cursor: return ""
        case .aiping: return "https://aiping.cn/api/v1"
        case .custom: return ""
        }
    }

    var defaultModel: String {
        switch self {
        case .ollama: return "qwen3.5:4b"
        case .openai: return "gpt-4o-mini"
        case .openrouter: return "anthropic/claude-sonnet-4"
        case .cursor: return "composer-2.5"
        case .aiping: return "GLM-5.2"
        case .custom: return ""
        }
    }

    var modelPlaceholder: String {
        switch self {
        case .ollama: return "模型（如 qwen3.5:4b）"
        case .openai: return "模型（如 gpt-4o-mini）"
        case .openrouter: return "模型（如 anthropic/claude-sonnet-4）"
        case .cursor: return "模型（如 composer-2.5）"
        case .aiping: return "模型（如 GLM-5.2）"
        case .custom: return "模型名"
        }
    }

    var showsBaseURL: Bool {
        self == .ollama || self == .custom
    }

    var needsAPIKey: Bool {
        self != .ollama
    }

    var defaultConcurrency: Int {
        switch self {
        case .ollama: return 2
        case .cursor: return 8
        default: return 4
        }
    }

    var concurrencyRange: ClosedRange<Int> {
        switch self {
        case .ollama: return 1...4
        case .cursor: return 1...8
        default: return 1...8
        }
    }

    var concurrencyHint: String {
        switch self {
        case .ollama:
            return "并发建议 ≤ 本机 Ollama 的 OLLAMA_NUM_PARALLEL。内存吃紧时调回 1。"
        case .cursor:
            return "Cursor Agent 并发；fallback 到 Cursor 时可跑满。"
        default:
            return "OpenAI、OpenRouter 等 OpenAI 兼容 API 的并发上限。"
        }
    }

    static func from(provider: String, baseURL: String) -> ModelProviderKind {
        if provider == "ollama" { return .ollama }
        if provider == "cursor" { return .cursor }
        if provider == "aiping" { return .aiping }
        let url = baseURL.lowercased()
        if url.contains("aiping.cn") { return .aiping }
        if url.contains("openrouter.ai") { return .openrouter }
        if url.contains("api.openai.com") { return .openai }
        if provider == "openrouter" { return .openrouter }
        if provider == "openai" {
            if !url.isEmpty && !url.contains("api.openai.com") { return .custom }
            return .openai
        }
        return .custom
    }

    static func isPresetModel(_ model: String) -> Bool {
        ["qwen3.5:0.8b", "qwen3.5:2b", "qwen3.5:4b", "qwen3.5:9b",
         "gpt-4o-mini", "anthropic/claude-sonnet-4", "composer-2.5", "GLM-5.2"].contains(model)
    }
}

struct OllamaModelTier: Codable, Identifiable, Hashable {
    let model: String
    let size_hint: String
    let label: String

    var id: String { model }
}

struct OllamaStatus: Codable {
    let skipped: Bool
    let resource_id: String?
    let installed: Bool
    let served: Bool
    let model: String
    let model_ready: Bool
    let ram_gb: String
    let message: String?
    let base_url: String
    let probe_ok: Bool
    let probe_detail: String?
    let selected_model: String?
    let recommended_tiers: [OllamaModelTier]
    let installed_models: [String]

    var ready: Bool { !skipped && probe_ok && model_ready }

    var selectedModel: String {
        let selected = selected_model?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return selected.isEmpty ? model : selected
    }

    enum CodingKeys: String, CodingKey {
        case skipped, resource_id, installed, served, model, model_ready, ram_gb, message, base_url
        case probe_ok, probe_detail, selected_model, recommended_tiers, installed_models
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        skipped = try c.decodeIfPresent(Bool.self, forKey: .skipped) ?? false
        resource_id = try c.decodeIfPresent(String.self, forKey: .resource_id)
        installed = try c.decodeIfPresent(Bool.self, forKey: .installed) ?? false
        served = try c.decodeIfPresent(Bool.self, forKey: .served) ?? false
        model = try c.decodeIfPresent(String.self, forKey: .model) ?? ""
        model_ready = try c.decodeIfPresent(Bool.self, forKey: .model_ready) ?? false
        ram_gb = try c.decodeIfPresent(String.self, forKey: .ram_gb) ?? "—"
        message = try c.decodeIfPresent(String.self, forKey: .message)
        base_url = try c.decodeIfPresent(String.self, forKey: .base_url) ?? "http://127.0.0.1:11434"
        probe_ok = try c.decodeIfPresent(Bool.self, forKey: .probe_ok) ?? served
        probe_detail = try c.decodeIfPresent(String.self, forKey: .probe_detail)
        selected_model = try c.decodeIfPresent(String.self, forKey: .selected_model)
        recommended_tiers = try c.decodeIfPresent([OllamaModelTier].self, forKey: .recommended_tiers) ?? []
        installed_models = try c.decodeIfPresent([String].self, forKey: .installed_models) ?? []
    }
}

enum AppLinks {
    static let githubRepository = URL(string: "https://github.com/hezhenghui7338/Lumina")!
    static let githubIssues = URL(string: "https://github.com/hezhenghui7338/Lumina/issues")!
}
