import SwiftUI
import UniformTypeIdentifiers

enum AppTab: String, CaseIterable, Identifiable {
    case library
    case news
    case settings

    var id: String { rawValue }

    var title: String {
        switch self {
        case .library: return "书库"
        case .news: return "资讯"
        case .settings: return "设置"
        }
    }

    var icon: String {
        switch self {
        case .library: return "books.vertical"
        case .news: return "newspaper"
        case .settings: return "gearshape"
        }
    }
}

struct ContentView: View {
    @EnvironmentObject private var core: CoreClient
    @AppStorage("lumina.onboarding.done") private var onboardingDone = false
    @State private var tab: AppTab = .library
    @State private var books: [BookSummary] = []
    @State private var selectedBookId: String?
    @State private var jumpSegmentIndex: Int?
    @State private var importError: String?
    @State private var showSearch = false
    @State private var showOnboarding = false

    var body: some View {
        TabView(selection: $tab) {
            libraryTab
                .tabItem { Label(AppTab.library.title, systemImage: AppTab.library.icon) }
                .tag(AppTab.library)

            NavigationStack {
                NewsView()
            }
            .tabItem { Label(AppTab.news.title, systemImage: AppTab.news.icon) }
            .tag(AppTab.news)

            NavigationStack {
                SettingsView()
            }
            .tabItem { Label(AppTab.settings.title, systemImage: AppTab.settings.icon) }
            .tag(AppTab.settings)
        }
        .background(LuminaTheme.background)
        .alert("导入失败", isPresented: .constant(importError != nil)) {
            Button("好") { importError = nil }
        } message: {
            Text(importError ?? "")
        }
        .sheet(isPresented: $showSearch) {
            SearchView(isPresented: $showSearch) { bookId, segmentIndex in
                tab = .library
                selectedBookId = bookId
                jumpSegmentIndex = segmentIndex
            }
        }
        .sheet(isPresented: $showOnboarding) {
            OnboardingView(isPresented: $showOnboarding)
                .onDisappear { onboardingDone = true }
        }
        .onReceive(NotificationCenter.default.publisher(for: .luminaOpenSearch)) { _ in
            showSearch = true
        }
        .task {
            await refreshBooks()
            if !onboardingDone {
                showOnboarding = true
            }
        }
    }

    private var libraryTab: some View {
        NavigationSplitView {
            List(books, selection: $selectedBookId) { book in
                VStack(alignment: .leading) {
                    Text(book.title).font(.headline)
                    Text(book.status).font(.caption).foregroundStyle(LuminaTheme.textSecondary)
                }
                .tag(book.id as String?)
            }
            .navigationTitle("书库")
            .toolbar {
                ToolbarItemGroup {
                    Button("搜索") { showSearch = true }
                        .keyboardShortcut("k", modifiers: .command)
                    Button("导入") { importBook() }
                }
            }
        } detail: {
            if let id = selectedBookId {
                ReaderView(bookId: id, initialSegmentIndex: jumpSegmentIndex)
                    .onAppear { jumpSegmentIndex = nil }
            } else {
                ContentUnavailableView("选择一本书", systemImage: "book")
            }
        }
    }

    private func refreshBooks() async {
        do {
            books = try await core.listBooks()
        } catch {
            importError = error.localizedDescription
        }
    }

    private func importBook() {
        Task {
            do {
                let panel = NSOpenPanel()
                panel.allowedContentTypes = [
                    .plainText,
                    .pdf,
                    UTType(filenameExtension: "epub")!,
                    UTType(filenameExtension: "mobi")!,
                ]
                panel.allowsMultipleSelection = false
                guard panel.runModal() == .OK, let url = panel.url else { return }
                let book = try await core.importBook(path: url.path)
                await refreshBooks()
                selectedBookId = book.id
            } catch {
                importError = error.localizedDescription
            }
        }
    }
}

extension Notification.Name {
    static let luminaOpenSearch = Notification.Name("luminaOpenSearch")
}
