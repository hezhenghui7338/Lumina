import SwiftUI
import UniformTypeIdentifiers
import AppKit

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
    @EnvironmentObject private var sidecar: SidecarManager
    @AppStorage("lumina.onboarding.done") private var onboardingDone = false
    @State private var tab: AppTab = .library
    @State private var selectedBookId: String?
    @State private var jumpSegmentIndex: Int?
    @State private var alertError: String?
    @State private var connectionError: String?
    @State private var showSearch = false
    @State private var showOnboarding = false
    @State private var importConflict: ImportConflictError?

    var body: some View {
        TabView(selection: $tab) {
            libraryTab
                .tabItem { Label(AppTab.library.title, systemImage: AppTab.library.icon) }
                .tag(AppTab.library)

            NewsView()
            .tabItem { Label(AppTab.news.title, systemImage: AppTab.news.icon) }
            .tag(AppTab.news)

            NavigationStack {
                SettingsView()
            }
            .tabItem { Label(AppTab.settings.title, systemImage: AppTab.settings.icon) }
            .tag(AppTab.settings)
        }
        .background(LuminaTheme.background)
        .alert("出错了", isPresented: .constant(alertError != nil)) {
            Button("好") { alertError = nil }
        } message: {
            Text(alertError ?? "")
        }
        .alert("无法连接服务", isPresented: .constant(connectionError != nil)) {
            Button("重试") {
                connectionError = nil
                Task {
                    await sidecar.ensureRunning()
                    await finishBootstrap()
                }
            }
            Button("退出", role: .destructive) {
                NSApplication.shared.terminate(nil)
            }
        } message: {
            Text(connectionError ?? "")
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
        .confirmationDialog(
            "书籍已存在",
            isPresented: Binding(
                get: { importConflict != nil },
                set: { if !$0 { importConflict = nil } }
            ),
            titleVisibility: .visible
        ) {
            if let conflict = importConflict {
                Button("重新导入", role: .destructive) {
                    let path = conflict.path
                    importConflict = nil
                    Task { await importBook(path: path, overwrite: true) }
                }
                Button("打开已有书籍") {
                    tab = .library
                    selectedBookId = conflict.existingBookId
                    importConflict = nil
                }
            }
            Button("取消", role: .cancel) {
                importConflict = nil
            }
        } message: {
            if let conflict = importConflict {
                Text("《\(conflict.title)》已在书库中。重新导入将删除原有摘要、笔记，并重新分段与摘要。是否继续？")
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .luminaOpenSearch)) { _ in
            showSearch = true
        }
        .onReceive(NotificationCenter.default.publisher(for: .luminaImportBook)) { _ in
            tab = .library
            importBook()
        }
        .task { await finishBootstrap() }
    }

    private var libraryTab: some View {
        LibraryTabView(
            selectedBookId: $selectedBookId,
            jumpSegmentIndex: $jumpSegmentIndex,
            onImport: importBook,
            onSearch: { showSearch = true },
            onStartSummarize: { Task { await startSummarizeAction() } },
            onStopSummarize: { Task { await stopSummarizeAction() } },
            emptyDetail: { libraryEmptyDetail }
        )
    }

    private var libraryEmptyDetail: some View {
        ContentUnavailableView {
            Label(
                "选择一本书",
                systemImage: "book"
            )
        } description: {
            Text("从左侧书库选择，或继续导入新书")
        } actions: {
            Button {
                importBook()
            } label: {
                Label("导入书籍", systemImage: "square.and.arrow.down")
            }
            .buttonStyle(.borderedProminent)
            .tint(LuminaTheme.accent)
        }
    }

    private func finishBootstrap() async {
        await sidecar.ensureRunning()
        guard sidecar.isRunning else {
            connectionError = sidecar.launchError ?? "无法连接到 AI 引擎，请重试或退出。"
            return
        }
        NotificationCenter.default.post(name: .luminaLibraryRefresh, object: nil)
        if !onboardingDone {
            showOnboarding = true
        }
    }

    private func importBook() {
        Task {
            let panel = NSOpenPanel()
            panel.allowedContentTypes = [
                .plainText,
                .pdf,
                UTType(filenameExtension: "epub")!,
                UTType(filenameExtension: "mobi")!,
            ]
            panel.allowsMultipleSelection = false
            guard panel.runModal() == .OK, let url = panel.url else { return }
            await importBook(path: url.path, overwrite: false)
        }
    }

    private func importBook(path: String, overwrite: Bool) async {
        do {
            await sidecar.ensureRunning()
            guard sidecar.isRunning else {
                connectionError = sidecar.launchError ?? "无法连接到 AI 引擎，请重试或退出。"
                return
            }
            let book = try await core.importBook(path: path, overwrite: overwrite)
            NotificationCenter.default.post(
                name: .luminaLibraryRefresh,
                object: nil,
                userInfo: ["afterImport": true]
            )
            selectedBookId = book.id
        } catch let conflict as ImportConflictError {
            importConflict = conflict
        } catch {
            if ConnectionError.isConnectionFailure(error) {
                connectionError = "无法连接到 AI 引擎，请重试或退出。"
            } else {
                alertError = error.localizedDescription
            }
        }
    }

    private func startSummarizeAction() async {
        do {
            if let id = selectedBookId {
                try await core.startSummarize(bookId: id)
            } else {
                try await core.startSummarizeAll()
            }
        } catch {
            if ConnectionError.isConnectionFailure(error) {
                connectionError = "无法连接到 AI 引擎，请重试或退出。"
            } else {
                alertError = error.localizedDescription
            }
        }
    }

    private func stopSummarizeAction() async {
        do {
            if let id = selectedBookId {
                try await core.stopSummarize(bookId: id)
            } else {
                try await core.stopSummarizeAll()
            }
        } catch {
            if ConnectionError.isConnectionFailure(error) {
                connectionError = "无法连接到 AI 引擎，请重试或退出。"
            } else {
                alertError = error.localizedDescription
            }
        }
    }
}

// MARK: - Library tab chrome (library sidebar via toolbar toggle)

private struct LibraryTabView<EmptyDetail: View>: View {
    @Binding var selectedBookId: String?
    @Binding var jumpSegmentIndex: Int?
    var onImport: () -> Void
    var onSearch: () -> Void
    var onStartSummarize: () -> Void
    var onStopSummarize: () -> Void
    @ViewBuilder var emptyDetail: () -> EmptyDetail

    @AppStorage("lumina.library.sidebarPinned") private var librarySidebarPinned = false
    @State private var segmentListPeeking = false
    @State private var showingAllNotes = false
    @State private var readerOverlayActive = false
    @State private var readerChromeVisible = false

    private let libraryWidth: CGFloat = 260

    private var librarySidebarVisible: Bool {
        selectedBookId == nil || librarySidebarPinned
    }

    private var windowToolbarVisible: Bool {
        selectedBookId == nil || readerChromeVisible || librarySidebarPinned
    }

    var body: some View {
        Group {
            if librarySidebarVisible {
                NavigationSplitView(columnVisibility: libraryColumnVisibility) {
                    librarySidebarContent
                } detail: {
                    detailContent
                }
                .navigationSplitViewStyle(.balanced)
            } else {
                NavigationStack {
                    detailContent
                }
                .toolbar {
                    ToolbarItem(placement: .automatic) {
                        Button { librarySidebarPinned = true } label: {
                            Label("书库", systemImage: "sidebar.left")
                        }
                        .help("展开书库")
                    }
                }
            }
        }
        .animation(.easeInOut(duration: 0.25), value: librarySidebarPinned)
        .background {
            WindowToolbarVisibility(visible: windowToolbarVisible)
        }
        .onChange(of: selectedBookId) { _, newId in
            if newId != nil {
                showingAllNotes = false
            } else {
                readerChromeVisible = false
            }
        }
    }

    private var libraryColumnVisibility: Binding<NavigationSplitViewVisibility> {
        Binding(
            get: { .doubleColumn },
            set: { newValue in
                guard selectedBookId != nil, newValue == .detailOnly else { return }
                librarySidebarPinned = false
            }
        )
    }

    @ViewBuilder
    private var detailContent: some View {
        if showingAllNotes {
            AllNotesView(
                onSelectNote: { bookId, segmentIndex in
                    showingAllNotes = false
                    selectedBookId = bookId
                    jumpSegmentIndex = segmentIndex
                },
                onDismiss: { showingAllNotes = false }
            )
        } else if let id = selectedBookId {
            ReaderView(
                bookId: id,
                initialSegmentIndex: jumpSegmentIndex,
                segmentListPeeking: $segmentListPeeking,
                readerOverlayActive: $readerOverlayActive,
                readerChromeVisible: $readerChromeVisible
            )
            .id(id)
            .onAppear { jumpSegmentIndex = nil }
        } else {
            emptyDetail()
        }
    }

    private func showAllNotes() {
        selectedBookId = nil
        showingAllNotes = true
    }

    private var librarySidebarContent: some View {
        LibraryView(
            selectedBookId: $selectedBookId,
            onImport: onImport,
            onSearch: onSearch,
            onShowAllNotes: showAllNotes,
            onStartSummarize: onStartSummarize,
            onStopSummarize: onStopSummarize
        )
        .navigationSplitViewColumnWidth(min: libraryWidth, ideal: libraryWidth, max: 340)
    }

}

extension Notification.Name {
    static let luminaOpenSearch = Notification.Name("luminaOpenSearch")
    static let luminaImportBook = Notification.Name("luminaImportBook")
    static let luminaLibraryRefresh = Notification.Name("luminaLibraryRefresh")
}
