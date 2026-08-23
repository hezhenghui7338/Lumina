import SwiftUI

struct LibraryCollectionSidebar: View {
    @ObservedObject var viewModel: LibraryViewModel

    var body: some View {
        List(selection: collectionBinding) {
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

    private var collectionBinding: Binding<LibraryCollection?> {
        Binding(
            get: { viewModel.collection },
            set: { newValue in
                if let newValue {
                    viewModel.setCollection(newValue)
                }
            }
        )
    }

    private func collectionRow(_ item: LibraryCollection) -> some View {
        Label {
            HStack {
                Text(item.label)
                Spacer()
                Text("\(viewModel.count(for: item))")
                    .foregroundStyle(LuminaTheme.textSecondary)
                    .monospacedDigit()
            }
        } icon: {
            Image(systemName: item.systemImage)
        }
        .tag(item)
    }
}
