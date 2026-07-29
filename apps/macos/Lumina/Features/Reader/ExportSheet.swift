import SwiftUI

struct ExportSheet: View {
    @Binding var isPresented: Bool
    @Binding var includeNotes: Bool
    let summaryReadyCount: Int
    let summaryTotalCount: Int
    let onExport: () async throws -> BookExportOutcome
    let onSaved: (URL) -> Void
    let onError: (String) -> Void

    @State private var isExporting = false
    @State private var cancelledHint = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("导出 Markdown 摘要版")
                .font(.headline)

            Text("摘要 \(summaryReadyCount)/\(summaryTotalCount)")
                .font(.subheadline)
                .foregroundStyle(summaryReadyCount > 0 ? Color.secondary : Color.orange)

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

            if cancelledHint {
                Text("已取消保存")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            HStack {
                Spacer()
                Button("取消") { isPresented = false }
                    .disabled(isExporting)
                Button("导出") {
                    Task {
                        isExporting = true
                        cancelledHint = false
                        defer { isExporting = false }
                        do {
                            switch try await onExport() {
                            case .saved(let url):
                                isPresented = false
                                onSaved(url)
                            case .cancelled:
                                cancelledHint = true
                            }
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
