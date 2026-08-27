import SwiftUI
import AppKit
import AVFoundation

struct SettingsView: View {
    @EnvironmentObject private var core: CoreClient
    @EnvironmentObject private var sidecar: SidecarManager
    @EnvironmentObject private var theme: ThemeManager
    @EnvironmentObject private var tour: OnboardingTourController
    @State private var settings: AppSettings?
    @State private var promptsDefaults: PromptsSettings?
    @State private var error: String?
    @State private var saving = false
    @State private var pendingSave = false
    @State private var autoSaveEnabled = false
    @State private var engineBusy = false
    @State private var tavilyAPIKey = ""
    @State private var tavilyKeyConfigured = false
    @State private var ocrCloudAPIKey = ""
    @State private var ocrCloudKeyConfigured = false
    @State private var ocrStatus: OcrStatus?
    @State private var testingOcr = false
    @State private var resourceAPIKeys: [String: String] = [:]
    @State private var resourceKeyConfigured: Set<String> = []
    @State private var editingResource: ModelResourceSettings?
    @State private var showingAddResource = false
    @State private var resourceStatuses: [String: ResourceStatus] = [:]
    @State private var loadingResourceStatuses = false
    @State private var voiceListTick = 0
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        ScrollViewReader { proxy in
            Form {
                formContent
            }
            .formStyle(.grouped)
            .navigationTitle("设置")
            .onChange(of: tour.step) { _, step in
                if step == .configureAPI {
                    DispatchQueue.main.async {
                        withAnimation {
                            proxy.scrollTo(TourAnchorID.apiResources, anchor: .center)
                        }
                    }
                }
            }
            .onAppear {
                if tour.step == .configureAPI {
                    DispatchQueue.main.async {
                        proxy.scrollTo(TourAnchorID.apiResources, anchor: .center)
                    }
                }
            }
        }
        .task { await load() }
        .onChange(of: sidecar.isRunning) { _, running in
            if running { Task { await load() } }
        }
        .onAppear { reloadSystemVoices() }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { reloadSystemVoices() }
        }
        .onReceive(NotificationCenter.default.publisher(for: AVSpeechSynthesizer.availableVoicesDidChangeNotification)) { _ in
            reloadSystemVoices()
        }
        .refreshable { await refreshResourceStatuses() }
        .onChange(of: settings?.target_language) { _, _ in
            guard autoSaveEnabled else { return }
            Task { await save() }
        }
        .onChange(of: settings?.web_search_provider) { _, _ in
            guard autoSaveEnabled else { return }
            Task { await save() }
        }
        .onChange(of: settings?.web_search_enabled) { _, _ in
            guard autoSaveEnabled else { return }
            Task { await save() }
        }
        .onChange(of: settings?.debug_mode) { _, _ in
            guard autoSaveEnabled else { return }
            Task { await save() }
        }
        .onChange(of: settings?.auto_start_summary) { _, _ in
            guard autoSaveEnabled else { return }
            Task { await save() }
        }
        .onChange(of: settings?.default_segment_tier) { _, _ in
            guard autoSaveEnabled else { return }
            Task { await save() }
        }
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
    private var formContent: some View {
        engineSection
        if let settings {
            loadedSettingsForm(settings: settings)
        } else if let error {
            ContentUnavailableView("无法加载设置", systemImage: "gearshape", description: Text(error))
        } else if sidecar.userStopped {
            ContentUnavailableView(
                "引擎已停止",
                systemImage: "power",
                description: Text("点上方「重启」后即可加载其余设置。")
            )
        } else {
            ProgressView("加载设置…")
        }
    }

    @ViewBuilder
    private func loadedSettingsForm(settings: AppSettings) -> some View {
        readingSection
        listenSection
        webSearchSection(settings: settings)
        ocrSection
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
        promptsSection(settings: settings)
        appearanceSection
        newsSection
        advancedSection(settings: settings)
        aboutSection
    }

    @ViewBuilder
    private var engineSection: some View {
        Section {
            HStack {
                Text("状态")
                Spacer()
                if sidecar.isBootstrapping || engineBusy {
                    ProgressView()
                        .controlSize(.small)
                }
                Text(engineStatusText)
                    .foregroundStyle(.secondary)
            }
            HStack {
                Button("停止") {
                    Task { await stopEngine() }
                }
                .disabled(engineBusy || sidecar.engineStatus == .stopped || sidecar.engineStatus == .starting)
                Button("重启") {
                    Task { await restartEngine() }
                }
                .disabled(engineBusy || sidecar.isBootstrapping)
            }
        } header: {
            Text("Lumina 引擎")
        } footer: {
            Text("退出应用会关闭后台引擎。摘要与导入队列会保存，下次打开后继续。")
        }
    }

    private var engineStatusText: String {
        if let err = sidecar.launchError, sidecar.engineStatus == .failed {
            return err
        }
        return sidecar.engineStatusLabel
    }

    @ViewBuilder
    private var readingSection: some View {
        Section {
            Picker("目标语言", selection: binding(\.target_language)) {
                Text("简体中文").tag("zh-CN")
                Text("English").tag("en-US")
                Text("日本語").tag("ja-JP")
            }
            Toggle("自动开始摘要", isOn: boolBinding(\.auto_start_summary))
            Picker("导入默认分段", selection: binding(\.default_segment_tier)) {
                Text("正常分段").tag("normal")
                Text("高级分段").tag("advanced")
            }
        } header: {
            Text("阅读")
        } footer: {
            Text("开启后，导入完成、打开书籍及重启时自动排队段摘要。导入默认分段为正常；高级会额外调用模型校准超长块。")
        }
    }

    @ViewBuilder
    private var listenSection: some View {
        Section {
            Picker("默认倍速", selection: ttsSpeedBinding) {
                ForEach(ListenPreferences.rates, id: \.self) { value in
                    Text(listenRateLabel(value)).tag(value)
                }
            }
            Picker("系统音色", selection: systemVoiceBinding) {
                Text("自动（高级/增强优先）").tag("")
                ForEach(systemVoiceOptions, id: \.identifier) { voice in
                    Text("\(voice.name) · \(voice.language) · \(SystemNeuralEngine.qualityLabel(for: voice))")
                        .tag(voice.identifier)
                }
            }
            Button(Self.usesVoiceOverVoiceDownloads ? "打开旁白语音设置" : "打开系统语音包") {
                openSystemVoicePackSettings()
            }
        } header: {
            Text("听书")
        } footer: {
            Text(listenVoiceFooter)
        }
    }

    private static var usesVoiceOverVoiceDownloads: Bool {
        ProcessInfo.processInfo.operatingSystemVersion.majorVersion >= 15
    }

    private var listenVoiceFooter: String {
        let qualityNote = SystemNeuralEngine.hasDownloadedHighQualityVoice()
            ? "已检测到高质量系统语音，完全离线，不产生朗读费用。"
            : "未下载高质量语音包时听感接近机械音。"
        let steps: String
        if Self.usesVoiceOverVoiceDownloads {
            steps = """
            下载由系统完成，Lumina 不代下音库。macOS 15 起请用旁白实用工具（不必打开旁白朗读）：
            1. 点上面的按钮打开「旁白实用工具」
            2. 左侧选「语音」
            3. 点 + 添加
            4. 选中文或英文，下载带 Premium / 增强 的音色
            5. 回到 Lumina，音色列表会刷新
            """
        } else {
            steps = """
            下载由系统完成，Lumina 不代下音库：
            1. 点上面的按钮打开「朗读内容」
            2. 系统声音 → 管理声音
            3. 下载中文 Premium / 优化版或英文 Premium
            4. 回到 Lumina，音色列表会刷新
            """
        }
        return "\(qualityNote)\n\(steps)"
    }

    private var systemVoiceOptions: [AVSpeechSynthesisVoice] {
        _ = voiceListTick
        return AVSpeechSynthesisVoice.speechVoices()
            .filter { $0.language.lowercased().hasPrefix("zh") || $0.language.lowercased().hasPrefix("en") }
            .sorted { $0.language == $1.language ? $0.name < $1.name : $0.language < $1.language }
    }

    private func reloadSystemVoices() {
        voiceListTick += 1
    }

    private func openSystemVoicePackSettings() {
        if Self.usesVoiceOverVoiceDownloads, let url = Self.voiceOverUtilityURL {
            NSWorkspace.shared.openApplication(at: url, configuration: NSWorkspace.OpenConfiguration()) { _, error in
                if error != nil {
                    DispatchQueue.main.async { Self.openSpokenContentSettings() }
                }
            }
            return
        }
        Self.openSpokenContentSettings()
    }

    private static var voiceOverUtilityURL: URL? {
        if let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.VoiceOverUtility") {
            return url
        }
        let path = "/System/Library/CoreServices/VoiceOver Utility.app"
        return FileManager.default.fileExists(atPath: path) ? URL(fileURLWithPath: path) : nil
    }

    private static func openSpokenContentSettings() {
        let candidates = [
            "x-apple.systempreferences:com.apple.Accessibility-Settings.extension?SpokenContent",
            "x-apple.systempreferences:com.apple.preference.universalaccess?SpokenContent",
        ]
        for raw in candidates {
            if let url = URL(string: raw), NSWorkspace.shared.open(url) {
                return
            }
        }
    }

    private var systemVoiceBinding: Binding<String> {
        Binding(
            get: { ListenPreferences.systemVoiceIdentifier ?? "" },
            set: { newValue in
                ListenPreferences.systemVoiceIdentifier = newValue.isEmpty ? nil : newValue
            }
        )
    }

    private var ttsSpeedBinding: Binding<Float> {
        Binding(
            get: { ListenPreferences.rate },
            set: { newValue in
                ListenPreferences.rate = newValue
                settings?.models.tts.engine = "system"
                settings?.models.tts.speed = Double(newValue)
                Task { await save() }
            }
        )
    }

    private func listenRateLabel(_ value: Float) -> String {
        if abs(value - 1.0) < 0.01 { return "1×" }
        if abs(value - value.rounded()) < 0.01 {
            return "\(Int(value.rounded()))×"
        }
        return String(format: "%g×", value)
    }

    @ViewBuilder
    private func promptsSection(settings: AppSettings) -> some View {
        if promptsDefaults != nil {
            Section {
                NavigationLink("Prompt 模板") {
                    PromptsSettingsView(
                        prompts: promptsBinding,
                        defaultPrompts: promptsDefaults ?? settings.prompts_defaults,
                        onSave: { await savePromptsOnly() }
                    )
                }
            } header: {
                Text("Prompt")
            } footer: {
                Text("自定义段摘要、深聊、翻译等 LLM 提示词。保存后立即生效，不影响已有摘要。")
            }
        }
    }

    private var promptsBinding: Binding<PromptsSettings> {
        Binding(
            get: { settings?.prompts ?? PromptsSettings(segment: "", document: "", chat: "", news_chat: "", translate: "", classify: "") },
            set: { newValue in
                settings?.prompts = newValue
            }
        )
    }

    @ViewBuilder
    private var appearanceSection: some View {
        Section("外观") {
            Picker("主题", selection: $theme.appearance) {
                ForEach(AppearanceMode.allCases) { mode in
                    Text(mode.label).tag(mode)
                }
            }
        }
    }

    @ViewBuilder
    private var newsSection: some View {
        Section {
            NavigationLink("RSS 信源") {
                NewsSourcesSettingsView()
            }
        } header: {
            Text("资讯")
        } footer: {
            Text("默认 BestBlogs 预置源；可添加自定义 RSS 地址。")
        }
    }

    @ViewBuilder
    private func advancedSection(settings: AppSettings) -> some View {
        Section {
            Toggle("调试模式", isOn: boolBinding(\.debug_mode))
            if settings.debug_mode {
                NavigationLink("后台任务") {
                    TaskManagerView()
                }
            }
        } header: {
            Text("高级")
        } footer: {
            Text("开启后可查看与管理 LLM 摘要、深聊、资讯精读等后台任务及 API 资源占用。默认关闭。")
        }
    }

    @ViewBuilder
    private var aboutSection: some View {
        Section("关于") {
            HStack(spacing: 14) {
                Image("LuminaMark")
                    .resizable()
                    .scaledToFit()
                    .frame(width: 48, height: 48)
                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Lumina")
                        .font(.headline)
                    Text("Local AI Reading Companion")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text("版本 \(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "未知")")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                Spacer()
            }
            .padding(.vertical, 4)
            Button("使用指南") {
                NotificationCenter.default.post(name: .luminaOpenUsageGuide, object: nil)
            }
            Link("GitHub 仓库", destination: AppLinks.githubRepository)
                .font(.caption)
            Link("反馈问题", destination: AppLinks.githubIssues)
                .font(.caption)
        }
    }

    @ViewBuilder
    private func webSearchSection(settings: AppSettings) -> some View {
        Section {
            Toggle("启用联网搜索", isOn: boolBinding(\.web_search_enabled))
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
            Text("默认开启。关闭后深聊只依据文档；无网时也会自动退回文档模式。免费默认 ddgs；要更稳的检索结果建议配置 Tavily。")
        }
    }

    @ViewBuilder
    private var ocrSection: some View {
        Section {
            TextField(
                "Base URL（如 https://api.openai.com/v1）",
                text: binding(\.ocr_cloud_base_url)
            )
            TextField("视觉模型（如 gpt-4o-mini）", text: binding(\.ocr_cloud_model))
            SecureField(
                ocrCloudKeyConfigured && ocrCloudAPIKey.isEmpty
                    ? "已保存（输入新 Key 可替换）"
                    : "API Key",
                text: $ocrCloudAPIKey
            )
            if let status = ocrStatus {
                LabeledContent("当前路径", value: status.provider == "cloud" ? "云端 OCR" : "本地 OCR")
                Text(status.displayMessage)
                    .font(.caption)
                    .foregroundStyle(status.ready ? Color.secondary : Color.orange)
            }
            HStack {
                Button("保存 OCR 配置") {
                    Task { await save() }
                }
                Button(testingOcr ? "测试中…" : "保存并测试") {
                    Task { await testOcrConnectivity() }
                }
                .disabled(testingOcr)
            }
        } header: {
            Text("文档识别")
        } footer: {
            Text("Base URL、模型和 Key 均配置后优先使用云端 OCR，扫描页图片会上传至该服务；任一项为空则仅在本机使用 RapidOCR。云端失败不会静默回退。")
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
        .id(TourAnchorID.apiResources)
        .tourAnchor(.apiResources)
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
            set: { newValue in
                guard var s = settings else { return }
                s[keyPath: keyPath] = newValue
                settings = s
            }
        )
    }

    private func boolBinding(_ keyPath: WritableKeyPath<AppSettings, Bool>) -> Binding<Bool> {
        Binding(
            get: { settings?[keyPath: keyPath] ?? false },
            set: { newValue in
                guard var s = settings else { return }
                s[keyPath: keyPath] = newValue
                settings = s
            }
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
            guard !used.contains(resource.id) else { return false }
            let status = resourceStatuses[resource.id]
            if resource.provider == "ollama" {
                return status?.ready == true
            }
            return keyConfigured(for: resource.id) || status?.ready == true
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

    private func stopEngine() async {
        engineBusy = true
        defer { engineBusy = false }
        await sidecar.stop(userInitiated: true)
    }

    private func restartEngine() async {
        engineBusy = true
        defer { engineBusy = false }
        error = nil
        await sidecar.restart()
        if sidecar.isRunning {
            await load()
        }
    }

    private func load() async {
        autoSaveEnabled = false
        if sidecar.userStopped {
            return
        }
        guard await sidecar.waitUntilReady() else { return }
        do {
            let loaded = try await core.fetchSettings()
            settings = loaded
            promptsDefaults = loaded.prompts_defaults
            ListenPreferences.syncFromSettings(loaded.models.tts)
            syncKeyState(from: loaded.models)
            tavilyKeyConfigured = loaded.tavily_api_key == "***"
            tavilyAPIKey = ""
            ocrCloudKeyConfigured = loaded.ocr_cloud_api_key == "***"
            ocrCloudAPIKey = ""
            resourceAPIKeys = [:]
            ocrStatus = try? await core.fetchOcrStatus()
            await refreshResourceStatuses()
            autoSaveEnabled = true
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
        if saving {
            pendingSave = true
            return
        }
        saving = true
        defer {
            saving = false
            if pendingSave {
                pendingSave = false
                Task { await save() }
            }
        }

        guard var snapshot = self.settings else { return }

        applyResourceKeys(to: &snapshot)

        var tavilyToSend: String? = nil
        if !tavilyAPIKey.isEmpty {
            tavilyToSend = tavilyAPIKey
            tavilyKeyConfigured = true
        } else if tavilyKeyConfigured {
            tavilyToSend = "***"
        }
        var ocrKeyToSend: String? = nil
        if !ocrCloudAPIKey.isEmpty {
            ocrKeyToSend = ocrCloudAPIKey
            ocrCloudKeyConfigured = true
        } else if ocrCloudKeyConfigured {
            ocrKeyToSend = "***"
        }

        do {
            let updated = try await core.updateSettings(
                targetLanguage: snapshot.target_language,
                webSearchProvider: snapshot.web_search_provider,
                webSearchEnabled: snapshot.web_search_enabled,
                tavilyAPIKey: tavilyToSend,
                ocrCloudBaseURL: snapshot.ocr_cloud_base_url,
                ocrCloudModel: snapshot.ocr_cloud_model,
                ocrCloudAPIKey: ocrKeyToSend,
                ocrCloudTimeoutSeconds: snapshot.ocr_cloud_timeout_seconds,
                debugMode: snapshot.debug_mode,
                autoStartSummary: snapshot.auto_start_summary,
                defaultSegmentTier: snapshot.default_segment_tier,
                models: snapshot.models,
                prompts: snapshot.prompts
            )
            self.settings = updated
            promptsDefaults = updated.prompts_defaults
            ListenPreferences.syncFromSettings(updated.models.tts)
            syncKeyState(from: updated.models)
            tavilyAPIKey = ""
            ocrCloudAPIKey = ""
            resourceAPIKeys = [:]
            tavilyKeyConfigured = updated.tavily_api_key == "***"
            ocrCloudKeyConfigured = updated.ocr_cloud_api_key == "***"
            ocrStatus = try? await core.fetchOcrStatus()
            await refreshResourceStatuses()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func savePromptsOnly() async {
        guard var snapshot = settings else { return }
        saving = true
        defer { saving = false }
        do {
            let updated = try await core.updateSettings(
                targetLanguage: snapshot.target_language,
                webSearchProvider: snapshot.web_search_provider,
                webSearchEnabled: snapshot.web_search_enabled,
                tavilyAPIKey: tavilyKeyConfigured ? "***" : nil,
                ocrCloudBaseURL: snapshot.ocr_cloud_base_url,
                ocrCloudModel: snapshot.ocr_cloud_model,
                ocrCloudAPIKey: ocrCloudKeyConfigured ? "***" : nil,
                ocrCloudTimeoutSeconds: snapshot.ocr_cloud_timeout_seconds,
                debugMode: snapshot.debug_mode,
                autoStartSummary: snapshot.auto_start_summary,
                defaultSegmentTier: snapshot.default_segment_tier,
                models: snapshot.models,
                prompts: snapshot.prompts
            )
            settings = updated
            promptsDefaults = updated.prompts_defaults
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func testOcrConnectivity() async {
        testingOcr = true
        defer { testingOcr = false }
        await save()
        ocrStatus = try? await core.fetchOcrStatus()
    }
}

// MARK: - Add resource

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
    var web_search_enabled: Bool
    var tavily_api_key: String?
    var ocr_cloud_base_url: String
    var ocr_cloud_model: String
    var ocr_cloud_api_key: String?
    var ocr_cloud_timeout_seconds: Double
    var debug_mode: Bool
    var auto_start_summary: Bool
    var default_segment_tier: String
    var models: ModelsSettings
    var prompts: PromptsSettings
    var prompts_defaults: PromptsSettings

    init(
        target_language: String,
        web_search_provider: String = "ddgs",
        web_search_enabled: Bool = true,
        tavily_api_key: String? = nil,
        ocr_cloud_base_url: String = "",
        ocr_cloud_model: String = "",
        ocr_cloud_api_key: String? = nil,
        ocr_cloud_timeout_seconds: Double = 60,
        debug_mode: Bool = false,
        auto_start_summary: Bool = false,
        default_segment_tier: String = "normal",
        models: ModelsSettings = .defaults,
        prompts: PromptsSettings? = nil,
        prompts_defaults: PromptsSettings? = nil
    ) {
        self.target_language = target_language
        self.web_search_provider = web_search_provider
        self.web_search_enabled = web_search_enabled
        self.tavily_api_key = tavily_api_key
        self.ocr_cloud_base_url = ocr_cloud_base_url
        self.ocr_cloud_model = ocr_cloud_model
        self.ocr_cloud_api_key = ocr_cloud_api_key
        self.ocr_cloud_timeout_seconds = ocr_cloud_timeout_seconds
        self.debug_mode = debug_mode
        self.auto_start_summary = auto_start_summary
        self.default_segment_tier = default_segment_tier
        self.models = models
        let empty = PromptsSettings(
            segment: "",
            document: "",
            chat: "",
            news_chat: "",
            translate: "",
            classify: ""
        )
        self.prompts = prompts ?? empty
        self.prompts_defaults = prompts_defaults ?? empty
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        target_language = try c.decode(String.self, forKey: .target_language)
        web_search_provider = try c.decodeIfPresent(String.self, forKey: .web_search_provider) ?? "ddgs"
        web_search_enabled = try c.decodeIfPresent(Bool.self, forKey: .web_search_enabled) ?? true
        tavily_api_key = try c.decodeIfPresent(String.self, forKey: .tavily_api_key)
        ocr_cloud_base_url = try c.decodeIfPresent(String.self, forKey: .ocr_cloud_base_url) ?? ""
        ocr_cloud_model = try c.decodeIfPresent(String.self, forKey: .ocr_cloud_model) ?? ""
        ocr_cloud_api_key = try c.decodeIfPresent(String.self, forKey: .ocr_cloud_api_key)
        ocr_cloud_timeout_seconds = try c.decodeIfPresent(Double.self, forKey: .ocr_cloud_timeout_seconds) ?? 60
        debug_mode = try c.decodeIfPresent(Bool.self, forKey: .debug_mode) ?? false
        auto_start_summary = try c.decodeIfPresent(Bool.self, forKey: .auto_start_summary) ?? false
        default_segment_tier = try c.decodeIfPresent(String.self, forKey: .default_segment_tier) ?? "normal"
        models = try c.decodeIfPresent(ModelsSettings.self, forKey: .models) ?? .defaults
        let empty = PromptsSettings(
            segment: "",
            document: "",
            chat: "",
            news_chat: "",
            translate: "",
            classify: ""
        )
        prompts = try c.decodeIfPresent(PromptsSettings.self, forKey: .prompts) ?? empty
        prompts_defaults = try c.decodeIfPresent(PromptsSettings.self, forKey: .prompts_defaults) ?? empty
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(target_language, forKey: .target_language)
        try c.encode(web_search_provider, forKey: .web_search_provider)
        try c.encode(web_search_enabled, forKey: .web_search_enabled)
        try c.encodeIfPresent(tavily_api_key, forKey: .tavily_api_key)
        try c.encode(ocr_cloud_base_url, forKey: .ocr_cloud_base_url)
        try c.encode(ocr_cloud_model, forKey: .ocr_cloud_model)
        try c.encodeIfPresent(ocr_cloud_api_key, forKey: .ocr_cloud_api_key)
        try c.encode(ocr_cloud_timeout_seconds, forKey: .ocr_cloud_timeout_seconds)
        try c.encode(debug_mode, forKey: .debug_mode)
        try c.encode(auto_start_summary, forKey: .auto_start_summary)
        try c.encode(default_segment_tier, forKey: .default_segment_tier)
        try c.encode(models, forKey: .models)
        try c.encode(prompts, forKey: .prompts)
    }

    enum CodingKeys: String, CodingKey {
        case target_language, web_search_provider, web_search_enabled, tavily_api_key
        case ocr_cloud_base_url, ocr_cloud_model, ocr_cloud_api_key
        case ocr_cloud_timeout_seconds
        case debug_mode, auto_start_summary, default_segment_tier, models, prompts, prompts_defaults
    }
}

struct ModelsSettings: Codable {
    var resources: [ModelResourceSettings]
    var chat: ProfileRouteSettings
    var summarize: ProfileRouteSettings
    var translate: ProfileRouteSettings?
    var tts: TTSSettings

    static var defaults: ModelsSettings {
        ModelsSettings(
            resources: [
                ModelResourceSettings(id: "ollama", provider: "ollama", base_url: "http://127.0.0.1:11434", model: "qwen3.5:4b", concurrency: 2),
                ModelResourceSettings(id: "openai", provider: "openai", base_url: "https://api.openai.com/v1", model: "gpt-4o-mini", concurrency: 4),
                ModelResourceSettings(id: "openrouter", provider: "openrouter", base_url: "https://openrouter.ai/api/v1", model: "anthropic/claude-sonnet-4", concurrency: 4),
                ModelResourceSettings(id: "cursor", provider: "cursor", model: "composer-2.5", concurrency: 8),
            ],
            chat: ProfileRouteSettings(priority: ["openai", "ollama"]),
            summarize: ProfileRouteSettings(priority: ["ollama", "openrouter"]),
            tts: .default
        )
    }

    init(
        resources: [ModelResourceSettings],
        chat: ProfileRouteSettings,
        summarize: ProfileRouteSettings,
        translate: ProfileRouteSettings? = nil,
        tts: TTSSettings = .default
    ) {
        self.resources = resources
        self.chat = chat
        self.summarize = summarize
        self.translate = translate
        self.tts = tts
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        resources = try c.decodeIfPresent([ModelResourceSettings].self, forKey: .resources) ?? []
        chat = try c.decodeIfPresent(ProfileRouteSettings.self, forKey: .chat) ?? ProfileRouteSettings()
        summarize = try c.decodeIfPresent(ProfileRouteSettings.self, forKey: .summarize) ?? ProfileRouteSettings()
        translate = try c.decodeIfPresent(ProfileRouteSettings.self, forKey: .translate)
        tts = try c.decodeIfPresent(TTSSettings.self, forKey: .tts) ?? .default
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(resources, forKey: .resources)
        try c.encode(chat, forKey: .chat)
        try c.encode(summarize, forKey: .summarize)
        try c.encodeIfPresent(translate, forKey: .translate)
        try c.encode(tts, forKey: .tts)
    }

    enum CodingKeys: String, CodingKey {
        case resources, chat, summarize, translate, tts
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
    var advanced_model: String?
    var api_key: String?
    var chat_timeout: Double?
    var concurrency: Int?
    var chunk_target_chars: Int?

    init(
        id: String,
        provider: String,
        base_url: String = "",
        model: String = "",
        advanced_model: String? = nil,
        api_key: String? = nil,
        chat_timeout: Double? = 12,
        concurrency: Int? = nil,
        chunk_target_chars: Int? = nil
    ) {
        self.id = id
        self.provider = provider
        self.base_url = base_url
        self.model = model
        self.advanced_model = advanced_model
        self.api_key = api_key
        self.chat_timeout = chat_timeout
        self.concurrency = concurrency
        self.chunk_target_chars = chunk_target_chars
    }

    var effectiveConcurrency: Int {
        if let concurrency, concurrency > 0 {
            return concurrency
        }
        return ModelProviderKind.from(provider: provider, baseURL: base_url).defaultConcurrency
    }

    var usesDefaultChunkTarget: Bool {
        (chunk_target_chars ?? 0) <= 0
    }

    var effectiveChunkTarget: Int {
        if let chunk_target_chars, chunk_target_chars > 0 {
            return chunk_target_chars
        }
        return ModelProviderKind.from(provider: provider, baseURL: base_url).defaultChunkTarget
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
        case .openrouter: return "模型（摘要建议 anthropic/claude-sonnet-4；openrouter/free 仅试用）"
        case .cursor: return "模型（如 composer-2.5）"
        case .aiping: return "模型（如 GLM-5.2）"
        case .custom: return "模型名"
        }
    }

    /// Short field prompt for the resource editor. Never used as a Form row label.
    var editorModelPlaceholder: String {
        switch self {
        case .ollama: return "如 qwen3.5:4b"
        case .openai: return "如 gpt-4o-mini"
        case .openrouter: return "如 anthropic/claude-sonnet-4"
        case .cursor: return "如 composer-2.5"
        case .aiping: return "如 GLM-5.2"
        case .custom: return "模型名"
        }
    }

    var editorConnectionFooter: String? {
        switch self {
        case .openrouter:
            return "摘要建议固定模型 anthropic/claude-sonnet-4；openrouter/free 仅试用，structured outputs 支持不稳定。"
        default:
            return nil
        }
    }

    var showsBaseURL: Bool {
        self == .ollama || self == .custom || self == .cursor
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
            return "OpenAI 兼容 API 并发；需配置 Cursor 代理 Base URL。"
        case .openrouter:
            return "OpenRouter 等 OpenAI 兼容 API 的并发上限。摘要建议固定模型；openrouter/free 适合试用，structured outputs 支持不稳定。"
        case .openai, .aiping, .custom:
            return "OpenAI 兼容 API 的并发上限。"
        }
    }

    var defaultChunkTarget: Int {
        switch self {
        case .ollama: return 2500
        case .openrouter: return 3500
        case .openai, .cursor, .aiping, .custom: return 4000
        }
    }

    var chunkTargetRange: ClosedRange<Int> {
        switch self {
        case .ollama: return 200...4000
        default: return 200...8000
        }
    }

    var chunkTargetHint: String {
        "导入时长书按此目标字数分段；仅当该资源为摘要优先级首位时生效，且只影响新导入的书籍。"
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
