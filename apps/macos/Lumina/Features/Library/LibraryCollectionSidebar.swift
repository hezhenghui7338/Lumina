import SwiftUI

struct LibraryCollectionSidebar: View {
    @ObservedObject var viewModel: LibraryViewModel

    var body: some View {
        List {
            ForEach(LibraryCollectionSection.allCases) { section in
                let items = viewModel.sidebarCollections.filter { $0.section == section }
                if !items.isEmpty {
                    if let label = section.label {
                        Section(label) {
                            ForEach(items) { item in collectionRow(item) }
                        }
                    } else {
                        Section {
                            ForEach(items) { item in collectionRow(item) }
                        }
                    }
                }
            }
        }
        .listStyle(.sidebar)
        .navigationTitle("书架")
    }

    private func collectionRow(_ item: LibraryCollection) -> some View {
        let selected = viewModel.query.isSelected(item)
        return Button {
            viewModel.selectFacet(item)
        } label: {
            Label {
                HStack {
                    Text(item.label)
                    Spacer(minLength: 8)
                    Text("\(viewModel.count(for: item))")
                        .foregroundStyle(LuminaTheme.textSecondary)
                        .monospacedDigit()
                }
            } icon: {
                Image(systemName: item.systemImage)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .listRowBackground(selected ? LuminaTheme.libraryRowSelectionBackground : Color.clear)
        .accessibilityAddTraits(selected ? [.isSelected] : [])
        .accessibilityHint(item == .favorite ? "与摘要、阅读、分类一起筛选" : "与其他筛选条件联合查询")
    }
}
