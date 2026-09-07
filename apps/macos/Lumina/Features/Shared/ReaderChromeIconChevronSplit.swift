import SwiftUI

/// Top-bar icon split: the icon button runs the default action; only the
/// adjacent chevron Menu reveals alternatives. Never wrap the icon in
/// `Menu+primaryAction` — that hides the menu behind a long-press. Never put
/// `buttonStyle` on the Menu — nested NSMenuItems become unselectable.
struct ReaderChromeIconChevronSplit<MenuContent: View>: View {
    let systemImage: String
    var primaryHelp: String
    var chevronHelp: String
    var primaryAccessibilityLabel: String
    var chevronAccessibilityLabel: String
    var accessibilityIdentifier: String
    var primary: () -> Void
    @ViewBuilder var menu: () -> MenuContent

    var body: some View {
        HStack(spacing: 0) {
            Button(action: primary) {
                Image(systemName: systemImage)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 4)
                    .contentShape(Rectangle())
            }
            .readerChromeIconAction()
            .help(primaryHelp)
            .accessibilityLabel(primaryAccessibilityLabel)

            Menu(content: menu) {
                Image(systemName: "chevron.down")
                    .imageScale(.small)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 4)
                    .contentShape(Rectangle())
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .help(chevronHelp)
            .accessibilityLabel(chevronAccessibilityLabel)
        }
        .fixedSize()
        .accessibilityIdentifier(accessibilityIdentifier)
    }
}
