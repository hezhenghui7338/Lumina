import SwiftUI

struct ExportSheet: View {
    @Binding var isPresented: Bool
    @Binding var includeNotes: Bool
    let summaryReadyCount: Int
    let summaryTotalCount: Int
    let onFetchMarkdown: () async throws -> String
    let onMarkdownReady: (String) -> Void
    let onError: (String) -> Void

    @State private var isExporting = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("导出 Markdown 摘要版")
                .font(.headline)

            Text("摘要 \(summaryReadyCount)/\(summaryTotalCount)")
                .font(.subheadline)
                .foregroundStyle(summaryReadyCount > 0 ? Color.secondary : Color.orange)

            if summaryReadyCount == 0 {
                Text("尚无可用摘要，请先完成摘要生成")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }

            Toggle("包含我的笔记", isOn: $includeNotes)
                .disabled(isExporting)

            Text("默认含译文段落。")
                .font(.caption)
                .foregroundStyle(.secondary)

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
                            isPresented = false
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
        .frame(width: 320)
    }
}
