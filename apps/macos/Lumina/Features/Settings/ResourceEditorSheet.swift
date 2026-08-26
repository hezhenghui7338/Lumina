import AppKit
import SwiftUI

/// Short captions used above resource-editor controls. Placeholders and footers
/// carry examples; these labels must stay short so macOS Form does not steal width.
enum ResourceEditorCopy {
    static let typeLabel = "类型"
    static let normalModelLabel = "正常模型"
    static let advancedModelLabel = "高级模型"
    static let advancedModelPlaceholder = "留空则使用正常模型"
    static let baseURLLabel = "Base URL"
    static let apiKeyLabel = "API Key"
    static let availableModelsLabel = "可用模型"
    static let probeAddressLabel = "探测地址"

    static let formLabels: [String] = [
        typeLabel,
        normalModelLabel,
        advancedModelLabel,
        baseURLLabel,
        apiKeyLabel,
        availableModelsLabel,
        probeAddressLabel,
    ]

    static let labelForbiddenFragments = ["如", "留空", "试用"]
}

struct ResourceEditorSheet: View {
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
    @State private var contextProbe: ContextProbeStatus?
    @State private var probingContext = false

    private var kind: ModelProviderKind {
        ModelProviderKind.from(provider: resource.provider, baseURL: resource.base_url)
    }

    var body: some View {
        NavigationStack {
            Form {
                connectionFields
                Section {
                    Stepper(value: concurrencyBinding, in: kind.concurrencyRange) {
                        Text("并发：\(resource.effectiveConcurrency)")
                    }
                } footer: {
                    Text(kind.concurrencyHint)
                }
                Section {
                    ChunkTargetInput(
                        value: chunkTargetBinding,
                        range: kind.chunkTargetRange,
                        label: chunkTargetLabel
                    )
                } footer: {
                    Text(kind.chunkTargetHint)
                }
                probeControls
                contextProbeControls
            }
            .formStyle(.grouped)
            .navigationTitle(resource.id)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") {
                        NSApp.keyWindow?.makeFirstResponder(nil)
                        onSave()
                        dismiss()
                    }
                }
            }
            .task {
                await refreshResourceStatus()
                await refreshContextProbe()
            }
        }
        .frame(minWidth: 520, minHeight: resource.provider == "ollama" ? 680 : 520)
    }

    @ViewBuilder
    private var connectionFields: some View {
        if let footer = kind.editorConnectionFooter {
            Section {
                connectionFieldStack
            } footer: {
                Text(footer)
            }
        } else {
            Section {
                connectionFieldStack
            }
        }
    }

    @ViewBuilder
    private var connectionFieldStack: some View {
        ResourceFormField(label: ResourceEditorCopy.typeLabel) {
            Picker(ResourceEditorCopy.typeLabel, selection: providerKindBinding) {
                ForEach(ModelProviderKind.allCases) { item in
                    Text(item.label).tag(item)
                }
            }
            .labelsHidden()
            .pickerStyle(.menu)
        }
        ResourceFormField(label: ResourceEditorCopy.normalModelLabel) {
            TextField(
                "",
                text: $resource.model,
                prompt: Text(kind.editorModelPlaceholder)
            )
            .textFieldStyle(.roundedBorder)
        }
        ResourceFormField(label: ResourceEditorCopy.advancedModelLabel) {
            TextField(
                "",
                text: advancedModelBinding,
                prompt: Text(ResourceEditorCopy.advancedModelPlaceholder)
            )
            .textFieldStyle(.roundedBorder)
        }
        if kind.showsBaseURL {
            ResourceFormField(label: ResourceEditorCopy.baseURLLabel) {
                TextField("", text: $resource.base_url, prompt: Text("https://…"))
                    .textFieldStyle(.roundedBorder)
            }
        }
        if kind.needsAPIKey {
            ResourceFormField(label: ResourceEditorCopy.apiKeyLabel) {
                SecureField(
                    "",
                    text: $apiKey,
                    prompt: Text(
                        keyConfigured && apiKey.isEmpty
                            ? "已保存（输入新 Key 可替换）"
                            : "粘贴 API Key"
                    )
                )
                .textFieldStyle(.roundedBorder)
            }
        }
    }

    private var advancedModelBinding: Binding<String> {
        Binding(
            get: { resource.advanced_model ?? "" },
            set: { resource.advanced_model = $0 }
        )
    }

    private var chunkTargetLabel: String {
        if resource.usesDefaultChunkTarget {
            return "分段目标：默认（\(kind.defaultChunkTarget) 字）"
        }
        return "分段目标：\(resource.effectiveChunkTarget) 字"
    }

    private var chunkTargetBinding: Binding<Int> {
        Binding(
            get: { resource.effectiveChunkTarget },
            set: { newValue in
                let clamped = ResegmentTarget.clamp(newValue, range: kind.chunkTargetRange)
                if clamped == kind.defaultChunkTarget {
                    resource.chunk_target_chars = 0
                } else {
                    resource.chunk_target_chars = clamped
                }
            }
        )
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
                ResourceChipWrap(spacing: 8) {
                    ResourceStatusChip(title: status.ready ? "可用" : "未就绪", ok: status.ready)
                    if resource.provider == "ollama" {
                        ResourceStatusChip(title: status.probe_ok ? "已连通" : "未连通", ok: status.probe_ok)
                        if let ram = status.ram_gb, !ram.isEmpty, ram != "—" {
                            ResourceStatusChip(title: ram, ok: true)
                        }
                    } else if kind.needsAPIKey {
                        ResourceStatusChip(
                            title: status.key_configured ? "Key 已配置" : "未配置 Key",
                            ok: status.key_configured
                        )
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)

                if resource.provider == "ollama" {
                    ResourceReadableBlock(
                        title: ResourceEditorCopy.probeAddressLabel,
                        text: status.base_url?.isEmpty == false
                            ? (status.base_url ?? "")
                            : "http://127.0.0.1:11434"
                    )
                }
                if !status.displayMessage.isEmpty {
                    ResourceReadableBlock(text: status.displayMessage)
                }
                let models = status.installed_models ?? status.available_models ?? []
                if !models.isEmpty {
                    ResourceFormField(label: ResourceEditorCopy.availableModelsLabel) {
                        Picker(
                            ResourceEditorCopy.availableModelsLabel,
                            selection: Binding(
                                get: { models.contains(resource.model) ? resource.model : "" },
                                set: { if !$0.isEmpty { resource.model = $0 } }
                            )
                        ) {
                            Text("选择…").tag("")
                            ForEach(models, id: \.self) { name in
                                Text(name).tag(name)
                            }
                        }
                        .labelsHidden()
                        .pickerStyle(.menu)
                    }
                }
                if let feedback = probeFeedback, !feedback.isEmpty {
                    ResourceReadableBlock(text: feedback)
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
                    Spacer(minLength: 0)
                }
            }
        }
    }

    @ViewBuilder
    private var contextProbeControls: some View {
        Section {
            if probingContext {
                ProgressView()
                ResourceReadableBlock(text: contextProbe?.displayMessage ?? "正在测试上下文长度…")
            } else if let probe = contextProbe, probe.status != "idle" {
                ResourceReadableBlock(text: probe.displayMessage)
            }
            HStack {
                Button(probingContext ? "测试中…" : "智能测试上下文") {
                    Task { await startContextProbe() }
                }
                .disabled(probingContext || refreshingStatus)
                if probingContext {
                    Button("取消") {
                        Task { await cancelContextProbe() }
                    }
                }
                Spacer(minLength: 0)
            }
        } header: {
            Text("智能测试上下文")
        } footer: {
            Text("把多段不同主题的文字拼在一起，检查模型会不会只读前面、丢掉最后几段。按仍能理解后面内容的长度取 80%，并封顶 3500 字作为分段目标。云端会消耗少量 token；更换模型后请重测。测试只填充分段目标，需点保存才会写入。")
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

    private func refreshContextProbe() async {
        guard let status = try? await core.fetchContextProbe(resourceId: resource.id) else { return }
        contextProbe = status
        if status.isRunning {
            probingContext = true
            await pollContextProbe()
        }
    }

    private func startContextProbe() async {
        probingContext = true
        probeFeedback = nil
        do {
            let key = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
            contextProbe = try await core.startContextProbe(
                resourceId: resource.id,
                model: resource.model,
                baseURL: resource.base_url,
                apiKey: key.isEmpty ? nil : key
            )
            await pollContextProbe()
        } catch {
            probingContext = false
            contextProbe = nil
            probeFeedback = error.localizedDescription
        }
    }

    private func pollContextProbe() async {
        while !Task.isCancelled {
            do {
                let status = try await core.fetchContextProbe(resourceId: resource.id)
                contextProbe = status
                if status.isRunning {
                    try await Task.sleep(nanoseconds: 500_000_000)
                    continue
                }
                probingContext = false
                applyProbeRecommendation(status)
                return
            } catch {
                if error.isCancellation { return }
                probingContext = false
                probeFeedback = error.localizedDescription
                return
            }
        }
    }

    private func cancelContextProbe() async {
        do {
            try await core.cancelContextProbe(resourceId: resource.id)
            await pollContextProbe()
        } catch {
            probingContext = false
            probeFeedback = error.localizedDescription
        }
    }

    private func applyProbeRecommendation(_ status: ContextProbeStatus) {
        guard status.status == "done", let recommended = status.recommended_chars, recommended > 0 else {
            return
        }
        if recommended == kind.defaultChunkTarget {
            resource.chunk_target_chars = 0
        } else {
            resource.chunk_target_chars = recommended
        }
    }
}

struct ResourceFormField<Content: View>: View {
    let label: String
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
            content
                .labelsHidden()
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 8, trailing: 16))
    }
}

struct ResourceStatusChip: View {
    let title: String
    let ok: Bool

    var body: some View {
        Text(title)
            .font(.caption)
            .foregroundStyle(ok ? Color.secondary : Color.orange)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(
                Capsule(style: .continuous)
                    .fill(ok ? Color.primary.opacity(0.06) : Color.orange.opacity(0.14))
            )
    }
}

struct ResourceReadableBlock: View {
    var title: String?
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if let title, !title.isEmpty {
                Text(title)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Text(text)
                .font(.callout)
                .foregroundStyle(.primary)
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(Color.primary.opacity(0.04))
        )
        .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 8, trailing: 16))
    }
}

/// Wraps status chips onto the next line instead of truncating against the trailing edge.
struct ResourceChipWrap: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        arrange(in: proposal.width ?? .infinity, subviews: subviews).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let origins = arrange(in: bounds.width, subviews: subviews).origins
        for (subview, origin) in zip(subviews, origins) {
            subview.place(
                at: CGPoint(x: bounds.minX + origin.x, y: bounds.minY + origin.y),
                proposal: .unspecified
            )
        }
    }

    private func arrange(in maxWidth: CGFloat, subviews: Subviews) -> (size: CGSize, origins: [CGPoint]) {
        var origins: [CGPoint] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        var usedWidth: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > 0, x + size.width > maxWidth {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            origins.append(CGPoint(x: x, y: y))
            rowHeight = max(rowHeight, size.height)
            x += size.width + spacing
            usedWidth = max(usedWidth, x - spacing)
        }
        return (CGSize(width: usedWidth, height: y + rowHeight), origins)
    }
}
