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
    @StateObject private var tour = OnboardingTourController()
    @State private var tab: AppTab = .library
    @State private var selectedBookId: String?
    @State private var jumpSegmentIndex: Int?
    @State private var alertError: String?
    @State private var connectionError: String?
    @State private var showSearch = false
    @State private var showUsageGuide = false
    @State private var importConflict: ImportConflictError?
    @State private var pendingImportPaths: [String] = []
    @State private var isImportingBook = false
    @State private var skipRemainingImportDuplicates = false

    var body: some View {
        Group {
            if sidecar.productReady {
                mainTabs
            } else {
                ColdStartGateView(
                    phases: sidecar.coldStartPhases,
                    startedAt: sidecar.coldStartStartedAt
                )
            }
        }
        .background(LuminaTheme.background)
        .environmentObject(tour)
        .overlayPreferenceValue(TourAnchorPreferenceKey.self) { anchors in
            if sidecar.productReady {
                tourOverlay(anchors: anchors)
            }
        }
        .alert("出错了", isPresented: .constant(alertError != nil)) {
            Button("好") { alertError = nil }
        } message: {
            Text(alertError ?? "")
        }
        .alert("无法连接服务", isPresented: .constant(connectionError != nil)) {
            Button("重试") {
                connectionError = nil
                Task { await finishBootstrap() }
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
        .sheet(isPresented: $showUsageGuide) {
            UsageGuideSheet(isPresented: $showUsageGuide)
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
                Button("覆盖", role: .destructive) {
                    applyImportConflictChoice(.overwrite, conflict: conflict)
                }
                Button("跳过") {
                    applyImportConflictChoice(.skip, conflict: conflict)
                }
                if ImportConflictPolicy.showsSkipRemaining(
                    pendingCount: pendingImportPaths.count
                ) {
                    Button("跳过剩下所有") {
                        applyImportConflictChoice(
                            .skipRemainingDuplicates,
                            conflict: conflict
                        )
                    }
                }
            }
            Button("取消剩余导入", role: .cancel) {
                applyImportConflictChoice(.cancelRemaining, conflict: nil)
            }
        } message: {
            if let conflict = importConflict {
                Text(
                    ImportConflictPolicy.dialogMessage(
                        title: conflict.title,
                        remainingCount: pendingImportPaths.count
                    )
                )
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .luminaOpenSearch)) { _ in
            guard sidecar.productReady else { return }
            showSearch = true
        }
        .onReceive(NotificationCenter.default.publisher(for: .luminaOpenUsageGuide)) { _ in
            guard sidecar.productReady, !tour.isActive else { return }
            showUsageGuide = true
        }
        .onReceive(NotificationCenter.default.publisher(for: .luminaImportBook)) { _ in
            guard sidecar.productReady else { return }
            tab = .library
            importBook()
        }
        .onReceive(NotificationCenter.default.publisher(for: .luminaOpenFiles)) { note in
            let paths = (note.userInfo?[AppDelegate.openFilesPathsKey] as? [String]) ?? []
            handleExternalOpen(paths: paths)
        }
        .onChange(of: tour.step) { _, _ in
            applyTourTab()
        }
        .onChange(of: tour.completed) { _, done in
            if done {
                if UsageGuidePresentationPolicy.marksOnboardingComplete(reopenOnly: false) {
                    onboardingDone = true
                }
                if UsageGuidePresentationPolicy.shouldPresentGuideAfterFirstRun {
                    showUsageGuide = true
                }
            }
        }
        .onChange(of: sidecar.productReady) { _, ready in
            if ready {
                AppDelegate.markUIReadyForOpenFiles()
                if !onboardingDone {
                    tour.start()
                }
            }
        }
        .onAppear {
            if sidecar.productReady {
                AppDelegate.markUIReadyForOpenFiles()
                if !onboardingDone {
                    tour.start()
                }
            }
        }
        .task { await finishBootstrap() }
    }

    private var mainTabs: some View {
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
    }

    @ViewBuilder
    private func tourOverlay(anchors: [TourAnchorID: Anchor<CGRect>]) -> some View {
        if tour.isActive {
            GeometryReader { proxy in
                let hole: CGRect? = {
                    guard let id = tour.anchorID, let anchor = anchors[id] else { return nil }
                    return proxy[anchor].insetBy(dx: -6, dy: -6)
                }()
                OnboardingTourOverlay(
                    hole: hole,
                    title: tour.copy.title,
                    bodyText: tour.copy.body,
                    stepIndex: tour.stepIndex,
                    stepCount: tour.stepCount,
                    isFirst: tour.isFirst,
                    primaryTitle: tour.primaryButtonTitle,
                    onBack: { tour.back() },
                    onNext: { tour.advance() },
                    onSkip: { tour.skip() }
                )
            }
            .ignoresSafeArea()
            .animation(.easeInOut(duration: 0.2), value: tour.step)
        }
    }

    private func applyTourTab() {
        guard tour.isActive, let surface = tour.surface else { return }
        switch surface {
        case .library, .reader:
            tab = .library
        case .settings:
            tab = .settings
        }
    }

    private var libraryTab: some View {
        LibraryTabView(
            selectedBookId: $selectedBookId,
            jumpSegmentIndex: $jumpSegmentIndex,
            onImport: importBook,
            onImportPaths: { enqueueImports(paths: $0) },
            onSearch: { showSearch = true },
            onStartSummarize: { tier in
                Task { await startSummarizeAction(summaryTier: tier) }
            },
            onStopSummarize: { Task { await stopSummarizeAction() } }
        )
    }

    private func finishBootstrap() async {
        await sidecar.ensureRunningAndProductReady()
        guard sidecar.isRunning else {
            if sidecar.userStopped { return }
            connectionError = sidecar.launchError ?? "无法连接到 AI 引擎，请重试或退出。"
            return
        }
        guard sidecar.productReady else { return }
        NotificationCenter.default.post(name: .luminaLibraryRefresh, object: nil)
    }

    private func importBook() {
        Task {
            let panel = NSOpenPanel()
            panel.allowedContentTypes = LibraryImportPolicy.supportedExtensions.compactMap {
                UTType(filenameExtension: $0)
            }
            panel.allowsMultipleSelection = true
            guard panel.runModal() == .OK else { return }
            enqueueImports(paths: panel.urls.map(\.path))
        }
    }

    private func handleExternalOpen(paths: [String]) {
        tab = .library
        selectedBookId = nil
        let classified = LibraryImportPolicy.classify(paths: paths)
        if !classified.unsupportedNames.isEmpty {
            alertError = LibraryImportPolicy.unsupportedMessage(
                names: classified.unsupportedNames
            )
        }
        enqueueImports(paths: classified.supportedPaths)
    }

    private func enqueueImports(paths: [String]) {
        guard !paths.isEmpty else { return }
        pendingImportPaths.append(contentsOf: paths)
        importNextBook()
    }

    private func applyImportConflictChoice(
        _ choice: ImportConflictChoice,
        conflict: ImportConflictError?
    ) {
        let decision = ImportConflictPolicy.decision(for: choice)
        importConflict = nil
        if decision.skipRemainingDuplicates {
            skipRemainingImportDuplicates = true
        }
        if !decision.continueQueue {
            skipRemainingImportDuplicates = false
            pendingImportPaths.removeAll()
            return
        }
        if decision.overwriteCurrent, let conflict {
            startImport(
                path: conflict.path,
                overwrite: true,
                replacingBookId: conflict.existingBookId
            )
            return
        }
        importNextBook()
    }

    private func importNextBook() {
        guard !isImportingBook, importConflict == nil else { return }
        guard !pendingImportPaths.isEmpty else {
            skipRemainingImportDuplicates = false
            return
        }
        let path = pendingImportPaths.removeFirst()
        startImport(path: path, overwrite: false)
    }

    private func startImport(
        path: String,
        overwrite: Bool,
        replacingBookId: String? = nil
    ) {
        guard !isImportingBook else { return }
        isImportingBook = true
        Task {
            await importBook(
                path: path,
                overwrite: overwrite,
                replacingBookId: replacingBookId
            )
        }
    }

    private func importBook(
        path: String,
        overwrite: Bool,
        replacingBookId: String?
    ) async {
        do {
            await sidecar.ensureRunning()
            guard sidecar.isRunning else {
                isImportingBook = false
                skipRemainingImportDuplicates = false
                pendingImportPaths.removeAll()
                if !sidecar.userStopped {
                    connectionError = sidecar.launchError ?? "无法连接到 AI 引擎，请重试或退出。"
                }
                return
            }
            let book = try await core.importBook(path: path, overwrite: overwrite)
            NotificationCenter.default.post(
                name: .luminaLibraryRefresh,
                object: nil,
                userInfo: ["afterImport": true]
            )
            if selectedBookId == replacingBookId {
                selectedBookId = book.id
            }
            isImportingBook = false
            importNextBook()
        } catch let conflict as ImportConflictError {
            isImportingBook = false
            if ImportConflictPolicy.shouldPrompt(
                skipRemainingDuplicates: skipRemainingImportDuplicates
            ) {
                importConflict = conflict
            } else {
                importNextBook()
            }
        } catch {
            isImportingBook = false
            skipRemainingImportDuplicates = false
            pendingImportPaths.removeAll()
            if ConnectionError.isConnectionFailure(error) {
                connectionError = "无法连接到 AI 引擎，请重试或退出。"
            } else {
                alertError = error.localizedDescription
            }
        }
    }

    private func startSummarizeAction(summaryTier: SummaryTier = .normal) async {
        do {
            if let id = selectedBookId {
                try await core.startSummarize(
                    bookId: id, summaryTier: summaryTier
                )
            } else {
                try await core.startSummarizeAll(summaryTier: summaryTier)
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

private struct LibraryTabView: View {
    @Binding var selectedBookId: String?
    @Binding var jumpSegmentIndex: Int?
    var onImport: () -> Void
    var onImportPaths: ([String]) -> Void
    var onSearch: () -> Void
    var onStartSummarize: (SummaryTier) -> Void
    var onStopSummarize: () -> Void

    @EnvironmentObject private var core: CoreClient
    @EnvironmentObject private var sidecar: SidecarManager
    @EnvironmentObject private var tour: OnboardingTourController
    @StateObject private var viewModel = LibraryViewModel()
    @ObservedObject private var readingProgress = ReadingProgressStore.shared
    @State private var showingAllNotes = false
    @State private var readerOverlayActive = false

    private let collectionWidth: CGFloat = 200

    /// The reader carries its own floating action bar, so the window toolbar row
    /// only exists on the bookshelf. Toggling it while reading would resize the
    /// content area and slide the text under the reader's chrome animation.
    private var windowToolbarVisible: Bool {
        selectedBookId == nil
    }

    var body: some View {
        Group {
            if selectedBookId == nil {
                NavigationSplitView(columnVisibility: .constant(.doubleColumn)) {
                    LibraryCollectionSidebar(viewModel: viewModel)
                        .navigationSplitViewColumnWidth(
                            min: collectionWidth, ideal: collectionWidth, max: 260
                        )
                        .toolbar(removing: .sidebarToggle)
                } detail: {
                    detailContent
                }
                .navigationSplitViewStyle(.balanced)
            } else {
                NavigationStack {
                    detailContent
                }
            }
        }
        .background {
            WindowToolbarVisibility(visible: windowToolbarVisible)
        }
        .onAppear { viewModel.loadPreferences() }
        .task(id: sidecar.isRunning) {
            guard sidecar.isRunning else { return }
            await viewModel.loadCategories(using: core)
            await refreshBooks()
        }
        .task(id: viewModel.needsSummarizePolling) {
            await pollSummaryProgress()
        }
        .onReceive(NotificationCenter.default.publisher(for: .luminaLibraryRefresh)) { _ in
            Task { await refreshBooks() }
        }
        .onReceive(readingProgress.$positions) { positions in
            viewModel.applyLocalProgress(positions)
        }
        .onChange(of: selectedBookId) { oldId, newId in
            if newId != nil {
                showingAllNotes = false
            }
            if oldId != nil, newId == nil {
                Task { await refreshBooks() }
            }
        }
        .onChange(of: tour.step) { _, _ in
            applyTourNavigation()
        }
        .onChange(of: viewModel.books.map(\.id)) { _, _ in
            syncTourLibrary()
        }
        .onAppear {
            syncTourLibrary()
            applyTourNavigation()
        }
    }

    private func syncTourLibrary() {
        let first = viewModel.books.first(where: \.canOpenInReader)
        tour.syncLibrary(hasOpenableBook: first != nil, firstBookId: first?.id)
    }

    private func applyTourNavigation() {
        guard tour.isActive, let surface = tour.surface else { return }
        switch surface {
        case .library:
            showingAllNotes = false
            selectedBookId = nil
        case .settings:
            break
        case .reader:
            showingAllNotes = false
            if let id = tour.firstOpenableBookId {
                selectedBookId = id
            }
        }
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
                readerOverlayActive: $readerOverlayActive,
                libraryViewModel: viewModel,
                onReturnToBookshelf: returnToBookshelf,
                onImport: onImport
            )
            .id(id)
            .onAppear { jumpSegmentIndex = nil }
        } else {
            BookshelfView(
                viewModel: viewModel,
                selectedBookId: $selectedBookId,
                onImport: onImport,
                onImportPaths: onImportPaths,
                onSearch: onSearch,
                onShowAllNotes: showAllNotes,
                onStartSummarize: onStartSummarize,
                onStopSummarize: onStopSummarize
            )
        }
    }

    private func showAllNotes() {
        selectedBookId = nil
        showingAllNotes = true
    }

    private func returnToBookshelf() {
        showingAllNotes = false
        selectedBookId = nil
    }

    private func refreshBooks(preserveOrder: Bool = false) async {
        guard await sidecar.waitUntilReady() else { return }
        try? await viewModel.refresh(using: core, preserveOrder: preserveOrder)
        syncTourLibrary()
    }

    private func pollSummaryProgress() async {
        while !Task.isCancelled {
            guard viewModel.needsSummarizePolling else { return }
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            guard !Task.isCancelled, viewModel.needsSummarizePolling else { return }
            await refreshBooks(preserveOrder: true)
        }
    }
}

extension Notification.Name {
    static let luminaOpenSearch = Notification.Name("luminaOpenSearch")
    static let luminaOpenUsageGuide = Notification.Name("luminaOpenUsageGuide")
    static let luminaImportBook = Notification.Name("luminaImportBook")
    static let luminaOpenFiles = Notification.Name("luminaOpenFiles")
    static let luminaLibraryRefresh = Notification.Name("luminaLibraryRefresh")
    static let luminaReadingProgressDidChange = Notification.Name("luminaReadingProgressDidChange")
}
