import SwiftUI

struct ExportSheet: View {
    @Binding var isPresented: Bool
    @Binding var includeNotes: Bool
    let onExport: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("导出 Markdown 摘要版")
                .font(.headline)
            Toggle("包含我的笔记", isOn: $includeNotes)
            Text("默认含译文段落。")
                .font(.caption)
                .foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button("取消") { isPresented = false }
                Button("导出") {
                    onExport()
                    isPresented = false
                }
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 320)
    }
}
