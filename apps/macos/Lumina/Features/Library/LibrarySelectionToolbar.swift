import SwiftUI

struct LibrarySelectionToolbar: View {
    let selectedCount: Int
    let startableCount: Int
    let stoppableCount: Int
    let summarizeActionInFlight: Bool
    var onStartSummarize: () -> Void
    var onStopSummarize: () -> Void
    var onDelete: () -> Void
    var onFavorite: () -> Void
    var onUnfavorite: () -> Void
    var onSelectActive: () -> Void
    var onSelectStartable: () -> Void
    var onSelectAll: () -> Void
    var onDone: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            headerRow
            actionRow
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(LuminaTheme.accentMuted.opacity(0.35))
    }

    private var headerRow: some View {
        HStack {
            Text("已选 \(selectedCount) 本")
                .font(.caption)
                .foregroundStyle(LuminaTheme.textSecondary)
            Spacer(minLength: 0)
            Button("完成", action: onDone)
                .font(.caption)
                .buttonStyle(.plain)
        }
    }

    private var actionRow: some View {
        HStack(spacing: 6) {
            summarizeMenu
            deleteButton
            favoriteMenu
            selectMenu
        }
    }

    private var summarizeMenu: some View {
        Menu {
            Button("开始摘要 (\(startableCount))") {
                onStartSummarize()
            }
            .disabled(startableCount == 0 || summarizeActionInFlight)
            Button("停止摘要 (\(stoppableCount))") {
                onStopSummarize()
            }
            .disabled(stoppableCount == 0 || summarizeActionInFlight)
        } label: {
            Text("摘要")
                .frame(maxWidth: .infinity)
        }
        .menuStyle(.borderlessButton)
        .buttonStyle(.bordered)
        .controlSize(.small)
        .font(.caption)
        .frame(maxWidth: .infinity)
        .help("批量开始或停止摘要")
    }

    private var deleteButton: some View {
        Button("删除") {
            onDelete()
        }
        .font(.caption)
        .buttonStyle(.bordered)
        .controlSize(.small)
        .frame(maxWidth: .infinity)
        .disabled(selectedCount == 0)
        .help("删除已选 \(selectedCount) 本书")
    }

    private var favoriteMenu: some View {
        Menu {
            Button("收藏 (\(selectedCount))") {
                onFavorite()
            }
            .disabled(selectedCount == 0)
            Button("取消收藏 (\(selectedCount))") {
                onUnfavorite()
            }
            .disabled(selectedCount == 0)
        } label: {
            Text("收藏")
                .frame(maxWidth: .infinity)
        }
        .menuStyle(.borderlessButton)
        .buttonStyle(.bordered)
        .controlSize(.small)
        .font(.caption)
        .frame(maxWidth: .infinity)
        .disabled(selectedCount == 0)
        .help("批量收藏或取消收藏")
    }

    private var selectMenu: some View {
        Menu {
            Button("选中进行中/排队") {
                onSelectActive()
            }
            Button("选中待摘要") {
                onSelectStartable()
            }
            Button("全选") {
                onSelectAll()
            }
        } label: {
            Text("选择")
                .frame(maxWidth: .infinity)
        }
        .menuStyle(.borderlessButton)
        .buttonStyle(.bordered)
        .controlSize(.small)
        .font(.caption)
        .frame(maxWidth: .infinity)
        .help("快捷选中：进行中、待摘要或全部")
    }
}
