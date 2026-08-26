import SwiftUI

struct ExportSheet: View {
    @Binding var isPresented: Bool
    @Binding var includeNotes: Bool
    @Binding var mode: MarkdownExportMode
    let summaryReadyCount: Int
    let summaryTotalCount: Int
    let onFetchMarkdown: () async throws -> String
    let onMarkdownReady: (String) -> Void
    let onError: (String) -> Void

    @State private var isExporting = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("导出 Markdown")
                .font(.headline)

            Text("摘要 \(summaryReadyCount)/\(summaryTotalCount)")
                .font(.subheadline)
                .foregroundStyle(summaryReadyCount > 0 ? Color.secondary : Color.orange)

            if summaryReadyCount == 0 {
                Text("尚无可用摘要，请先完成摘要生成")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }

            Picker("导出内容", selection: $mode) {
                Text("完整摘要版").tag(MarkdownExportMode.full)
                Text("仅导出总结").tag(MarkdownExportMode.sentences)
            }
            .pickerStyle(.radioGroup)
            .disabled(isExporting)

            if mode == .full {
                Toggle("包含我的笔记", isOn: $includeNotes)
                    .disabled(isExporting)
                Text("默认含译文段落。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                Text("只含各段三句话，不含要点、注意、追问、译文和笔记。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            if isExporting {
                HStack(spacing: 8) {
                    ProgressView()
                        .controlSize(.small)
                    Text("正在生成…")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            HStack {
                Spacer()
                Button("取消") { isPresented = false }
                    .disabled(isExporting)
                Button("导出") {
                    Task {
                        isExporting = true
                        defer { isExporting = false }
                        do {
                            let markdown = try await onFetchMarkdown()
                            onMarkdownReady(markdown)
                        } catch {
                            onError(error.localizedDescription)
                        }
                    }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(isExporting || summaryReadyCount == 0)
            }
        }
        .padding(20)
        .frame(width: 360)
    }
}
