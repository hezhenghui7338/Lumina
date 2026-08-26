import SwiftUI

/// Split row: the title button runs the default (normal) action; only the
/// adjacent chevron Menu reveals advanced options. Never nest this inside
/// another Menu — NSMenu submenus open on hover.
struct SummarizeChevronSplit<MenuContent: View>: View {
    let title: String
    var isEnabled: Bool = true
    var primary: () -> Void
    @ViewBuilder var advancedMenu: () -> MenuContent

    var body: some View {
        HStack(spacing: 0) {
            Button(title, action: primary)
                .buttonStyle(.plain)
                .padding(.horizontal, 8)
                .padding(.vertical, 6)
                .contentShape(Rectangle())
                .disabled(!isEnabled)
            Menu(content: advancedMenu) {
                Image(systemName: "chevron.down")
                    .imageScale(.small)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 6)
                    .contentShape(Rectangle())
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .disabled(!isEnabled)
            .help("点箭头才展开高级摘要；悬停文字不会弹出")
            .accessibilityLabel("高级摘要")
        }
        .fixedSize()
    }
}
