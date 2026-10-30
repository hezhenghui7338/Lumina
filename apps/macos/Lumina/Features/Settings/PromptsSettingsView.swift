import SwiftUI

struct PromptsSettingsView: View {
    @Binding var prompts: PromptsSettings
    let defaultPrompts: PromptsSettings
    let onSave: () async -> Void

    @State private var saving = false

    private static let styleKeys = PromptsSettings.segmentStyleKeys

    var body: some View {
        Form {
            promptSection(
                title: "段摘要",
                footer: "必填占位符：{text}、{anchor}；可选：{target_language}、{style_guidance}",
                text: $prompts.segment
            ) {
                prompts.segment = defaultPrompts.segment
            }

            DisclosureGroup("段摘要 · 高级（可选覆盖）") {
                optionalPromptSection(
                    title: "Ollama 覆盖",
                    footer: "留空则使用主模板。必填占位符：{text}；可选：{target_language}、{style_guidance}",
                    text: optionalBinding(\.segment_ollama)
                ) {
                    prompts.segment_ollama = defaultPrompts.segment_ollama
                }
                optionalPromptSection(
                    title: "Cloud 覆盖",
                    footer: "留空则使用主模板。必填占位符：{text}；可选：{target_language}、{style_guidance}",
                    text: optionalBinding(\.segment_cloud)
                ) {
                    prompts.segment_cloud = defaultPrompts.segment_cloud
                }
            }

            DisclosureGroup("按类型摘要风格") {
                Text("按书类 / 古文注入语气与侧重点；改后仅对新生成与手动重试摘要生效。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                ForEach(Self.styleKeys, id: \.self) { key in
                    styleSection(key: key)
                }
                Button("恢复全部风格默认") {
                    prompts.segment_styles = defaultPrompts.segment_styles
                }
                .font(.caption)
            }

            promptSection(
                title: "文档 / 资讯速读",
                footer: "必填占位符：{filename}、{annotated}；可选：{target_language}",
                text: $prompts.document
            ) {
                prompts.document = defaultPrompts.document
            }

            promptSection(
                title: "深聊（书籍）",
                footer: "System 提示，无占位符",
                text: $prompts.chat
            ) {
                prompts.chat = defaultPrompts.chat
            }

            promptSection(
                title: "深聊（资讯）",
                footer: "System 提示，无占位符",
                text: $prompts.news_chat
            ) {
                prompts.news_chat = defaultPrompts.news_chat
            }

            promptSection(
                title: "翻译",
                footer: "必填占位符：{target_language}、{text}",
                text: $prompts.translate
            ) {
                prompts.translate = defaultPrompts.translate
            }

            promptSection(
                title: "图书分类",
                footer: "必填占位符：{categories}、{title}、{author}、{text}",
                text: $prompts.classify
            ) {
                prompts.classify = defaultPrompts.classify
            }

            Section {
                Button("全部恢复默认") {
                    prompts = defaultPrompts
                }
                Button(saving ? "保存中…" : "保存 Prompt") {
                    Task { await savePrompts() }
                }
                .disabled(saving)
            }
        }
        .formStyle(.grouped)
        .navigationTitle("Prompt 模板")
    }

    @ViewBuilder
    private func styleSection(key: String) -> some View {
        Section {
            PromptTextEditor(text: styleBinding(key))
                .frame(minHeight: 80)
            Button("恢复默认") {
                var styles = prompts.segment_styles ?? [:]
                styles[key] = defaultPrompts.segment_styles?[key] ?? ""
                prompts.segment_styles = styles
            }
            .font(.caption)
        } header: {
            Text(key)
        }
    }

    private func styleBinding(_ key: String) -> Binding<String> {
        Binding(
            get: { prompts.segment_styles?[key] ?? defaultPrompts.segment_styles?[key] ?? "" },
            set: { newValue in
                var styles = prompts.segment_styles ?? defaultPrompts.segment_styles ?? [:]
                styles[key] = newValue
                prompts.segment_styles = styles
            }
        )
    }

    @ViewBuilder
    private func promptSection(
        title: String,
        footer: String,
        text: Binding<String>,
        reset: @escaping () -> Void
    ) -> some View {
        Section {
            PromptTextEditor(text: text)
            Button("恢复默认") { reset() }
                .font(.caption)
        } header: {
            Text(title)
        } footer: {
            Text(footer)
        }
    }

    @ViewBuilder
    private func optionalPromptSection(
        title: String,
        footer: String,
        text: Binding<String>,
        reset: @escaping () -> Void
    ) -> some View {
        Section {
            PromptTextEditor(text: text)
            Button("清除覆盖") { reset() }
                .font(.caption)
        } header: {
            Text(title)
        } footer: {
            Text(footer)
        }
    }

    private func optionalBinding(_ keyPath: WritableKeyPath<PromptsSettings, String?>) -> Binding<String> {
        Binding(
            get: { prompts[keyPath: keyPath] ?? "" },
            set: { newValue in
                let trimmed = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
                prompts[keyPath: keyPath] = trimmed.isEmpty ? nil : newValue
            }
        )
    }

    @MainActor
    private func savePrompts() async {
        saving = true
        defer { saving = false }
        await onSave()
    }
}

private struct PromptTextEditor: View {
    @Binding var text: String

    var body: some View {
        TextEditor(text: $text)
            .font(.system(.body, design: .monospaced))
            .frame(minHeight: 140)
    }
}

struct PromptsSettings: Codable, Equatable {
    static let segmentStyleKeys = ["文学", "历史", "科技", "哲学", "经济", "传记", "其他", "古文"]

    var segment: String
    var segment_ollama: String?
    var segment_cloud: String?
    var document: String
    var chat: String
    var news_chat: String
    var translate: String
    var classify: String
    var segment_styles: [String: String]?

    init(
        segment: String,
        segment_ollama: String? = nil,
        segment_cloud: String? = nil,
        document: String,
        chat: String,
        news_chat: String,
        translate: String,
        classify: String,
        segment_styles: [String: String]? = nil
    ) {
        self.segment = segment
        self.segment_ollama = segment_ollama
        self.segment_cloud = segment_cloud
        self.document = document
        self.chat = chat
        self.news_chat = news_chat
        self.translate = translate
        self.classify = classify
        self.segment_styles = segment_styles
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        segment = try c.decode(String.self, forKey: .segment)
        segment_ollama = try c.decodeIfPresent(String.self, forKey: .segment_ollama)
        segment_cloud = try c.decodeIfPresent(String.self, forKey: .segment_cloud)
        document = try c.decode(String.self, forKey: .document)
        chat = try c.decode(String.self, forKey: .chat)
        news_chat = try c.decode(String.self, forKey: .news_chat)
        translate = try c.decode(String.self, forKey: .translate)
        classify = try c.decode(String.self, forKey: .classify)
        segment_styles = try c.decodeIfPresent([String: String].self, forKey: .segment_styles)
    }

    enum CodingKeys: String, CodingKey {
        case segment, segment_ollama, segment_cloud, document, chat, news_chat, translate, classify
        case segment_styles
    }
}
