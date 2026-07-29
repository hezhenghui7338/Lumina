import SwiftUI

/// Shared RSS source manager — used from News tab (sheet) and Settings (navigation).
struct NewsSourcesSettingsView: View {
    @EnvironmentObject private var core: CoreClient
    @Environment(\.dismiss) private var dismiss

    /// When true, show a Done button (sheet mode from News tab).
    var showsDismissButton: Bool = false
    var onChanged: (() -> Void)?

    @State private var sources: [NewsSource] = []
    @State private var newURL = ""
    @State private var newTitle = ""
    @State private var busy = false
    @State private var error: String?
    @State private var showRestoreConfirm = false

    private var presetSources: [NewsSource] {
        sources.filter(\.isPreset)
    }

    private var customSources: [NewsSource] {
        sources.filter { !$0.isPreset }
    }

    var body: some View {
        Form {
            Section {
                TextField("RSS URL", text: $newURL)
                    .textFieldStyle(.roundedBorder)
                TextField("显示名称（可选）", text: $newTitle)
                    .textFieldStyle(.roundedBorder)
                Button(busy ? "添加中…" : "添加信源") {
                    Task { await addSource() }
                }
                .disabled(busy || newURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            } header: {
                Text("添加 RSS 源")
            } footer: {
                Text("支持 RSS / Atom 地址。中文源如量子位可通过自建 RSSHub 订阅，例如 https://你的实例/qbitai")
            }

            if !presetSources.isEmpty {
                Section("预置信源 (\(presetSources.count))") {
                    ForEach(presetSources) { source in
                        sourceRow(source)
                    }
                }
            }

            Section("自定义信源 (\(customSources.count))") {
                if customSources.isEmpty {
                    Text("暂无自定义源。删除预置后可点「恢复默认信源」补回 BestBlogs 源。")
                        .foregroundStyle(LuminaTheme.textSecondary)
                } else {
                    ForEach(customSources) { source in
                        sourceRow(source)
                    }
                }
            }

            Section {
                Button("恢复默认信源") {
                    showRestoreConfirm = true
                }
                .disabled(busy)
            } footer: {
                Text("补回 3 个 BestBlogs 预置源并更新预置名称；不会删除你的自定义源。")
            }

            if let error {
                Section {
                    Text(error)
                        .foregroundStyle(.red)
                        .font(.caption)
                }
            }
        }
        .formStyle(.grouped)
        .navigationTitle("RSS 信源")
        .toolbar {
            if showsDismissButton {
                ToolbarItem(placement: .cancellationAction) {
                    Button("完成") {
                        dismiss()
                        onChanged?()
                    }
                }
            }
        }
        .confirmationDialog(
            "恢复默认信源？",
            isPresented: $showRestoreConfirm,
            titleVisibility: .visible
        ) {
            Button("恢复") {
                Task { await restoreDefaults() }
            }
            Button("取消", role: .cancel) {}
        } message: {
            Text("将补回缺失的预置信源并更新其显示名称，自定义源保持不变。")
        }
        .overlay {
            if sources.isEmpty && !busy && error == nil {
                ProgressView("加载信源…")
            }
        }
        .task {
            await reloadSources()
        }
        .frame(minWidth: 480, minHeight: 420)
    }

    @ViewBuilder
    private func sourceRow(_ source: NewsSource) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(sourceDisplayTitle(source))
                .font(.system(size: 13, weight: .medium))
            Text(source.url)
                .font(.system(size: 11))
                .foregroundStyle(LuminaTheme.textSecondary)
                .lineLimit(2)
        }
        .swipeActions(edge: .trailing, allowsFullSwipe: false) {
            Button(role: .destructive) {
                Task { await deleteSource(source) }
            } label: {
                Label("删除", systemImage: "trash")
            }
            .disabled(busy)
        }
    }

    private func sourceDisplayTitle(_ source: NewsSource) -> String {
        let title = source.title?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return title.isEmpty ? source.url : title
    }

    private func reloadSources() async {
        busy = true
        error = nil
        defer { busy = false }
        do {
            sources = try await core.fetchNewsSources()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func addSource() async {
        let url = newURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !url.isEmpty else { return }
        busy = true
        error = nil
        defer { busy = false }
        do {
            let title = newTitle.trimmingCharacters(in: .whitespacesAndNewlines)
            let added = try await core.addNewsSource(url: url, title: title)
            if !sources.contains(where: { $0.id == added.id }) {
                sources.append(added)
            }
            newURL = ""
            newTitle = ""
            onChanged?()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func deleteSource(_ source: NewsSource) async {
        busy = true
        error = nil
        defer { busy = false }
        do {
            try await core.deleteNewsSource(id: source.id)
            sources.removeAll { $0.id == source.id }
            onChanged?()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func restoreDefaults() async {
        busy = true
        error = nil
        defer { busy = false }
        do {
            sources = try await core.restoreNewsDefaults()
            onChanged?()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
