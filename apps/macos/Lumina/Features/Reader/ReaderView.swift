import SwiftUI
import AppKit
import UniformTypeIdentifiers

private enum ReaderOverlay: Equatable {
    case none, chat, notes
}

private enum ReaderEdgeTarget: Equatable {
    case segments, chat, notes
}

private enum ReaderChromeMode: Equatable {
    case hidden, revealed
}

enum ReaderChatScope: String, CaseIterable, Identifiable {
    case segment
    case book
    var id: String { rawValue }
}

struct ReaderView: View {
    let bookId: String
    var initialSegmentIndex: Int? = nil
    @Binding var segmentListPeeking: Bool
    @Binding var readerOverlayActive: Bool
    @Binding var readerChromeVisible: Bool
    @Binding var librarySidebarPinned: Bool
    var onReturnToBookshelf: () -> Void = {}
    var onImport: () -> Void = {}
    @EnvironmentObject private var core: CoreClient
    @Environment(\.scenePhase) private var scenePhase

    @ObservedObject var libraryViewModel: LibraryViewModel
    @StateObject private var viewModel = ReaderViewModel()
    @AppStorage("lumina.reader.segmentListPinned") private var segmentListPinned = false

    init(
        bookId: String,
        initialSegmentIndex: Int? = nil,
        segmentListPeeking: Binding<Bool> = .constant(false),
        readerOverlayActive: Binding<Bool> = .constant(false),
        readerChromeVisible: Binding<Bool> = .constant(false),
        librarySidebarPinned: Binding<Bool> = .constant(false),
        libraryViewModel: LibraryViewModel,
        onReturnToBookshelf: @escaping () -> Void = {},
        onImport: @escaping () -> Void = {}
    ) {
        self.bookId = bookId
        self.initialSegmentIndex = initialSegmentIndex
        _segmentListPeeking = segmentListPeeking
        _readerOverlayActive = readerOverlayActive
        _readerChromeVisible = readerChromeVisible
        _librarySidebarPinned = librarySidebarPinned
        _libraryViewModel = ObservedObject(wrappedValue: libraryViewModel)
        self.onReturnToBookshelf = onReturnToBookshelf
        self.onImport = onImport
    }
    @State private var expandedSourceSegments: Set<Int> = []
    @State private var expandedSummarySegments: Set<Int> = []
    @State private var contentMode: ReaderContentMode = .summary
    /// The segment pinned to the top of the viewport. Single source of truth for
    /// reading progress: SwiftUI writes it while scrolling, and every jump is
    /// performed by assigning to it. Nothing else may move the scroll view.
    @State private var topSegmentIdx: Int?
    @State private var readerGlobalFrame: CGRect = .null
    @State private var overlay: ReaderOverlay = .none
    @State private var overlayEngaged = false
    @State private var chatInput = ""
    @State private var highlightSegment: Int?
    @State private var showExport = false
    @State private var exportIncludeNotes = false
    @State private var exportDocument = MarkdownExportDocument(text: "")
    @State private var showFileExporter = false
    @State private var exportDefaultFilename = "summary.md"
    @State private var exportFallbackBookTitle = ""
    @State private var shouldPresentFileExporter = false
    @State private var exportFeedback: ExportFeedback?
    @State private var notesRefreshToken = 0
    @State private var noteError: String?
    @State private var actionError: String?
    @State private var showRegenerateConfirm = false
    @State private var regenerateSummaryTier: SummaryTier = .normal
    @State private var showResegmentSheet = false
    @State private var showBoundarySheet = false
    @State private var boundaryLeftIdx = 0
    @State private var resegmentTargetChars = 4000
    @State private var isResegmentSubmitting = false
    @State private var readerSize: CGSize = .zero
    @State private var pendingEdge: ReaderEdgeTarget? = nil
    @State private var dwellTask: Task<Void, Never>? = nil
    @State private var chromeMode: ReaderChromeMode = .revealed
    @State private var summarizeActionInFlight = false
    @FocusState private var chatFocused: Bool
    @FocusState private var readerContentFocused: Bool

    private let segmentsWidth: CGFloat = 240
    private let notesWidth: CGFloat = 220
    private let chatHeight: CGFloat = 300
    private let edgeHotZone: CGFloat = 8
    private let topEdgeExclusionZone: CGFloat = 28
    private let edgeDwellNanoseconds: UInt64 = 250_000_000
    private let segmentSwitchDuration: TimeInterval = 0.05
    private let segmentFeedGap: CGFloat = 0

    private var chromeVisible: Bool { chromeMode != .hidden }

    private var edgeIconsVisible: Bool {
        chromeMode == .revealed
    }

    private var toolbarVisible: Bool {
        viewModel.bookStatus == "processing"
            || chromeMode == .revealed
            || overlay != .none
    }

    private var segmentListVisibility: ReaderSegmentListVisibility {
        ReaderSegmentListVisibility(pinned: segmentListPinned, peeking: segmentListPeeking)
    }

    private var segmentListOverlayVisible: Bool {
        segmentListVisibility.overlayVisible
    }

    private var segmentListInlineVisible: Bool {
        segmentListVisibility.inlineVisible
    }

    private var segmentListAnyVisible: Bool {
        segmentListVisibility.anyVisible
    }

    private var librarySummarizeOverviewActive: Bool {
        guard let overview = libraryViewModel.summarizeOverview else { return false }
        return SummarizeActivityChip.shouldShow(activeCount: overview.activeCount)
    }

    private var shouldShowContentSummaryProgress: Bool {
        ReaderSummaryProgressPolicy.shouldShowContentBanner(
            readyCount: viewModel.summaryReadyCount,
            totalCount: viewModel.summaryTotalCount,
            overviewActive: librarySummarizeOverviewActive,
            segmentListVisible: segmentListAnyVisible
        )
    }

    private var readerKeyboardScrollEnabled: Bool {
        overlay == .none
            && !chatFocused
            && !showBoundarySheet
            && !showExport
            && !showResegmentSheet
            && !showRegenerateConfirm
    }

    private var regenerateConfirmMessage: String {
        let count = viewModel.segments.count
        let tier = regenerateSummaryTier.label
        return "将用「\(tier)」重新生成全书 \(count) 个段的摘要。已有摘要会被全部覆盖，会消耗大量计算和 API 资源，且无法撤销。若只想用该档位补齐未摘要段落，请改用「开始摘要」。"
    }

    private var boundarySheet: some View {
        SegmentBoundarySheet(
            bookId: bookId,
            leftIdx: boundaryLeftIdx,
            core: core,
            onApplied: { result, leftText, rightText in
                viewModel.applyBoundaryMove(
                    result: result,
                    leftText: leftText,
                    rightText: rightText
                )
                showBoundarySheet = false
            },
            onCancel: { showBoundarySheet = false }
        )
    }

    var body: some View {
        readerLayout
            .toolbar {
                if toolbarVisible {
                    readerToolbar
                }
            }
            .toolbar(removing: .sidebarToggle)
            .background { readerModeShortcutButton }
            .confirmationDialog(
                "全书重新摘要",
                isPresented: $showRegenerateConfirm,
                titleVisibility: .visible
            ) {
                Button("确认覆盖全书", role: .destructive) {
                    Task {
                        do {
                            try await viewModel.regenerateAllSummaries(
                                core: core, summaryTier: regenerateSummaryTier
                            )
                        }
                        catch { actionError = error.localizedDescription }
                    }
                }
                Button("取消", role: .cancel) {}
            } message: {
                Text(regenerateConfirmMessage)
            }
            .sheet(isPresented: $showResegmentSheet) {
                ResegmentBookSheet(
                    bookTitle: viewModel.exportBookTitle,
                    targetChars: $resegmentTargetChars,
                    isPresented: $showResegmentSheet,
                    isSubmitting: isResegmentSubmitting,
                    onSubmit: submitResegment
                )
            }
            .sheet(isPresented: $showBoundarySheet) {
                boundarySheet
            }
            .sheet(isPresented: $showExport, onDismiss: presentFileExporterIfNeeded) {
                ExportSheet(
                    isPresented: $showExport,
                    includeNotes: $exportIncludeNotes,
                    summaryReadyCount: viewModel.summaryReadyCount,
                    summaryTotalCount: viewModel.summaryTotalCount,
                    onFetchMarkdown: {
                        try await viewModel.fetchExportMarkdown(
                            core: core,
                            includeNotes: exportIncludeNotes
                        )
                    },
                    onMarkdownReady: { markdown in
                        exportDocument = MarkdownExportDocument(text: markdown)
                        exportDefaultFilename = BookMarkdownExporter.defaultFilename(
                            for: viewModel.exportBookTitle
                        )
                        exportFallbackBookTitle = viewModel.exportBookTitle
                        shouldPresentFileExporter = true
                        showExport = false
                    },
                    onError: { actionError = $0 }
                )
            }
            .fileExporter(
                isPresented: $showFileExporter,
                document: exportDocument,
                contentType: .plainText,
                defaultFilename: exportDefaultFilename
            ) { result in
                handleFileExportCompletion(result)
            }
            .exportFeedbackAlert($exportFeedback)
            .alert("笔记错误", isPresented: noteErrorPresented) {
                Button("好") { noteError = nil }
            } message: {
                Text(noteError ?? "")
            }
            .alert("操作失败", isPresented: actionErrorPresented) {
                Button("好") { actionError = nil }
            } message: {
                Text(actionError ?? "")
            }
    }

    private func presentFileExporterIfNeeded() {
        guard shouldPresentFileExporter else { return }
        shouldPresentFileExporter = false
        showFileExporter = true
    }

    private func prepareResegment() {
        resegmentTargetChars = ResegmentTarget.normalized(
            currentTarget: viewModel.chunkTargetChars,
            totalChars: viewModel.totalCharCount,
            segmentCount: viewModel.segments.count
        )
        showResegmentSheet = true
    }

    private func openBoundaryEditor(at idx: Int? = nil) {
        let resolved = idx ?? viewModel.selectedIdx ?? 0
        let lastIdx = max(0, viewModel.segments.count - 2)
        boundaryLeftIdx = min(max(0, resolved), lastIdx)
        showBoundarySheet = true
    }

    private func submitResegment() {
        guard !isResegmentSubmitting else { return }
        isResegmentSubmitting = true
        Task {
            do {
                try await viewModel.resegmentBook(
                    core: core,
                    chunkTargetChars: resegmentTargetChars
                )
                showResegmentSheet = false
                closeOverlay()
            } catch {
                actionError = error.localizedDescription
            }
            isResegmentSubmitting = false
        }
    }

    @MainActor
    private func handleFileExportCompletion(_ result: Result<URL, Error>) {
        let markdown = exportDocument.text
        let bookTitle = exportFallbackBookTitle
        exportDocument = MarkdownExportDocument(text: "")
        exportFallbackBookTitle = ""

        switch result {
        case .success:
            exportFeedback = BookMarkdownExporter.feedback(from: result)
        case .failure(let error) where BookMarkdownExporter.isUserCancellation(error):
            exportFeedback = .cancelled
        case .failure:
            exportFeedback = BookMarkdownExporter.presentSavePanelFallback(
                markdown: markdown,
                bookTitle: bookTitle
            )
        }
    }

    private var noteErrorPresented: Binding<Bool> {
        Binding(
            get: { noteError != nil },
            set: { if !$0 { noteError = nil } }
        )
    }

    private var actionErrorPresented: Binding<Bool> {
        Binding(
            get: { actionError != nil },
            set: { if !$0 { actionError = nil } }
        )
    }

    private var readerModeShortcutButton: some View {
        Button("切换阅读模式", action: toggleContentMode)
            .keyboardShortcut("o", modifiers: [.command, .shift])
            .opacity(0)
            .frame(width: 0, height: 0)
    }

    @ToolbarContentBuilder
    private var readerToolbar: some ToolbarContent {
        ToolbarItem(placement: .primaryAction) {
            Button(action: onImport) {
                Label("导入", systemImage: "square.and.arrow.down")
            }
            .help("导入书籍")
            .labelStyle(.iconOnly)
            .foregroundStyle(LuminaTheme.accent)
        }

        ToolbarItem(placement: .navigation) {
            Button {
                Task {
                    await viewModel.flushProgressSave()
                    onReturnToBookshelf()
                }
            } label: {
                Label("书架", systemImage: "square.grid.2x2")
            }
            .help("返回书架")
        }

        ToolbarItem(placement: .navigation) {
            Button {
                toggleLibrarySidebar()
            } label: {
                Label("最近", systemImage: "sidebar.left")
                    .symbolVariant(librarySidebarPinned ? .fill : .none)
            }
            .help(librarySidebarPinned ? "收起最近阅读" : "展开最近阅读")
        }

        ToolbarItem(placement: .navigation) {
            Button {
                toggleSegmentList()
            } label: {
                Label("段列表", systemImage: "list.bullet.rectangle")
                    .symbolVariant(segmentListAnyVisible ? .fill : .none)
                    .foregroundStyle(segmentListAnyVisible ? LuminaTheme.accent : .primary)
            }
            .help(segmentListAnyVisible ? "收起段列表" : "展开段列表")
        }

        ToolbarItemGroup {
            if librarySummarizeOverviewActive {
                readerSummarizeActivityChip
            }

            Picker("阅读模式", selection: $contentMode) {
                ForEach(ReaderContentMode.allCases, id: \.self) { mode in
                    Text(mode.label).tag(mode)
                }
            }
            .pickerStyle(.segmented)
            .frame(width: 120)
            .help("切换摘要 / 原文阅读模式（⌘⇧O）")

            Button("笔记") {
                openOverlay(.notes, engaged: true)
            }
            .disabled(viewModel.bookStatus == "processing")
            Button("提问") {
                openOverlay(.chat, engaged: true)
            }
            .disabled(viewModel.bookStatus == "processing")

            Menu("摘要") {
                Menu("开始摘要") {
                    ForEach(SummaryTier.allCases) { tier in
                        Button(tier.startMenuLabel) {
                            Task {
                                do {
                                    try await viewModel.startSummarize(
                                        core: core, summaryTier: tier
                                    )
                                } catch {
                                    actionError = error.localizedDescription
                                }
                            }
                        }
                    }
                }
                Button("停止摘要") {
                    Task {
                        do { try await viewModel.stopSummarize(core: core) }
                        catch { actionError = error.localizedDescription }
                    }
                }
                Divider()
                Menu("全书重新摘要") {
                    ForEach(SummaryTier.allCases) { tier in
                        Button(tier.regenerateMenuLabel) {
                            regenerateSummaryTier = tier
                            showRegenerateConfirm = true
                        }
                    }
                }
            }
            .help("开始摘要只处理未摘要段落；全书重新摘要会覆盖已有摘要，操作前会要求确认")
            .disabled(viewModel.bookStatus == "processing")
            Button("整书重新分段") {
                prepareResegment()
            }
            .disabled(viewModel.bookStatus == "processing")
            Button("调整分段") {
                openBoundaryEditor()
            }
            .disabled(viewModel.bookStatus == "processing" || viewModel.segments.count < 2)
            Button("导出") { showExport = true }
                .disabled(viewModel.bookStatus == "processing")
        }
    }

    private var readerLayout: some View {
        HStack(spacing: 0) {
            if segmentListInlineVisible {
                segmentSidebarPanel(isOverlay: false)
                    .transition(.move(edge: .leading).combined(with: .opacity))
            }

            ZStack {
                segmentContent
                    .frame(maxWidth: .infinity, maxHeight: .infinity)

                HStack(spacing: 0) {
                    if segmentListOverlayVisible {
                        segmentSidebarPanel(isOverlay: true)
                            .shadow(color: .black.opacity(0.12), radius: 12, x: 2, y: 0)
                            .transition(.move(edge: .leading).combined(with: .opacity))
                    }
                    Spacer(minLength: 0)
                }
                .allowsHitTesting(segmentListOverlayVisible)

                if edgeIconsVisible {
                    readerEdgeIconsOverlay
                        .transition(.opacity.combined(with: .scale(scale: 0.92)))
                }

                if overlay != .none {
                    Color.black.opacity(0.18)
                        .ignoresSafeArea()
                        .contentShape(Rectangle())
                        .onTapGesture { closeOverlay() }
                        .transition(.opacity)
                }

                HStack(spacing: 0) {
                    Spacer(minLength: 0)
                    notesDrawer
                        .offset(x: overlay == .notes ? 0 : notesWidth)
                }
                .allowsHitTesting(overlay == .notes)

                VStack(spacing: 0) {
                    Spacer(minLength: 0)
                    chatDrawer
                        .offset(y: overlay == .chat ? 0 : chatHeight + 40)
                }
                .allowsHitTesting(overlay == .chat)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .animation(.easeInOut(duration: 0.25), value: segmentListInlineVisible)
        .animation(.easeInOut(duration: 0.25), value: segmentListOverlayVisible)
        .animation(.easeInOut(duration: 0.25), value: overlay)
        .animation(.easeInOut(duration: 0.25), value: chromeMode)
        .animation(.easeInOut(duration: 0.25), value: edgeIconsVisible)
        .background(
            EdgeHoverTracker(continuousTracking: segmentListOverlayVisible) { point, size in
                if readerSize != size { readerSize = size }
                handleEdgePointer(point)
            }
        )
        .onExitCommand { closeOverlay() }
        .onChange(of: overlay) { _, newValue in
            chatFocused = newValue == .chat && overlayEngaged
            readerOverlayActive = newValue != .none
            if newValue != .none {
                cancelEdgeDwell()
                setChromeMode(.revealed, closingSegmentPeek: true)
            } else {
                readerContentFocused = true
                setChromeMode(.revealed)
            }
        }
        .onChange(of: overlayEngaged) { _, engaged in
            if engaged, overlay == .chat { chatFocused = true }
        }
        .onChange(of: chromeMode) { _, mode in
            readerChromeVisible = mode != .hidden
                || overlay != .none
                || viewModel.bookStatus == "processing"
        }
        .onChange(of: viewModel.bookStatus) { _, status in
            if status == "processing" {
                setChromeMode(.revealed)
                readerChromeVisible = true
            }
        }
        .onAppear {
            readerOverlayActive = overlay != .none
            readerChromeVisible = toolbarVisible
        }
        .onChange(of: viewModel.selectedIdx) { _, idx in
            guard let idx else { return }
            viewModel.selectSegment(idx)
            // A selection that came from the pinned segment must not scroll back.
            guard !viewModel.consumeTopSegmentSelection(idx) else { return }
            jump(to: idx)
        }
        .onChange(of: topSegmentIdx) { _, idx in
            guard let idx else { return }
            if viewModel.progressPhase == .restoring {
                // Correct a stray pin while the feed is still materializing.
                if let target = viewModel.restoreTarget, target != idx {
                    topSegmentIdx = target
                }
                return
            }
            viewModel.noteTopSegment(idx)
            viewModel.prefetchSummaries(around: idx, core: core, radius: 3)
            if contentMode == .original {
                viewModel.prefetchSources(around: idx, core: core, radius: 3)
            }
        }
        .onPreferenceChange(ReaderGlobalFrameKey.self) { frame in
            readerGlobalFrame = frame
        }
        .onChange(of: contentMode) { _, mode in
            ReaderPreferences.setContentMode(mode, for: bookId)
            viewModel.setContentMode(mode)
            if mode == .original {
                let idx = topSegmentIdx ?? viewModel.selectedIdx ?? viewModel.segments.first?.idx ?? 0
                viewModel.prefetchSources(around: idx, core: core, radius: 5)
            }
        }
        .task(id: bookId) {
            overlay = .none
            overlayEngaged = false
            applySegmentListVisibility(ReaderSegmentListPolicy.endPeek(segmentListVisibility))
            chromeMode = .revealed
            readerChromeVisible = true
            expandedSourceSegments = []
            expandedSummarySegments = []
            contentMode = ReaderPreferences.contentMode(for: bookId)
            viewModel.setContentMode(contentMode)
            topSegmentIdx = nil
            // The resume index is delivered before the segments are published so
            // the feed's very first layout already renders at the saved segment.
            await viewModel.load(
                bookId: bookId,
                core: core,
                initialSegmentIndex: initialSegmentIndex
            ) { resumeIdx in
                topSegmentIdx = resumeIdx
            }
            readerContentFocused = true
            if contentMode == .original, let idx = viewModel.selectedIdx {
                viewModel.prefetchSources(around: idx, core: core, radius: 5)
            }
            if let idx = viewModel.selectedIdx {
                viewModel.prefetchSummaries(around: idx, core: core, radius: 5)
            }
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .background {
                Task { await viewModel.flushProgressSave() }
            }
        }
        .onDisappear {
            Task {
                await viewModel.flushProgressSave()
                NotificationCenter.default.post(name: .luminaLibraryRefresh, object: nil)
                viewModel.cancelAllTasks()
            }
        }
    }

    // MARK: - Content

    private var processingContent: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(viewModel.isResegmenting ? "正在重新分段…" : "正在解析文档…")
                .font(.headline)
            if let progress = viewModel.ingestProgress {
                Text(progress.label)
                    .font(.caption)
                    .foregroundStyle(LuminaTheme.textSecondary)
                if progress.total > 0 {
                    ProgressView(
                        value: Double(progress.page),
                        total: Double(progress.total)
                    )
                    .controlSize(.small)
                    .tint(LuminaTheme.accent)
                } else {
                    ProgressView()
                        .controlSize(.small)
                        .tint(LuminaTheme.accent)
                }
            } else {
                ProgressView()
                    .controlSize(.small)
                    .tint(LuminaTheme.accent)
            }
            Text(
                viewModel.isResegmenting
                    ? "完成后会清空旧摘要、笔记和本书对话，并从第一段开始阅读。"
                    : "扫描版 PDF 会在后台 OCR，可能需要几分钟。你可以返回书架做别的事，也可以取消导入。"
            )
                .font(.caption)
                .foregroundStyle(LuminaTheme.textSecondary)
            if viewModel.isResegmenting {
                Button(viewModel.isResegmentCancelling ? "正在取消…" : "取消重新分段") {
                    Task {
                        do { try await viewModel.cancelResegment(core: core) }
                        catch { actionError = error.localizedDescription }
                    }
                }
                .disabled(viewModel.isResegmentCancelling)
            } else {
                Button(viewModel.isIngestCancelling ? "正在取消…" : "取消导入") {
                    Task {
                        do { try await viewModel.cancelIngest(core: core) }
                        catch { actionError = error.localizedDescription }
                    }
                }
                .disabled(viewModel.isIngestCancelling)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(LuminaTheme.summaryPadding)
    }

    private func loadErrorContent(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("无法加载")
                .font(.headline)
            Text(message)
                .font(.body)
                .foregroundStyle(LuminaTheme.textSecondary)
            Button("重试") {
                Task {
                    await viewModel.reload(
                        core: core,
                        initialSegmentIndex: initialSegmentIndex
                    ) { resumeIdx in
                        topSegmentIdx = resumeIdx
                    }
                }
            }
            .buttonStyle(.borderedProminent)
            .tint(LuminaTheme.accent)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(LuminaTheme.summaryPadding)
    }

    private var segmentContent: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                LazyVStack(alignment: .leading, spacing: segmentFeedGap) {
                    if let error = viewModel.loadError {
                        loadErrorContent(error)
                    } else if viewModel.bookStatus == "processing" {
                        processingContent
                    } else if viewModel.segments.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            ProgressView()
                                .controlSize(.small)
                            Text("正在加载…")
                                .font(.caption)
                                .foregroundStyle(LuminaTheme.textSecondary)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(LuminaTheme.summaryPadding)
                    } else {
                        ForEach(viewModel.segments, id: \.idx) { seg in
                            segmentBlock(for: seg)
                        }
                    }
                }
                .scrollTargetLayout()

                if !viewModel.segments.isEmpty {
                    Color.clear
                        .frame(
                            height: ReadingProgress.endPinSpacerHeight(
                                viewportHeight: readerGlobalFrame.height
                            )
                        )
                        .allowsHitTesting(false)
                        .accessibilityHidden(true)
                }
            }
            .readingColumn()
            .padding(.horizontal, LuminaTheme.summaryPadding)
            .padding(.vertical, LuminaTheme.summaryPadding)
            .frame(maxWidth: .infinity, alignment: .leading)
            // Controls inside the feed keep their own clicks: SwiftUI gives the
            // tap to the frontmost handler, so only reading surface lands here.
            .contentShape(Rectangle())
            .onTapGesture { toggleChromeOnBlankClick() }
        }
        .scrollPosition(id: $topSegmentIdx, anchor: .top)
        .safeAreaInset(edge: .top, spacing: 0) {
            if shouldShowContentSummaryProgress {
                VStack(alignment: .leading, spacing: 8) {
                    if !toolbarVisible {
                        readerSummarizeActivityChip
                    }
                    SummaryProgressBanner(
                        readyCount: viewModel.summaryReadyCount,
                        totalCount: viewModel.summaryTotalCount,
                        activityLabel: viewModel.summarizeActivityLabel,
                        activeLabelProvider: viewModel.activeSummarizeLabel
                    )
                }
                .readingColumn()
                .padding(.horizontal, LuminaTheme.summaryPadding)
                .padding(.vertical, 8)
                .background(LuminaTheme.background)
            }
        }
        .background {
            ScrollViewKeyHandler(
                enabled: readerKeyboardScrollEnabled
            )
        }
        .animation(.easeOut(duration: 0.2), value: contentMode)
        .background(LuminaTheme.background)
        .background {
            GeometryReader { geo in
                Color.clear.preference(
                    key: ReaderGlobalFrameKey.self,
                    value: geo.frame(in: .global)
                )
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .focusable()
        .focused($readerContentFocused)
        .focusEffectDisabled()
        .onAppear { readerContentFocused = true }
        .onKeyPress("[") {
            guard readerContentFocused else { return .ignored }
            navigateSegment(delta: -1)
            return .handled
        }
        .onKeyPress("]") {
            guard readerContentFocused else { return .ignored }
            navigateSegment(delta: 1)
            return .handled
        }
        .onKeyPress("【") {
            guard readerContentFocused else { return .ignored }
            navigateSegment(delta: -1)
            return .handled
        }
        .onKeyPress("】") {
            guard readerContentFocused else { return .ignored }
            navigateSegment(delta: 1)
            return .handled
        }
        .onKeyPress(.upArrow) {
            guard readerKeyboardScrollEnabled else { return .ignored }
            NotificationCenter.default.post(
                name: .luminaScrollContent,
                object: nil,
                userInfo: ["delta": -ReaderKeyboardScroll.lineDelta]
            )
            return .handled
        }
        .onKeyPress(.downArrow) {
            guard readerKeyboardScrollEnabled else { return .ignored }
            NotificationCenter.default.post(
                name: .luminaScrollContent,
                object: nil,
                userInfo: ["delta": ReaderKeyboardScroll.lineDelta]
            )
            return .handled
        }
        .onKeyPress(.pageUp) {
            guard readerKeyboardScrollEnabled else { return .ignored }
            NotificationCenter.default.post(name: .luminaScrollContent, object: nil, userInfo: ["page": -1])
            return .handled
        }
        .onKeyPress(.pageDown) {
            guard readerKeyboardScrollEnabled else { return .ignored }
            NotificationCenter.default.post(name: .luminaScrollContent, object: nil, userInfo: ["page": 1])
            return .handled
        }
    }

    private func toggleSource(for idx: Int) {
        if expandedSourceSegments.contains(idx) {
            withAnimation(.easeOut(duration: 0.2)) {
                expandedSourceSegments.remove(idx)
            }
        } else {
            withAnimation(.easeOut(duration: 0.2)) {
                expandedSourceSegments.insert(idx)
            }
            viewModel.fetchSource(idx: idx, core: core)
        }
    }

    private func toggleSummary(for idx: Int) {
        withAnimation(.easeOut(duration: 0.2)) {
            if expandedSummarySegments.contains(idx) {
                expandedSummarySegments.remove(idx)
            } else {
                expandedSummarySegments.insert(idx)
            }
        }
    }

    private func toggleContentMode() {
        contentMode = contentMode == .summary ? .original : .summary
    }

    @ViewBuilder
    private func segmentBlock(for seg: SegmentRow) -> some View {
        let cachedSource = viewModel.cachedSource(for: seg.idx)
        let idx = seg.idx
        let isLast = seg.idx == viewModel.segments.last?.idx
        SegmentReadingBlock(
            contentMode: contentMode,
            segment: seg,
            segmentTotal: viewModel.segments.count,
            isLast: isLast,
            isHighlighted: highlightSegment == idx,
            isSourceExpanded: contentMode == .original || expandedSourceSegments.contains(idx),
            isSummaryExpanded: expandedSummarySegments.contains(idx),
            sourceBody: cachedSource,
            isSourceLoading: viewModel.isSourceLoading(idx: idx),
            isSourceRefreshing: viewModel.isSourceRefreshing(idx: idx),
            needsTranslation: viewModel.needsTranslation(for: cachedSource?.rawText),
            parsedSummary: viewModel.parsedSummary(for: idx),
            isSummaryLoading: viewModel.isSummaryLoading(for: idx),
            summaryProgressMessage: viewModel.segmentProgressMessage(for: idx),
            runningMetrics: viewModel.segmentRunningMetrics[idx],
            onToggleSource: { toggleSource(for: idx) },
            onToggleSummary: { toggleSummary(for: idx) },
            onFollowUp: { question in
                openOverlay(.chat, engaged: true)
                Task { await viewModel.sendChat(question, core: core) }
            },
            onRetrySummary: { summaryTier in
                Task {
                    do {
                        try await viewModel.retrySegment(
                            idx,
                            summaryTier: summaryTier,
                            core: core
                        )
                    }
                    catch { actionError = error.localizedDescription }
                }
            },
            canGoPrev: SegmentTurnNavigation.targetIdx(
                current: idx, delta: -1, sortedIdxs: viewModel.segments.map(\.idx).sorted()
            ) != nil,
            canGoNext: SegmentTurnNavigation.targetIdx(
                current: idx, delta: 1, sortedIdxs: viewModel.segments.map(\.idx).sorted()
            ) != nil,
            onPrevSegment: { turnSegment(from: idx, delta: -1) },
            onNextSegment: { turnSegment(from: idx, delta: 1) },
            onAdjustBoundary: isLast ? nil : { openBoundaryEditor(at: idx) },
            onSourceAppear: contentMode == .original
                ? { viewModel.fetchSource(idx: idx, core: core) }
                : nil
        )
        .equatable()
        .onAppear {
            viewModel.hydrateSummary(idx: idx, core: core)
        }
    }

    /// The one and only way to move the reader. Assigning the pinned segment is
    /// the scroll: SwiftUI owns the anchoring, nothing else touches the origin.
    private func jump(to idx: Int) {
        guard topSegmentIdx != idx else { return }
        let delta = SegmentRenderWindow.segmentIndexDelta(
            from: topSegmentIdx,
            to: idx,
            in: viewModel.segments
        )
        if delta <= SegmentRenderWindow.scrollAnimateThreshold {
            withAnimation(.easeInOut(duration: segmentSwitchDuration)) {
                topSegmentIdx = idx
            }
        } else {
            var transaction = Transaction()
            transaction.disablesAnimations = true
            withTransaction(transaction) {
                topSegmentIdx = idx
            }
        }
    }

    private func navigateSegment(delta: Int) {
        guard overlay == .none, !chatFocused else { return }
        let current = viewModel.selectedIdx ?? topSegmentIdx
        guard let current else { return }
        turnSegment(from: current, delta: delta)
    }

    private func turnSegment(from idx: Int, delta: Int) {
        let sorted = viewModel.segments.map(\.idx).sorted()
        guard let target = SegmentTurnNavigation.targetIdx(
            current: idx, delta: delta, sortedIdxs: sorted
        ) else { return }
        navigateToSegment(target)
    }

    private func navigateToSegment(_ idx: Int) {
        viewModel.selectedIdx = idx
        readerContentFocused = true
        jump(to: idx)
    }

    private func selectSidebarSegment(_ idx: Int) {
        viewModel.selectedIdx = idx
        jump(to: idx)
    }

    // MARK: - Sidebar & drawers

    private var readerEdgeIconsOverlay: some View {
        // Only the icons themselves accept hits — never a full-size Spacer layer.
        Color.clear
            .allowsHitTesting(false)
            .overlay(alignment: .leading) {
                ReaderEdgeIcon(
                    systemImage: "list.bullet.rectangle",
                    label: "段列表",
                    isActive: segmentListAnyVisible
                ) {
                    toggleSegmentList()
                }
                .padding(.leading, 6)
            }
            .overlay(alignment: .trailing) {
                ReaderEdgeIcon(
                    systemImage: "note.text",
                    label: "笔记",
                    isActive: overlay == .notes
                ) {
                    openOverlay(.notes, engaged: true)
                }
                .padding(.trailing, 6)
            }
            .overlay(alignment: .bottom) {
                ReaderEdgeIcon(
                    systemImage: "bubble.left.and.bubble.right",
                    label: "深聊",
                    isActive: overlay == .chat
                ) {
                    openOverlay(.chat, engaged: true)
                }
                .padding(.bottom, 8)
            }
    }

    private func segmentSidebarPanel(isOverlay: Bool) -> some View {
        VStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("段列表")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(LuminaTheme.textPrimary)
                    Spacer(minLength: 0)
                    sidebarHeaderButtons
                }

                SummaryProgressBanner(
                    readyCount: viewModel.summaryReadyCount,
                    totalCount: viewModel.summaryTotalCount,
                    activityLabel: viewModel.summarizeActivityLabel,
                    activeLabelProvider: viewModel.activeSummarizeLabel,
                    hideWhenComplete: false
                )

                readerSummarizeActivityChip

                Button("导出摘要…") {
                    exportIncludeNotes = false
                    showExport = true
                }
                .font(.caption)
                .buttonStyle(.plain)
                .foregroundStyle(LuminaTheme.accent)
                .disabled(viewModel.summaryReadyCount == 0)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)

            if viewModel.isSegmentSelectionMode {
                HStack(spacing: 8) {
                    Button("重新摘要 (\(viewModel.checkedSegmentIndices.count))") {
                        Task {
                            do { try await viewModel.retryCheckedSegments(core: core) }
                            catch { actionError = error.localizedDescription }
                        }
                    }
                    .font(.caption)
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    .disabled(viewModel.checkedSegmentIndices.isEmpty)

                    Spacer(minLength: 0)

                    Button("全选") {
                        viewModel.selectAllChecks()
                    }
                    .font(.caption)
                    .buttonStyle(.plain)

                    Button("完成") {
                        viewModel.exitSegmentSelectionMode()
                    }
                    .font(.caption)
                    .buttonStyle(.plain)
                }
                .padding(.horizontal, 10)
                .padding(.bottom, 6)
            }

            Divider()

            segmentSidebar
        }
        .frame(width: segmentsWidth)
        .frame(maxHeight: .infinity)
        .background(LuminaTheme.surface)
        .overlay(alignment: .trailing) {
            if !isOverlay {
                Divider()
            }
        }
    }

    @ViewBuilder
    private var sidebarHeaderButtons: some View {
        Button {
            viewModel.toggleSegmentSelectionMode()
        } label: {
            Image(systemName: viewModel.isSegmentSelectionMode ? "checklist.checked" : "checklist")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(
                    viewModel.isSegmentSelectionMode
                        ? LuminaTheme.accent
                        : LuminaTheme.textSecondary
                )
                .frame(width: 24, height: 24)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help(viewModel.isSegmentSelectionMode ? "退出多选" : "多选")
        if !segmentListPinned {
            Button {
                withAnimation(.easeInOut(duration: 0.25)) {
                    applySegmentListVisibility(ReaderSegmentListPolicy.pin(segmentListVisibility))
                    chromeMode = .revealed
                }
            } label: {
                Image(systemName: "pin")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(LuminaTheme.textSecondary)
                    .frame(width: 24, height: 24)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .help("钉住段列表")
        }
        Button {
            withAnimation(.easeInOut(duration: 0.25)) {
                applySegmentListVisibility(ReaderSegmentListPolicy.close(segmentListVisibility))
            }
        } label: {
            Image(systemName: "chevron.left")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(LuminaTheme.textSecondary)
                .frame(width: 24, height: 24)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help("收起段列表")
    }

    @ViewBuilder
    private var readerSummarizeActivityChip: some View {
        if let overview = libraryViewModel.summarizeOverview,
           SummarizeActivityChip.shouldShow(activeCount: overview.activeCount) {
            SummarizeActivityChip(
                running: overview.counts.running,
                queued: overview.counts.queued,
                indexing: overview.indexingCount,
                stalledReason: overview.stalled_reason,
                isBusy: summarizeActionInFlight
            ) {
                Task { await stopAllSummarize() }
            }
            .disabled(summarizeActionInFlight)
        }
    }

    private func stopAllSummarize() async {
        guard !summarizeActionInFlight else { return }
        summarizeActionInFlight = true
        defer { summarizeActionInFlight = false }
        do {
            try await core.stopSummarizeAll()
            viewModel.markSummarizePaused()
            try await libraryViewModel.refresh(using: core, preserveOrder: true)
        } catch {
            actionError = error.localizedDescription
        }
    }

    private var notesDrawer: some View {
        NotesPanel(
            bookId: bookId,
            segmentId: viewModel.currentSegment?.id,
            refreshToken: notesRefreshToken,
            onSelectSegment: { idx in
                navigateToSegment(idx)
            }
        )
        .frame(width: notesWidth)
        .frame(maxHeight: .infinity)
        .background(LuminaTheme.surface)
        .overlay(alignment: .leading) {
            Divider()
        }
        .shadow(color: .black.opacity(overlay == .notes ? 0.12 : 0), radius: 12, x: -2, y: 0)
        .simultaneousGesture(TapGesture().onEnded { overlayEngaged = true })
    }

    private var chatDrawer: some View {
        VStack(spacing: 0) {
            Capsule()
                .fill(Color.secondary.opacity(0.35))
                .frame(width: 36, height: 4)
                .padding(.top, 8)
                .padding(.bottom, 4)
            chatPanel
        }
        .frame(maxWidth: .infinity)
        .frame(height: chatHeight)
        .background(LuminaTheme.surface)
        .overlay(alignment: .top) {
            Divider()
        }
        .shadow(color: .black.opacity(overlay == .chat ? 0.12 : 0), radius: 12, x: 0, y: -2)
        .simultaneousGesture(TapGesture().onEnded { overlayEngaged = true })
    }

    private var segmentSidebar: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(viewModel.segments) { seg in
                        segmentSidebarRow(seg)
                            .id(seg.idx)
                    }
                }
            }
            .onChange(of: viewModel.selectedIdx) { _, idx in
                guard let idx else { return }
                withAnimation(.easeInOut(duration: segmentSwitchDuration)) {
                    proxy.scrollTo(idx, anchor: .center)
                }
            }
            .onAppear {
                guard let idx = viewModel.selectedIdx else { return }
                Task { @MainActor in
                    await Task.yield()
                    proxy.scrollTo(idx, anchor: .center)
                }
            }
        }
    }

    @ViewBuilder
    private func segmentSidebarRow(_ seg: SegmentRow) -> some View {
        let rowContent = HStack(alignment: .top, spacing: 6) {
            if viewModel.isSegmentSelectionMode {
                Toggle(
                    isOn: Binding(
                        get: { viewModel.checkedSegmentIndices.contains(seg.idx) },
                        set: { on in
                            if on {
                                viewModel.checkedSegmentIndices.insert(seg.idx)
                            } else {
                                viewModel.checkedSegmentIndices.remove(seg.idx)
                            }
                        }
                    )
                ) {
                    EmptyView()
                }
                .toggleStyle(.checkbox)
                .labelsHidden()
            }

            statusIcon(for: seg)
            SegmentSidebarRow(
                segment: seg,
                runningMetrics: viewModel.segmentRunningMetrics[seg.idx],
                bulletsPreview: viewModel.sidebarPreviewByIdx[seg.idx]
            )
        }
        .contentShape(Rectangle())
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            viewModel.selectedIdx == seg.idx
                ? LuminaTheme.listSelectionBackground
                : Color.clear
        )

        Group {
            if viewModel.isSegmentSelectionMode {
                rowContent
                    .onTapGesture { viewModel.toggleCheck(seg.idx) }
            } else {
                Button {
                    selectSidebarSegment(seg.idx)
                } label: {
                    rowContent
                }
                .buttonStyle(.plain)
            }
        }
        .contextMenu {
            if viewModel.checkedSegmentIndices.contains(seg.idx),
               viewModel.checkedSegmentIndices.count > 1 {
                Button("重新摘要选中 (\(viewModel.checkedSegmentIndices.count))") {
                    Task {
                        do { try await viewModel.retryCheckedSegments(core: core) }
                        catch { actionError = error.localizedDescription }
                    }
                }
            } else {
                Button("重新摘要") {
                    Task {
                        do { try await viewModel.retrySegment(seg.idx, core: core) }
                        catch { actionError = error.localizedDescription }
                    }
                }
            }
        }
    }

    private var chatPanel: some View {
        VStack(spacing: 8) {
            HStack {
                Text("深聊").font(.headline)
                Picker("范围", selection: $viewModel.chatScope) {
                    Text("当前段").tag(ReaderChatScope.segment)
                    Text(viewModel.bookChatPickerLabel).tag(ReaderChatScope.book)
                }
                .pickerStyle(.segmented)
                .frame(maxWidth: 220)
                .onChange(of: viewModel.chatScope) { _, newValue in
                    guard newValue == .book, !viewModel.canChatBook else { return }
                    let shouldBuild = viewModel.needsBookIndexBuild
                    viewModel.chatScope = .segment
                    guard shouldBuild else { return }
                    Task { await viewModel.buildBookIndex(core: core) }
                }
                Spacer()
                Button {
                    closeOverlay()
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal)

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 8) {
                        ForEach(viewModel.messages) { msg in
                            VStack(alignment: .leading, spacing: 4) {
                                HStack {
                                    Text(msg.role == "user" ? "你" : "深聊")
                                        .font(.caption.bold())
                                    if msg.role == "assistant", msg.content.isEmpty, viewModel.isSending {
                                        ProgressView()
                                            .controlSize(.small)
                                        Text(viewModel.chatStatus ?? "正在响应…")
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                    if msg.role == "assistant", !msg.content.isEmpty {
                                        Button("存为笔记") {
                                            Task { await saveChatAsNote(msg.content) }
                                        }
                                        .font(.caption)
                                    }
                                }
                                if !msg.content.isEmpty {
                                    Text(msg.content)
                                }
                                ForEach(msg.citations, id: \.segment_index) { c in
                                    Button(c.label) {
                                        navigateToSegment(c.segment_index)
                                        highlightSegment = c.segment_index
                                        closeOverlay()
                                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                                            highlightSegment = nil
                                        }
                                    }
                                    .buttonStyle(.link)
                                }
                                ForEach(msg.webRefs) { ref in
                                    if let url = URL(string: ref.url) {
                                        Link(ref.displayLabel, destination: url)
                                            .font(.caption)
                                    }
                                }
                                if let attribution = ChatMetricsFormatter.attribution(for: msg) {
                                    Text(attribution)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            .padding(8)
                            .background(msg.role == "user" ? Color.blue.opacity(0.08) : Color.gray.opacity(0.08))
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                            .id(msg.id)
                        }
                    }
                    .padding(.horizontal)
                }
                .onChange(of: viewModel.messages.count) { _, _ in
                    scrollChatToBottom(proxy: proxy)
                }
                .onChange(of: viewModel.messages.last?.content) { _, _ in
                    scrollChatToBottom(proxy: proxy)
                }
            }

            HStack {
                TextField(viewModel.chatPlaceholder, text: $chatInput)
                    .textFieldStyle(.roundedBorder)
                    .focused($chatFocused)
                    .disabled(viewModel.isSending)
                    .onChange(of: chatInput) { _, newValue in
                        if !newValue.isEmpty { overlayEngaged = true }
                    }
                    .onSubmit { submitChat() }
                Button("发送") { submitChat() }
                    .disabled(
                        chatInput.trimmingCharacters(in: .whitespaces).isEmpty || viewModel.isSending
                    )
            }
            .padding(.horizontal)
            .padding(.bottom, 8)
        }
    }

    private func submitChat() {
        let text = chatInput.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !viewModel.isSending else { return }
        chatInput = ""
        overlayEngaged = true
        Task { await viewModel.sendChat(text, core: core) }
    }

    private func scrollChatToBottom(proxy: ScrollViewProxy) {
        guard let last = viewModel.messages.last else { return }
        withAnimation(.easeOut(duration: 0.2)) {
            proxy.scrollTo(last.id, anchor: .bottom)
        }
    }

    // MARK: - Edge hover & overlay

    private func handleEdgePointer(_ point: CGPoint?) {
        if overlay != .none, !overlayEngaged {
            let stillInOverlay = point.map { isPointerInOverlay($0, overlay: overlay, size: readerSize) } ?? false
            if !stillInOverlay {
                closeOverlay()
            }
        }

        if overlay != .none {
            cancelEdgeDwell()
            return
        }

        if segmentListOverlayVisible {
            let inList = point.map { isPointerInSegmentList($0, size: readerSize) } ?? false
            let inEdge = point.map { isPointerInLeftEdge($0) } ?? false
            if point == nil || (!inList && !inEdge) {
                withAnimation(.easeInOut(duration: 0.25)) {
                    applySegmentListVisibility(ReaderSegmentListPolicy.endPeek(segmentListVisibility))
                }
            }
        }

        let target = point.flatMap { edgeTarget(at: $0, in: readerSize) }

        guard let target else {
            cancelEdgeDwell()
            return
        }

        if pendingEdge == target { return }
        cancelEdgeDwell()
        pendingEdge = target
        dwellTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: edgeDwellNanoseconds)
            guard !Task.isCancelled, pendingEdge == target, overlay == .none else { return }
            pendingEdge = nil
            switch target {
            case .segments:
                if segmentListVisibility.pinned {
                    setChromeMode(.revealed)
                } else {
                    withAnimation(.easeInOut(duration: 0.25)) {
                        applySegmentListVisibility(
                            ReaderSegmentListPolicy.beginEdgePeek(segmentListVisibility)
                        )
                    }
                }
            case .notes:
                withAnimation(.easeInOut(duration: 0.25)) {
                    overlayEngaged = false
                    overlay = .notes
                }
            case .chat:
                withAnimation(.easeInOut(duration: 0.25)) {
                    overlayEngaged = false
                    overlay = .chat
                }
            }
        }
    }

    private func isPointerInSegmentList(_ point: CGPoint, size: CGSize) -> Bool {
        ReaderSegmentListGeometry.isPointerInSegmentList(point, segmentsWidth: segmentsWidth)
    }

    private func isPointerInLeftEdge(_ point: CGPoint) -> Bool {
        point.x <= edgeHotZone && point.y > topEdgeExclusionZone
    }

    private func setChromeMode(_ mode: ReaderChromeMode, closingSegmentPeek: Bool = false) {
        let needsChrome = chromeMode != mode
        let needsPeekClose = closingSegmentPeek && segmentListPeeking
        guard needsChrome || needsPeekClose else { return }
        withAnimation(.easeInOut(duration: 0.25)) {
            if needsChrome {
                chromeMode = mode
            }
            if needsPeekClose {
                applySegmentListVisibility(ReaderSegmentListPolicy.endPeek(segmentListVisibility))
            }
        }
    }

    private func collapseAllChrome() {
        withAnimation(.easeInOut(duration: 0.25)) {
            chromeMode = .hidden
            applySegmentListVisibility(ReaderSegmentListPolicy.endPeek(segmentListVisibility))
            overlay = .none
            overlayEngaged = false
        }
    }

    private func toggleChromeOnBlankClick() {
        switch ReaderChromeClickPolicy.outcome(
            overlayOpen: overlay != .none,
            segmentPeekVisible: segmentListOverlayVisible,
            chromeHidden: chromeMode == .hidden
        ) {
        case .ignore:
            break
        case .closeSegmentPeek:
            withAnimation(.easeInOut(duration: 0.25)) {
                applySegmentListVisibility(ReaderSegmentListPolicy.endPeek(segmentListVisibility))
            }
        case .collapse:
            collapseAllChrome()
        case .reveal:
            setChromeMode(.revealed)
        }
    }

    private func toggleLibrarySidebar() {
        withAnimation(.easeInOut(duration: 0.25)) {
            librarySidebarPinned.toggle()
        }
    }

    private func toggleSegmentList() {
        guard overlay == .none else { return }
        let next = ReaderSegmentListPolicy.toggleByExplicitClick(segmentListVisibility)
        withAnimation(.easeInOut(duration: 0.25)) {
            applySegmentListVisibility(next)
            if next.pinned {
                chromeMode = .revealed
            }
        }
    }

    private func applySegmentListVisibility(_ next: ReaderSegmentListVisibility) {
        segmentListPinned = next.pinned
        segmentListPeeking = next.peeking
    }

    private func isPointerInOverlay(_ point: CGPoint, overlay: ReaderOverlay, size: CGSize) -> Bool {
        switch overlay {
        case .none:
            return false
        case .notes:
            return point.x >= size.width - notesWidth
        case .chat:
            return point.y >= size.height - chatHeight
        }
    }

    private func edgeTarget(at point: CGPoint, in size: CGSize) -> ReaderEdgeTarget? {
        guard size.width > 0, size.height > 0 else { return nil }
        guard chromeMode == .hidden else { return nil }
        if point.y <= topEdgeExclusionZone { return nil }
        if point.x <= edgeHotZone {
            return !segmentListAnyVisible ? .segments : nil
        }
        if point.x >= size.width - edgeHotZone { return .notes }
        if point.y >= size.height - edgeHotZone { return .chat }
        return nil
    }

    private func cancelEdgeDwell() {
        dwellTask?.cancel()
        dwellTask = nil
        pendingEdge = nil
    }

    private func closeOverlay() {
        withAnimation(.easeInOut(duration: 0.25)) {
            overlay = .none
            overlayEngaged = false
        }
    }

    private func openOverlay(_ kind: ReaderOverlay, engaged: Bool) {
        // Chrome reveal + segment-peek close happen once in onChange(of: overlay).
        withAnimation(.easeInOut(duration: 0.25)) {
            overlayEngaged = engaged
            overlay = kind
        }
    }

    private func saveChatAsNote(_ content: String) async {
        do {
            try await viewModel.saveAsNote(content, core: core)
            notesRefreshToken += 1
        } catch {
            if let message = error.userFacingMessage {
                noteError = message
            }
        }
    }

    @ViewBuilder
    private func statusIcon(for seg: SegmentRow) -> some View {
        Group {
            if seg.idx == viewModel.selectedIdx {
                Image(systemName: "largecircle.fill.circle")
                    .foregroundStyle(LuminaTheme.accent)
            } else {
                switch seg.summary_status {
                case "ready":
                    Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                case "running":
                    Image(systemName: "circle.lefthalf.filled").foregroundStyle(LuminaTheme.accent)
                case "failed", "error":
                    Image(systemName: "exclamationmark.circle").foregroundStyle(.red)
                default:
                    Image(systemName: "circle").foregroundStyle(.secondary)
                }
            }
        }
        .frame(width: 16, alignment: .center)
    }
}

struct SegmentSidebarRow: View {
    let segment: SegmentRow
    var runningMetrics: SegmentRunningMetrics?
    var bulletsPreview: String?

    private var chapterTitle: String {
        if let ch = segment.chapter, !ch.isEmpty { return ch }
        return "段 \(segment.idx + 1)"
    }

    private var showsLiveProgress: Bool {
        segment.summary_status == "running" && (segment.label == nil || segment.label?.isEmpty == true)
    }

    private var outlineLabel: String? {
        if let label = segment.label, !label.isEmpty { return label }
        switch segment.summary_status {
        case "running":
            return nil
        case "pending":
            return "等待摘要…"
        case "failed", "error":
            return SummaryMetricsFormatter.failureLabel(
                durationS: segment.summary_duration_s,
                retryCount: segment.retry_count
            )
        default:
            return nil
        }
    }

    private func statusCaption(at now: Date) -> String {
        if let runningMetrics {
            return SummaryMetricsFormatter.inProgressLabel(
                startedAt: runningMetrics.startedAt,
                llmAttempt: runningMetrics.llmAttempt,
                maxLlmAttempts: runningMetrics.maxLlmAttempts,
                now: now
            )
        }
        return "摘要生成中…"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(chapterTitle)
                .font(.subheadline)
                .lineLimit(1)
            if showsLiveProgress {
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    Text(statusCaption(at: context.date))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            } else if let outline = outlineLabel {
                Text(outline)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
            if let preview = bulletsPreview {
                Text(preview)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
    }
}

private struct ReaderGlobalFrameKey: PreferenceKey {
    static var defaultValue: CGRect = .null

    static func reduce(value: inout CGRect, nextValue: () -> CGRect) {
        let next = nextValue()
        if !next.isNull { value = next }
    }
}

/// Scrolls the enclosing NSScrollView on keyboard scroll notifications.
private struct ScrollViewKeyHandler: NSViewRepresentable {
    var enabled: Bool

    func makeNSView(context: Context) -> ScrollViewKeyNSView {
        let view = ScrollViewKeyNSView()
        view.isEnabled = enabled
        return view
    }

    func updateNSView(_ nsView: ScrollViewKeyNSView, context: Context) {
        nsView.isEnabled = enabled
    }
}

/// Keyboard scrolling only. This view must never move the scroll origin on its
/// own: anchoring belongs to SwiftUI's `scrollPosition`, and a second writer is
/// what used to make reading progress drift.
private final class ScrollViewKeyNSView: NSView {
    var isEnabled = true
    private var observer: NSObjectProtocol?
    private var keyMonitor: Any?
    private static weak var activeInstance: ScrollViewKeyNSView?
    private static weak var readerScrollView: NSScrollView?

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        if window != nil {
            Self.activeInstance = self
            Self.readerScrollView = Self.discoverScrollView(from: self)
            installKeyMonitor()
        } else {
            if Self.activeInstance === self {
                Self.activeInstance = nil
                Self.readerScrollView = nil
            }
            removeKeyMonitor()
        }
        if observer == nil {
            observer = NotificationCenter.default.addObserver(
                forName: .luminaScrollContent,
                object: nil,
                queue: .main
            ) { [weak self] note in
                self?.handleScroll(note)
            }
        }
    }

    deinit {
        if let observer {
            NotificationCenter.default.removeObserver(observer)
        }
        removeKeyMonitor()
    }

    private func installKeyMonitor() {
        guard keyMonitor == nil else { return }
        keyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self else { return event }
            return self.handleKeyDown(event)
        }
    }

    private func removeKeyMonitor() {
        if let keyMonitor {
            NSEvent.removeMonitor(keyMonitor)
            self.keyMonitor = nil
        }
    }

    private func handleKeyDown(_ event: NSEvent) -> NSEvent? {
        guard isEnabled, event.window == window else { return event }
        if window?.attachedSheet != nil { return event }
        guard !Self.isTextInputResponder(window?.firstResponder) else { return event }

        let mods = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
        if !mods.intersection([.command, .option, .control]).isEmpty { return event }

        switch event.keyCode {
        case 126: // up arrow
            performKeyboardScroll(lineDelta: -ReaderKeyboardScroll.lineDelta, page: nil)
            return nil
        case 125: // down arrow
            performKeyboardScroll(lineDelta: ReaderKeyboardScroll.lineDelta, page: nil)
            return nil
        case 116: // page up
            performKeyboardScroll(lineDelta: nil, page: -1)
            return nil
        case 121: // page down
            performKeyboardScroll(lineDelta: nil, page: 1)
            return nil
        default:
            return event
        }
    }

    private func handleScroll(_ note: Notification) {
        guard isEnabled else { return }
        if let delta = note.userInfo?["delta"] as? CGFloat {
            performKeyboardScroll(lineDelta: delta, page: nil)
        } else if let page = note.userInfo?["page"] as? Int {
            performKeyboardScroll(lineDelta: nil, page: page)
        }
    }

    private func performKeyboardScroll(lineDelta: CGFloat?, page: Int?) {
        let probeDelta: CGFloat
        if let lineDelta {
            probeDelta = lineDelta
        } else if let page {
            probeDelta = CGFloat(page)
        } else {
            return
        }
        guard let scrollView = Self.targetScrollView(deltaY: probeDelta) else { return }

        let clipView = scrollView.contentView
        let deltaY: CGFloat
        if let lineDelta {
            deltaY = lineDelta
        } else if let page {
            deltaY = ReaderKeyboardScroll.pageDelta(viewportHeight: clipView.bounds.height, page: page)
        } else {
            return
        }

        var origin = clipView.bounds.origin
        origin.y = ReaderKeyboardScroll.clampedOriginY(
            currentY: origin.y,
            deltaY: deltaY,
            viewportHeight: clipView.bounds.height,
            contentHeight: scrollView.documentView?.bounds.height ?? 0
        )
        Self.applyScrollOrigin(origin, to: scrollView)
    }

    private static func targetScrollView(deltaY: CGFloat) -> NSScrollView? {
        guard let main = resolvedScrollView else { return nil }
        if let nested = preferredNestedScrollView(in: main, deltaY: deltaY) {
            return nested
        }
        return main
    }

    private static func preferredNestedScrollView(in main: NSScrollView, deltaY: CGFloat) -> NSScrollView? {
        let clip = main.contentView
        let visible = clip.bounds
        var best: NSScrollView?
        var bestDistance = CGFloat.greatestFiniteMagnitude

        for nested in nestedScrollViews(in: main.documentView) {
            let frameInClip = nested.convert(nested.bounds, to: clip)
            guard visible.intersects(frameInClip) else { continue }
            guard canScroll(nested, by: deltaY) else { continue }
            let distance = abs(frameInClip.minY - visible.minY)
            if distance < bestDistance {
                bestDistance = distance
                best = nested
            }
        }
        return best
    }

    private static func nestedScrollViews(in root: NSView?) -> [NSScrollView] {
        guard let root else { return [] }
        var result: [NSScrollView] = []
        func walk(_ view: NSView) {
            if let sv = view as? NSScrollView {
                result.append(sv)
                return
            }
            for subview in view.subviews {
                walk(subview)
            }
        }
        walk(root)
        return result
    }

    private static func canScroll(_ scrollView: NSScrollView, by deltaY: CGFloat) -> Bool {
        let clip = scrollView.contentView
        let maxY = max(0, (scrollView.documentView?.bounds.height ?? 0) - clip.bounds.height)
        return ReaderKeyboardScroll.canMove(
            originY: clip.bounds.origin.y,
            deltaY: deltaY,
            maxY: maxY
        )
    }

    private static func isTextInputResponder(_ responder: NSResponder?) -> Bool {
        var current = responder
        while let node = current {
            if let textView = node as? NSTextView {
                if textView is LuminaSelectableTextView { return false }
                return textView.isEditable
            }
            if let field = node as? NSTextField {
                return field.isEditable
            }
            current = node.nextResponder
        }
        return false
    }

    private static var resolvedScrollView: NSScrollView? {
        readerScrollView ?? activeInstance?.enclosingScrollView
    }

    private static func discoverScrollView(from view: NSView) -> NSScrollView? {
        var current: NSView? = view
        while let node = current {
            if let scrollView = node as? NSScrollView { return scrollView }
            current = node.superview
        }
        guard let contentView = view.window?.contentView else { return nil }
        return findLargestScrollView(in: contentView)
    }

    private static func findLargestScrollView(in view: NSView) -> NSScrollView? {
        if let scrollView = view as? NSScrollView { return scrollView }
        var best: NSScrollView?
        var bestArea: CGFloat = 0
        for subview in view.subviews {
            guard let candidate = findLargestScrollView(in: subview) else { continue }
            let area = candidate.bounds.width * candidate.bounds.height
            if area > bestArea {
                bestArea = area
                best = candidate
            }
        }
        return best
    }

    private static func applyScrollOrigin(_ origin: NSPoint, to scrollView: NSScrollView) {
        let clipView = scrollView.contentView
        var clamped = origin
        let docHeight = scrollView.documentView?.bounds.height ?? 0
        let maxY = max(0, docHeight - clipView.bounds.height)
        clamped.y = min(max(0, clamped.y), maxY)
        clipView.setBoundsOrigin(clamped)
        scrollView.reflectScrolledClipView(clipView)
    }
}

extension Notification.Name {
    fileprivate static let luminaScrollContent = Notification.Name("luminaScrollContent")
}

struct SegmentSourceBody: Equatable {
    let idx: Int
    let rawText: String
    let translation: String
}

enum BookLanguageMatcher {
    static func normalize(_ code: String?) -> String? {
        guard let code, !code.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return nil
        }
        let primary = code
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: "_", with: "-")
            .lowercased()
            .split(separator: "-")
            .first
            .map(String.init)
        switch primary {
        case "zh", "cmn": return "zh"
        case "en": return "en"
        case "ja": return "ja"
        case "ko": return "ko"
        case "fr": return "fr"
        case "de": return "de"
        case "es": return "es"
        default: return primary
        }
    }

    static func languagesMatch(_ a: String?, _ b: String?) -> Bool {
        guard let na = normalize(a), let nb = normalize(b) else { return false }
        return na == nb
    }

    static func inferLanguage(from text: String) -> String? {
        let sample = String(text.prefix(4000))
        guard !sample.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }

        var cjk = 0
        var kana = 0
        var latin = 0
        for scalar in sample.unicodeScalars {
            switch scalar.value {
            case 0x4E00...0x9FFF: cjk += 1
            case 0x3040...0x309F, 0x30A0...0x30FF: kana += 1
            case 0x41...0x5A, 0x61...0x7A: latin += 1
            default: break
            }
        }
        let total = cjk + kana + latin
        guard total >= 20 else { return nil }
        if kana > cjk && kana >= latin { return "ja" }
        if cjk >= latin && Double(cjk) / Double(total) >= 0.15 { return "zh" }
        if Double(latin) / Double(total) >= 0.5 { return "en" }
        if cjk > 0 { return "zh" }
        if latin > 0 { return "en" }
        return nil
    }

    static func needsTranslation(
        bookLanguage: String?,
        bookTargetLanguage: String?,
        globalTargetLanguage: String,
        textSample: String?
    ) -> Bool {
        let effectiveTarget = bookTargetLanguage ?? globalTargetLanguage
        var effectiveBookLang = bookLanguage
        if effectiveBookLang == nil, let textSample {
            effectiveBookLang = inferLanguage(from: textSample)
        }
        guard effectiveBookLang != nil, !effectiveTarget.isEmpty else { return false }
        return !languagesMatch(effectiveBookLang, effectiveTarget)
    }
}

@MainActor
final class ReaderViewModel: ObservableObject {
    @Published var segments: [SegmentRow] = []
    @Published var selectedIdx: Int?
    @Published var checkedSegmentIndices: Set<Int> = []
    @Published var isSegmentSelectionMode = false
    @Published var currentSegment: SegmentRow?
    @Published private(set) var sourceCacheVersion = 0
    @Published var loadingSourceIndices: Set<Int> = []
    @Published var refreshingSourceIndices: Set<Int> = []
    @Published var messages: [ChatMessage] = []
    @Published var isSending = false
    @Published var chatStatus: String?
    @Published var chatScope: ReaderChatScope = .segment
    @Published var indexStatus = "idle"
    @Published private(set) var bookSummariesComplete = false
    @Published var summaryReadyCount = 0
    @Published var summaryTotalCount = 0
    @Published var summarizeState: String?
    @Published var segmentRunningMetrics: [Int: SegmentRunningMetrics] = [:]
    @Published var sidebarPreviewByIdx: [Int: String] = [:]
    @Published private(set) var parsedSummaryCache: [Int: ParsedSummary] = [:]
    @Published var totalCharCount: Int?
    @Published var chunkTargetChars: Int?
    @Published private(set) var bookStatus = "unread"
    @Published private(set) var isResegmenting = false
    @Published private(set) var isResegmentCancelling = false
    @Published private(set) var isIngestCancelling = false
    @Published var loadError: String?
    @Published var ingestProgress: IngestProgress?
    /// `restoring` until the feed settles on the resumed segment; `reading`
    /// afterwards, when the pinned segment is the progress.
    @Published private(set) var progressPhase: ReaderProgressPhase = .reading
    private(set) var restoreTarget: Int?
    private var restoreSettleTask: Task<Void, Never>?
    private var bookLanguage: String?
    private var bookTargetLanguage: String?
    private var bookTitle: String?
    private var globalTargetLanguage = "zh-CN"
    private var bookId = ""
    private var eventTask: Task<Void, Never>?
    private var detailTasks: [Int: Task<Void, Never>] = [:]
    private var summaryHydrateTasks: [Int: Task<Void, Never>] = [:]
    private var summaryParseTasks: [Int: Task<Void, Never>] = [:]
    private var sidebarPreviewTasks: [Int: Task<Void, Never>] = [:]
    private var chatTask: Task<Void, Never>?
    private var hydratingSummaryIndices: Set<Int> = []
    private var parsingSummaryIndices: Set<Int> = []
    private var parsedSummarySourceJSON: [Int: String] = [:]
    private var parsingSummaryJSON: [Int: String] = [:]
    private var summaryParseGeneration: [Int: Int] = [:]
    private var sourceCache: [Int: SegmentSourceBody] = [:]
    private var sourceCacheOrder: [Int] = []
    private var contentMode: ReaderContentMode = .summary
    private let summaryModeCacheLimit = 5
    private let originalModeCacheLimit = 12

    private var effectiveCacheLimit: Int {
        contentMode == .original ? originalModeCacheLimit : summaryModeCacheLimit
    }

    static let resegmentMinTargetChars = ResegmentTarget.minChars
    static let resegmentMaxTargetChars = ResegmentTarget.maxChars
    static let resegmentTargetRange = ResegmentTarget.range

    static func normalizedResegmentTarget(
        currentTarget: Int?,
        totalChars: Int?,
        segmentCount: Int
    ) -> Int {
        ResegmentTarget.normalized(
            currentTarget: currentTarget,
            totalChars: totalChars,
            segmentCount: segmentCount
        )
    }

    func setContentMode(_ mode: ReaderContentMode) {
        guard contentMode != mode else { return }
        contentMode = mode
        while sourceCacheOrder.count > effectiveCacheLimit {
            let evict = sourceCacheOrder.removeFirst()
            sourceCache.removeValue(forKey: evict)
        }
        sourceCacheVersion += 1
    }

    func prefetchSources(around idx: Int, core: CoreClient, radius: Int) {
        let sorted = segments.map(\.idx).sorted()
        guard let pos = sorted.firstIndex(of: idx) else { return }
        let start = max(0, pos - radius)
        let end = min(sorted.count - 1, pos + radius)
        for i in start...end {
            let segmentIdx = sorted[i]
            if sourceCache[segmentIdx] != nil { continue }
            if loadingSourceIndices.contains(segmentIdx) { continue }
            fetchSource(idx: segmentIdx, core: core)
        }
    }

    func needsTranslation(for textSample: String? = nil) -> Bool {
        BookLanguageMatcher.needsTranslation(
            bookLanguage: bookLanguage,
            bookTargetLanguage: bookTargetLanguage,
            globalTargetLanguage: globalTargetLanguage,
            textSample: textSample
        )
    }

    var canChatBook: Bool {
        bookSummariesComplete && indexStatus == "ready"
    }

    var bookChatPickerLabel: String {
        if canChatBook { return "全书" }
        guard bookSummariesComplete else { return "全书" }
        return indexStatus == "building" ? "全书（索引生成中）" : "全书（点此建索引）"
    }

    /// True when picking 全书 should kick off the on-demand index build.
    var needsBookIndexBuild: Bool {
        bookSummariesComplete && indexStatus != "ready" && indexStatus != "building"
    }

    var chatPlaceholder: String {
        chatScope == .book ? "问全书…" : "针对本段提问…"
    }

    func parsedSummary(for idx: Int) -> ParsedSummary? {
        parsedSummaryCache[idx]
    }

    func isSummaryLoading(for idx: Int) -> Bool {
        hydratingSummaryIndices.contains(idx) || parsingSummaryIndices.contains(idx)
    }

    func cancelAllTasks() {
        eventTask?.cancel()
        eventTask = nil
        restoreSettleTask?.cancel()
        restoreSettleTask = nil
        for task in detailTasks.values {
            task.cancel()
        }
        detailTasks.removeAll()
        for task in summaryHydrateTasks.values {
            task.cancel()
        }
        summaryHydrateTasks.removeAll()
        clearSummaryCache()
        cancelSidebarPreviewTasks()
        hydratingSummaryIndices.removeAll()
        chatTask?.cancel()
        chatTask = nil
        isSending = false
        loadingSourceIndices.removeAll()
        refreshingSourceIndices.removeAll()
    }

    func scheduleSidebarPreview(idx: Int, summaryJSON: String?) {
        guard let summaryJSON, !summaryJSON.isEmpty else {
            sidebarPreviewByIdx.removeValue(forKey: idx)
            sidebarPreviewTasks[idx]?.cancel()
            sidebarPreviewTasks.removeValue(forKey: idx)
            return
        }
        sidebarPreviewTasks[idx]?.cancel()
        sidebarPreviewTasks[idx] = Task.detached { [summaryJSON] in
            let preview = SegmentReadyEventParser.formatBulletsPreview(summaryJSON)
            guard !Task.isCancelled else { return }
            await MainActor.run { [weak self] in
                guard let self else { return }
                self.sidebarPreviewTasks.removeValue(forKey: idx)
                if let preview {
                    self.sidebarPreviewByIdx[idx] = preview
                } else {
                    self.sidebarPreviewByIdx.removeValue(forKey: idx)
                }
            }
        }
    }

    private func scheduleSidebarPreviews(for list: [SegmentRow]) {
        for seg in list where seg.summary_status == "ready" {
            if let json = seg.summary_json, !json.isEmpty {
                scheduleSidebarPreview(idx: seg.idx, summaryJSON: json)
            }
        }
    }

    private func cancelSidebarPreviewTasks() {
        for task in sidebarPreviewTasks.values {
            task.cancel()
        }
        sidebarPreviewTasks.removeAll()
    }

    /// `onResume` is called with the segment to open at, before the segments are
    /// published, so the feed's first layout already renders there and no
    /// scroll-restore retry loop is needed.
    func load(
        bookId: String,
        core: CoreClient,
        initialSegmentIndex: Int? = nil,
        onResume: (Int?) -> Void = { _ in }
    ) async {
        await flushProgressSave()
        cancelAllTasks()
        clearAllSourceCache()
        segments = []
        sidebarPreviewByIdx = [:]
        selectedIdx = nil
        checkedSegmentIndices = []
        isSegmentSelectionMode = false
        currentSegment = nil
        messages = []
        summaryReadyCount = 0
        summaryTotalCount = 0
        summarizeState = nil
        totalCharCount = nil
        chunkTargetChars = nil
        bookLanguage = nil
        bookTargetLanguage = nil
        bookTitle = nil
        globalTargetLanguage = "zh-CN"
        bookStatus = "unread"
        isResegmenting = false
        isResegmentCancelling = false
        isIngestCancelling = false
        indexStatus = "idle"
        bookSummariesComplete = false
        chatScope = .segment
        loadError = nil
        ingestProgress = nil
        progressPhase = .restoring
        restoreTarget = nil
        self.bookId = bookId
        ReadingProgressStore.shared.attach(core: core)
        do {
            try Task.checkCancellation()
            async let bookTask = core.fetchBook(id: bookId)
            async let settingsTask = core.fetchSettings()
            let book = try await bookTask
            let settings = try await settingsTask
            try Task.checkCancellation()
            bookStatus = book.status
            isResegmenting = book.processing_kind == "resegment"
            indexStatus = book.index_status ?? "idle"
            bookSummariesComplete = book.hasCompletedSummary
            if chatScope == .book, !canChatBook {
                chatScope = .segment
            }
            bookTitle = book.title
            globalTargetLanguage = settings.target_language
            eventTask = core.subscribeEvents(bookId: bookId) { [weak self] event in
                Task { @MainActor in
                    self?.handleEvent(event, core: core)
                }
            }
            guard book.status != "processing" else {
                progressPhase = .reading
                return
            }

            async let openTask = core.openBook(id: bookId)
            async let listTask = core.listSegments(bookId: bookId)
            let open = try await openTask
            try Task.checkCancellation()
            let list = try await listTask
            try Task.checkCancellation()

            let saved = ReadingProgressStore.shared.resumeIndex(
                bookId: bookId,
                serverIndex: open.current_segment_index,
                segmentCount: list.count
            )
            let idx = initialSegmentIndex
                ?? list.first(where: { $0.idx == saved })?.idx
                ?? list.first?.idx
            restoreTarget = idx
            // Pin before publishing the feed: the first layout lands on `idx`.
            onResume(idx)

            segments = list
            scheduleSidebarPreviews(for: list)
            warmSummaryCache(from: list)
            summaryReadyCount = book.summary_ready_count ?? list.filter { $0.summary_status == "ready" }.count
            summaryTotalCount = book.summary_total_count ?? list.count
            summarizeState = book.summarize_state
            totalCharCount = book.total_char_count
            chunkTargetChars = book.chunk_target_chars
            bookLanguage = book.language
            bookTargetLanguage = book.target_language
            if let idx {
                ReadingProgressStore.shared.hydrate(
                    bookId: bookId,
                    index: idx,
                    total: list.count
                )
                topSegmentSelection = idx
                selectedIdx = idx
                selectSegment(idx)
                prefetchSummaries(around: idx, core: core, radius: 3)
                scheduleReadingHandoff()
            } else {
                progressPhase = .reading
                selectedIdx = nil
            }
        } catch is CancellationError {
            progressPhase = .reading
            return
        } catch {
            progressPhase = .reading
            loadError = ConnectionError.userMessage(for: error, fallback: "加载失败，请重试。")
        }
    }

    func reload(
        core: CoreClient,
        initialSegmentIndex: Int? = nil,
        onResume: (Int?) -> Void = { _ in }
    ) async {
        await load(
            bookId: bookId,
            core: core,
            initialSegmentIndex: initialSegmentIndex,
            onResume: onResume
        )
    }

    /// Set when the pinned segment drives the selection, so the resulting
    /// `selectedIdx` change is not mistaken for a jump request.
    private var topSegmentSelection: Int?

    /// Hand the feed over from restoring to reading once it has settled on the
    /// resumed segment. Until then a stray pin from a still-materializing
    /// LazyVStack gets corrected rather than recorded.
    private func scheduleReadingHandoff() {
        restoreSettleTask?.cancel()
        restoreSettleTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 300_000_000)
            guard !Task.isCancelled, progressPhase == .restoring else { return }
            let target = restoreTarget
            progressPhase = .reading
            restoreTarget = nil
            if let target { noteTopSegment(target) }
        }
    }

    /// Record the segment pinned to the top of the viewport. This is the only
    /// place reading progress is written.
    func noteTopSegment(_ idx: Int) {
        guard progressPhase.recordsProgress else { return }
        guard !bookId.isEmpty, !segments.isEmpty else { return }
        ReadingProgressStore.shared.record(
            bookId: bookId,
            index: idx,
            total: segments.count
        )
        if selectedIdx != idx {
            topSegmentSelection = idx
            selectedIdx = idx
        }
    }

    /// True when this selection came from the pinned segment, so the reader
    /// must not scroll in response to it.
    func consumeTopSegmentSelection(_ idx: Int) -> Bool {
        if topSegmentSelection == idx {
            topSegmentSelection = nil
            return true
        }
        return false
    }

    func flushProgressSave() async {
        await ReadingProgressStore.shared.flush(bookId: bookId)
    }

    func prefetchSummaries(around idx: Int, core: CoreClient, radius: Int = 3) {
        let sorted = segments.map(\.idx).sorted()
        guard let pos = sorted.firstIndex(of: idx) else { return }
        let start = max(0, pos - radius)
        let end = min(sorted.count - 1, pos + radius)
        for i in start...end {
            hydrateSummary(idx: sorted[i], core: core)
        }
    }

    func hydrateSummary(idx: Int, core: CoreClient) {
        guard let seg = segments.first(where: { $0.idx == idx }) else { return }
        if let json = seg.summary_json, !json.isEmpty {
            ensureSummaryParsed(idx: idx, json: json)
        }
        guard needsSummaryHydration(seg) else { return }
        guard !hydratingSummaryIndices.contains(idx) else { return }

        summaryHydrateTasks[idx]?.cancel()
        hydratingSummaryIndices.insert(idx)
        let bookId = self.bookId

        summaryHydrateTasks[idx] = Task.detached { [bookId] in
            let detail = try? await core.fetchSegmentSummary(bookId: bookId, idx: idx)
            guard !Task.isCancelled else { return }
            await MainActor.run { [weak self] in
                guard let self else { return }
                self.summaryHydrateTasks.removeValue(forKey: idx)
                self.hydratingSummaryIndices.remove(idx)
                guard let detail else { return }
                self.mergeSummaryDetail(detail, at: idx)
            }
        }
    }

    private func needsSummaryHydration(_ seg: SegmentRow) -> Bool {
        seg.summary_status == "ready"
            && (seg.summary_json == nil || seg.summary_json?.isEmpty == true)
    }

    private func mergeSummaryDetail(_ detail: SegmentSummaryDetail, at idx: Int) {
        guard let i = segments.firstIndex(where: { $0.idx == idx }) else { return }
        var updated = segments[i]
        if let value = detail.summary_json, !value.isEmpty { updated.summary_json = value }
        if let value = detail.label { updated.label = value }
        if let value = detail.anchor_label { updated.anchor_label = value }
        if let value = detail.summary_provider { updated.summary_provider = value }
        if let value = detail.summary_model { updated.summary_model = value }
        if let value = detail.summary_tier { updated.summary_tier = value }
        if let value = detail.summary_duration_s { updated.summary_duration_s = value }
        if let value = detail.summary_llm_attempts { updated.summary_llm_attempts = value }
        if let status = detail.summary_status { updated.summary_status = status }
        segments[i] = updated
        syncCurrentSegment(from: updated)
        if let json = updated.summary_json, !json.isEmpty {
            ensureSummaryParsed(idx: idx, json: json)
        }
        scheduleSidebarPreview(idx: idx, summaryJSON: updated.summary_json)
    }

    private func clearSummaryCache() {
        for task in summaryParseTasks.values {
            task.cancel()
        }
        summaryParseTasks.removeAll()
        parsedSummaryCache = [:]
        parsedSummarySourceJSON.removeAll()
        parsingSummaryJSON.removeAll()
        parsingSummaryIndices.removeAll()
        summaryParseGeneration.removeAll()
    }

    private func invalidateParsedSummary(idx: Int) {
        summaryParseTasks[idx]?.cancel()
        summaryParseTasks.removeValue(forKey: idx)
        parsedSummaryCache.removeValue(forKey: idx)
        parsedSummarySourceJSON.removeValue(forKey: idx)
        parsingSummaryJSON.removeValue(forKey: idx)
        parsingSummaryIndices.remove(idx)
        summaryParseGeneration[idx] = (summaryParseGeneration[idx] ?? 0) + 1
    }

    private func ensureSummaryParsed(idx: Int, json: String) {
        scheduleSummaryParse(idx: idx, json: json)
    }

    private func nextSummaryParseGeneration(idx: Int) -> Int {
        let generation = (summaryParseGeneration[idx] ?? 0) + 1
        summaryParseGeneration[idx] = generation
        return generation
    }

    private func scheduleSummaryParse(idx: Int, json: String) {
        if parsedSummaryCache[idx] != nil, parsedSummarySourceJSON[idx] == json {
            return
        }
        if parsingSummaryJSON[idx] == json {
            return
        }

        summaryParseTasks[idx]?.cancel()
        let generation = nextSummaryParseGeneration(idx: idx)
        parsingSummaryIndices.insert(idx)
        parsingSummaryJSON[idx] = json
        summaryParseTasks[idx] = Task.detached { [weak self] in
            let parsed = ParsedSummary(json: json)
            guard !Task.isCancelled else { return }
            await MainActor.run { [weak self] in
                guard let self else { return }
                self.applyParsedSummary(
                    idx: idx,
                    json: json,
                    parsed: parsed,
                    generation: generation
                )
            }
        }
    }

    private func applyParsedSummary(
        idx: Int,
        json: String,
        parsed: ParsedSummary?,
        generation: Int
    ) {
        guard summaryParseGeneration[idx] == generation else { return }
        if parsingSummaryJSON[idx] == json {
            parsingSummaryJSON.removeValue(forKey: idx)
            summaryParseTasks.removeValue(forKey: idx)
        }
        parsingSummaryIndices.remove(idx)
        guard let parsed else { return }
        var cache = parsedSummaryCache
        cache[idx] = parsed
        parsedSummaryCache = cache
        parsedSummarySourceJSON[idx] = json
    }

    private func warmSummaryCache(from list: [SegmentRow]) {
        let items = list.compactMap { segment -> (idx: Int, json: String)? in
            guard let json = segment.summary_json, !json.isEmpty else { return nil }
            return (segment.idx, json)
        }
        guard !items.isEmpty else { return }

        var generations: [Int: Int] = [:]
        parsingSummaryIndices.formUnion(items.map(\.idx))
        for item in items {
            parsingSummaryJSON[item.idx] = item.json
            generations[item.idx] = nextSummaryParseGeneration(idx: item.idx)
        }
        Task.detached { [weak self] in
            let parsed = ParsedSummary.parseBatch(items)
            guard !Task.isCancelled else { return }
            await MainActor.run { [weak self] in
                guard let self else { return }
                for item in items {
                    self.applyParsedSummary(
                        idx: item.idx,
                        json: item.json,
                        parsed: parsed[item.idx],
                        generation: generations[item.idx] ?? 0
                    )
                }
            }
        }
    }

    /// Apply list meta only — never fetch or cache raw_text / translation in `segments[]`.
    func selectSegment(_ idx: Int) {
        if let meta = segments.first(where: { $0.idx == idx }) {
            currentSegment = meta
        }
    }

    func cachedSource(for idx: Int) -> SegmentSourceBody? {
        guard let body = sourceCache[idx] else { return nil }
        sourceCacheOrder.removeAll { $0 == idx }
        sourceCacheOrder.append(idx)
        return body
    }

    func isSourceLoading(idx: Int) -> Bool {
        loadingSourceIndices.contains(idx)
    }

    func isSourceRefreshing(idx: Int) -> Bool {
        refreshingSourceIndices.contains(idx)
    }

    private func clearAllSourceCache() {
        for task in detailTasks.values {
            task.cancel()
        }
        detailTasks.removeAll()
        sourceCache.removeAll()
        sourceCacheOrder.removeAll()
        loadingSourceIndices.removeAll()
        refreshingSourceIndices.removeAll()
        sourceCacheVersion += 1
    }

    private func storeSourceCache(_ body: SegmentSourceBody) {
        sourceCache[body.idx] = body
        sourceCacheOrder.removeAll { $0 == body.idx }
        sourceCacheOrder.append(body.idx)
        while sourceCacheOrder.count > effectiveCacheLimit {
            let evict = sourceCacheOrder.removeFirst()
            sourceCache.removeValue(forKey: evict)
        }
        sourceCacheVersion += 1
    }

    /// On-demand original text; results stay in per-segment cache (not `segments[]`).
    func fetchSource(idx: Int, core: CoreClient, force: Bool = false, translationOnly: Bool = false) {
        if !force, cachedSource(for: idx) != nil { return }

        detailTasks[idx]?.cancel()

        let existing = sourceCache[idx]
        let keepExistingRaw = existing != nil && !(existing?.rawText.isEmpty ?? true)

        if translationOnly && keepExistingRaw {
            refreshingSourceIndices.insert(idx)
        } else if force && keepExistingRaw {
            refreshingSourceIndices.insert(idx)
        } else {
            loadingSourceIndices.insert(idx)
        }

        let bookId = self.bookId
        detailTasks[idx] = Task.detached { [bookId] in
            let fresh = try? await core.getSegment(bookId: bookId, idx: idx)
            guard !Task.isCancelled else { return }
            await MainActor.run { [weak self] in
                guard let self else { return }
                self.detailTasks.removeValue(forKey: idx)
                self.loadingSourceIndices.remove(idx)
                self.refreshingSourceIndices.remove(idx)
                guard let fresh else { return }
                let rawText = fresh.raw_text ?? ""
                let translation = fresh.translation ?? ""
                let body: SegmentSourceBody
                if translationOnly, let existing, existing.idx == idx {
                    body = SegmentSourceBody(
                        idx: idx,
                        rawText: existing.rawText,
                        translation: translation
                    )
                } else {
                    body = SegmentSourceBody(idx: idx, rawText: rawText, translation: translation)
                }
                self.storeSourceCache(body)
            }
        }
    }

    func startSummarize(
        core: CoreClient, summaryTier: SummaryTier = .normal
    ) async throws {
        try await core.startSummarize(
            bookId: bookId, summaryTier: summaryTier
        )
        summarizeState = "queued"
        for seg in segments where seg.summary_status == "failed" || seg.summary_status == "error" {
            applySegmentStatus(idx: seg.idx, status: "pending")
        }
        NotificationCenter.default.post(name: .luminaLibraryRefresh, object: nil)
    }

    func stopSummarize(core: CoreClient) async throws {
        try await core.stopSummarize(bookId: bookId)
        markSummarizePaused()
        NotificationCenter.default.post(name: .luminaLibraryRefresh, object: nil)
    }

    func markSummarizePaused() {
        if summarizeState == "running" || summarizeState == "queued" {
            summarizeState = "paused"
        }
    }

    /// Whole-book index is built on demand only; nothing queues it in the background.
    func buildBookIndex(core: CoreClient) async {
        guard bookSummariesComplete, indexStatus != "building" else { return }
        indexStatus = "building"
        do {
            try await core.buildBookIndex(bookId: bookId)
        } catch {
            guard let message = error.userFacingMessage else { return }
            indexStatus = "error"
            chatStatus = "建全书索引失败：\(message)"
        }
    }

    func retrySegment(
        _ idx: Int,
        summaryTier: SummaryTier? = nil,
        core: CoreClient
    ) async throws {
        try await core.retrySegment(
            bookId: bookId,
            idx: idx,
            summaryTier: summaryTier
        )
        applySegmentStatus(idx: idx, status: "pending")
        summarizeState = "queued"
        NotificationCenter.default.post(name: .luminaLibraryRefresh, object: nil)
    }

    func clearChecks() {
        checkedSegmentIndices = []
    }

    func selectAllChecks() {
        checkedSegmentIndices = Set(segments.map(\.idx))
    }

    func toggleCheck(_ idx: Int) {
        if checkedSegmentIndices.contains(idx) {
            checkedSegmentIndices.remove(idx)
        } else {
            checkedSegmentIndices.insert(idx)
        }
    }

    func enterSegmentSelectionMode() {
        isSegmentSelectionMode = true
    }

    func exitSegmentSelectionMode() {
        isSegmentSelectionMode = false
        clearChecks()
    }

    func toggleSegmentSelectionMode() {
        if isSegmentSelectionMode {
            exitSegmentSelectionMode()
        } else {
            enterSegmentSelectionMode()
        }
    }

    func retryCheckedSegments(core: CoreClient) async throws {
        let indices = Array(checkedSegmentIndices).sorted()
        guard !indices.isEmpty else { return }
        try await core.retrySegments(bookId: bookId, indices: indices)
        for idx in indices {
            applySegmentStatus(idx: idx, status: "pending")
        }
        summarizeState = "queued"
        exitSegmentSelectionMode()
        NotificationCenter.default.post(name: .luminaLibraryRefresh, object: nil)
    }

    func regenerateAllSummaries(
        core: CoreClient, summaryTier: SummaryTier = .normal
    ) async throws {
        try await core.regenerateBookSummaries(
            bookId: bookId, summaryTier: summaryTier
        )
        for seg in segments {
            applySegmentStatus(idx: seg.idx, status: "pending")
        }
        summarizeState = "queued"
        bookSummariesComplete = false
        exitSegmentSelectionMode()
        NotificationCenter.default.post(name: .luminaLibraryRefresh, object: nil)
    }

    func resegmentBook(core: CoreClient, chunkTargetChars: Int) async throws {
        // Segment indices are about to change, so the recorded position is void.
        ReadingProgressStore.shared.forget(bookId: bookId)
        try await core.resegmentBook(
            bookId: bookId,
            chunkTargetChars: chunkTargetChars
        )
        bookStatus = "processing"
        isResegmenting = true
        isResegmentCancelling = false
        loadError = nil
        ingestProgress = IngestProgress(
            page: 0,
            total: 0,
            message: "正在重新分段…"
        )
        exitSegmentSelectionMode()
        NotificationCenter.default.post(name: .luminaLibraryRefresh, object: nil)
    }

    func applyBoundaryMove(
        result: SegmentBoundaryMoveResult,
        leftText: String,
        rightText: String
    ) {
        applyBoundarySide(
            idx: result.left_idx,
            charCount: result.left_char_count,
            anchor: result.left_anchor_label,
            chapter: result.left_chapter,
            status: result.left_status ?? "pending",
            rawText: leftText
        )
        applyBoundarySide(
            idx: result.right_idx,
            charCount: result.right_char_count,
            anchor: result.right_anchor_label,
            chapter: result.right_chapter,
            status: result.right_status ?? "pending",
            rawText: rightText
        )
    }

    private func applyBoundarySide(
        idx: Int,
        charCount: Int,
        anchor: String?,
        chapter: String?,
        status: String,
        rawText: String?
    ) {
        guard let i = segments.firstIndex(where: { $0.idx == idx }) else { return }
        var updated = segments[i]
        updated.summary_status = status
        updated.summary_json = nil
        updated.label = nil
        updated.translation = nil
        updated.char_count = charCount
        if let anchor { updated.anchor_label = anchor }
        updated.chapter = chapter
        segments[i] = updated
        syncCurrentSegment(from: updated)
        invalidateParsedSummary(idx: idx)
        segmentRunningMetrics.removeValue(forKey: idx)
        if let rawText {
            storeSourceCache(
                SegmentSourceBody(idx: idx, rawText: rawText, translation: "")
            )
        }
    }

    func cancelResegment(core: CoreClient) async throws {
        guard isResegmenting, !isResegmentCancelling else { return }
        isResegmentCancelling = true
        do {
            try await core.cancelResegmentBook(bookId: bookId)
            ingestProgress = IngestProgress(page: 0, total: 0, message: "正在取消重新分段…")
        } catch {
            isResegmentCancelling = false
            throw error
        }
    }

    func cancelIngest(core: CoreClient) async throws {
        guard bookStatus == "processing", !isResegmenting, !isIngestCancelling else { return }
        isIngestCancelling = true
        do {
            try await core.cancelIngestBook(bookId: bookId)
            ingestProgress = IngestProgress(page: 0, total: 0, message: "正在取消导入…")
        } catch {
            isIngestCancelling = false
            throw error
        }
    }

    func sendChat(_ text: String, quote: String? = nil, core: CoreClient) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isSending else { return }
        guard let idx = selectedIdx else { return }

        chatTask?.cancel()
        let task = Task { await performSendChat(trimmed, quote: quote, segmentIndex: idx, core: core) }
        chatTask = task
        await task.value
        if chatTask == task {
            chatTask = nil
        }
    }

    private func performSendChat(
        _ text: String,
        quote: String?,
        segmentIndex: Int,
        core: CoreClient
    ) async {
        isSending = true
        chatStatus = nil
        defer {
            isSending = false
            chatStatus = nil
        }

        messages.append(ChatMessage(role: "user", content: text))
        messages.append(ChatMessage(role: "assistant", content: ""))
        let assistantIndex = messages.count - 1

        do {
            let resp = try await core.chatStream(
                bookId: bookId,
                message: text,
                segmentIndex: segmentIndex,
                quote: quote,
                scope: chatScope.rawValue,
                onStatus: { status in
                    Task { @MainActor in
                        self.chatStatus = status
                    }
                }
            ) { token in
                Task { @MainActor in
                    guard assistantIndex < self.messages.count else { return }
                    self.messages[assistantIndex].content += token
                }
            }
            try Task.checkCancellation()
            guard assistantIndex < messages.count else { return }
            messages[assistantIndex].content = resp.answer
            messages[assistantIndex].citations = resp.citations
            messages[assistantIndex].applyMetrics(from: resp)
        } catch is CancellationError {
            if assistantIndex < messages.count, messages[assistantIndex].content.isEmpty {
                messages[assistantIndex].content = "已取消"
            }
        } catch let error as URLError where error.code == .cancelled {
            if assistantIndex < messages.count, messages[assistantIndex].content.isEmpty {
                messages[assistantIndex].content = "已取消"
            }
        } catch {
            guard assistantIndex < messages.count else { return }
            messages[assistantIndex].content = "深聊失败：\(error.localizedDescription)"
        }
    }

    func saveAsNote(_ content: String, core: CoreClient) async throws {
        guard let segmentId = currentSegment?.id else {
            throw NSError(
                domain: "Lumina",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "请先选择段落"]
            )
        }
        _ = try await core.createNote(
            bookId: bookId,
            content: content,
            segmentId: segmentId,
            type: "ai"
        )
    }

    var exportBookTitle: String {
        bookTitle ?? "summary"
    }

    func fetchExportMarkdown(core: CoreClient, includeNotes: Bool) async throws -> String {
        try await BookMarkdownExporter.fetchMarkdown(
            core: core,
            bookId: bookId,
            summaryReadyCount: summaryReadyCount,
            includeNotes: includeNotes
        )
    }

    func segmentProgressMessage(for idx: Int, at now: Date = Date()) -> String? {
        guard let segment = segments.first(where: { $0.idx == idx }) else { return nil }
        switch segment.summary_status {
        case "running":
            if let metrics = segmentRunningMetrics[idx] {
                return SummaryMetricsFormatter.inProgressLabel(
                    startedAt: metrics.startedAt,
                    llmAttempt: metrics.llmAttempt,
                    maxLlmAttempts: metrics.maxLlmAttempts,
                    now: now
                )
            }
            return "摘要生成中…"
        case "failed", "error":
            return SummaryMetricsFormatter.failureLabel(
                durationS: segment.summary_duration_s,
                retryCount: segment.retry_count
            )
        default:
            return nil
        }
    }

    func activeSummarizeLabel(at now: Date = Date()) -> String? {
        guard let running = segments.first(where: { $0.summary_status == "running" }) else { return nil }
        let idx = running.idx
        guard let metrics = segmentRunningMetrics[idx] else {
            return "段 \(idx + 1) · 摘要生成中…"
        }
        let elapsed = max(0, now.timeIntervalSince(metrics.startedAt))
        var parts = ["段 \(idx + 1)", SummaryMetricsFormatter.duration(seconds: elapsed)]
        parts.append(
            SummaryMetricsFormatter.attemptLabel(
                attempt: metrics.llmAttempt,
                maxAttempts: metrics.maxLlmAttempts
            )
        )
        return parts.joined(separator: " · ")
    }

    var summarizeActivityLabel: String? {
        ReaderSummaryProgressPolicy.activityLabel(
            running: ReaderSummaryProgressPolicy.runningCount(in: segments),
            queued: ReaderSummaryProgressPolicy.queuedCount(
                in: segments, summarizeState: summarizeState
            )
        )
    }

    private func applySegmentStatus(idx: Int, status: String, label: String? = nil, event: [String: Any]? = nil) {
        guard let i = segments.firstIndex(where: { $0.idx == idx }) else { return }
        var updated = segments[i]
        updated.summary_status = status
        if let label { updated.label = label }
        if let retry = event?["retry_count"] as? Int {
            updated.retry_count = retry
        }
        if let duration = event?["summary_duration_s"] as? Double {
            updated.summary_duration_s = duration
        } else if let duration = event?["summary_duration_s"] as? Int {
            updated.summary_duration_s = Double(duration)
        }
        segments[i] = updated
        syncCurrentSegment(from: updated)
        if status == "running" {
            let startedAt: Date
            if let startedAtStr = event?["started_at"] as? String,
               let parsed = SummaryMetricsFormatter.parseISO8601(startedAtStr) {
                startedAt = parsed
            } else {
                startedAt = Date()
            }
            segmentRunningMetrics[idx] = SegmentRunningMetrics(
                startedAt: startedAt,
                llmAttempt: 1,
                maxLlmAttempts: nil
            )
        } else if status == "ready" {
            segmentRunningMetrics.removeValue(forKey: idx)
        } else if status == "pending" {
            segmentRunningMetrics.removeValue(forKey: idx)
        } else if status == "failed" || status == "error" {
            segmentRunningMetrics.removeValue(forKey: idx)
        }
    }

    private func applySegmentReady(idx: Int, event: [String: Any]) {
        guard let i = segments.firstIndex(where: { $0.idx == idx }) else { return }
        var updated = segments[i]
        updated.summary_status = (event["summary_status"] as? String) ?? "ready"
        if let label = event["label"] as? String { updated.label = label }
        if let summaryJSON = SegmentReadyEventParser.extractSummaryJSON(from: event) {
            updated.summary_json = summaryJSON
        }
        if let anchor = (event["anchor_label"] as? String) ?? (event["anchor"] as? String) {
            updated.anchor_label = anchor
        }
        if let provider = event["summary_provider"] as? String { updated.summary_provider = provider }
        if let model = event["summary_model"] as? String { updated.summary_model = model }
        if let tier = event["summary_tier"] as? String { updated.summary_tier = tier }
        if let duration = event["summary_duration_s"] as? Double {
            updated.summary_duration_s = duration
        } else if let duration = event["summary_duration_s"] as? Int {
            updated.summary_duration_s = Double(duration)
        }
        if let attempts = event["summary_llm_attempts"] as? Int {
            updated.summary_llm_attempts = attempts
        }
        segments[i] = updated
        syncCurrentSegment(from: updated)
        segmentRunningMetrics.removeValue(forKey: idx)
        if let json = updated.summary_json, !json.isEmpty {
            ensureSummaryParsed(idx: idx, json: json)
        }
        scheduleSidebarPreview(idx: idx, summaryJSON: updated.summary_json)
    }

    private func syncCurrentSegment(from segment: SegmentRow) {
        guard selectedIdx == segment.idx else { return }
        currentSegment = segment
    }

    func handleEvent(_ event: [String: Any], core: CoreClient) {
        if let ready = event["summary_ready_count"] as? Int {
            summaryReadyCount = ready
        }
        if let total = event["summary_total_count"] as? Int {
            summaryTotalCount = total
        }
        if summaryTotalCount > 0 {
            bookSummariesComplete = summaryReadyCount >= summaryTotalCount
            if bookSummariesComplete {
                summarizeState = "summarized"
            }
            if !bookSummariesComplete, chatScope == .book {
                chatScope = .segment
            }
        }

        if let state = event["summarize_state"] as? String {
            summarizeState = state
        }

        let type = event["type"] as? String
        switch type {
        case "summarize_resumed":
            if summarizeState != "running" {
                summarizeState = "queued"
            }
        case "resegment_started":
            isResegmenting = true
            isResegmentCancelling = false
            if let target = event["chunk_target_chars"] as? Int {
                chunkTargetChars = target
            }
            ingestProgress = IngestProgress(page: 0, total: 0, message: "正在重新分段…")
        case "ingest_progress":
            let page = event["page"] as? Int ?? 0
            let total = event["total"] as? Int ?? 0
            let message = event["message"] as? String ?? ""
            ingestProgress = IngestProgress(page: page, total: total, message: message)
        case "ingest_complete":
            ingestProgress = nil
            isIngestCancelling = false
            let wasResegmented = event["resegmented"] as? Bool == true
            if wasResegmented {
                messages = []
                selectedIdx = 0
                isResegmenting = false
                isResegmentCancelling = false
                indexStatus = "idle"
                bookSummariesComplete = false
                chatScope = .segment
                NotificationCenter.default.post(name: .luminaLibraryRefresh, object: nil)
            }
            Task {
                await reload(
                    core: core,
                    initialSegmentIndex: wasResegmented ? 0 : selectedIdx
                )
            }
        case "ingest_failed":
            ingestProgress = nil
            isIngestCancelling = false
            bookStatus = "error"
            loadError = event["message"] as? String ?? "文档解析失败"
        case "ingest_cancelled":
            ingestProgress = nil
            isIngestCancelling = false
            bookStatus = "error"
            loadError = event["message"] as? String ?? "已取消导入"
            NotificationCenter.default.post(name: .luminaLibraryRefresh, object: nil)
        case "resegment_failed":
            ingestProgress = nil
            isResegmenting = false
            isResegmentCancelling = false
            bookStatus = event["status"] as? String ?? "reading"
            loadError = event["message"] as? String ?? "重新分段失败"
            NotificationCenter.default.post(name: .luminaLibraryRefresh, object: nil)
        case "resegment_cancelled":
            ingestProgress = nil
            isResegmenting = false
            isResegmentCancelling = false
            bookStatus = event["status"] as? String ?? "reading"
            loadError = nil
            NotificationCenter.default.post(name: .luminaLibraryRefresh, object: nil)
            Task { await reload(core: core, initialSegmentIndex: selectedIdx) }
        case "segment_status":
            guard let idx = SegmentReadyEventParser.eventIndex(from: event),
                  let status = event["status"] as? String else { return }
            applySegmentStatus(idx: idx, status: status, event: event)
            if status == "running" {
                summarizeState = "running"
            }
        case "segment_summarize_progress", "segment_summary_progress":
            guard let idx = SegmentReadyEventParser.eventIndex(from: event) else { return }
            var metrics = segmentRunningMetrics[idx] ?? SegmentRunningMetrics(
                startedAt: Date(),
                llmAttempt: 1,
                maxLlmAttempts: nil
            )
            if let attempt = event["llm_attempt"] as? Int {
                metrics.llmAttempt = attempt
            } else if let attempt = event["attempt"] as? Int {
                metrics.llmAttempt = attempt
            }
            if let maxAttempts = event["max_llm_attempts"] as? Int {
                metrics.maxLlmAttempts = maxAttempts
            } else if let maxAttempts = event["max_attempts"] as? Int {
                metrics.maxLlmAttempts = maxAttempts
            }
            segmentRunningMetrics[idx] = metrics
        case "segment_ready":
            guard let idx = SegmentReadyEventParser.eventIndex(from: event) else { return }
            applySegmentReady(idx: idx, event: event)
            if let seg = segments.first(where: { $0.idx == idx }), needsSummaryHydration(seg) {
                hydrateSummary(idx: idx, core: core)
            }
        case "segment_boundary_moved":
            let leftIdx = event["left_idx"] as? Int ?? SegmentReadyEventParser.eventIndex(from: event)
            guard let leftIdx else { return }
            let rightIdx = event["right_idx"] as? Int ?? leftIdx + 1
            applyBoundarySide(
                idx: leftIdx,
                charCount: event["left_char_count"] as? Int ?? 0,
                anchor: event["left_anchor_label"] as? String,
                chapter: event["left_chapter"] as? String,
                status: (event["left_status"] as? String) ?? "pending",
                rawText: nil
            )
            applyBoundarySide(
                idx: rightIdx,
                charCount: event["right_char_count"] as? Int ?? 0,
                anchor: event["right_anchor_label"] as? String,
                chapter: event["right_chapter"] as? String,
                status: (event["right_status"] as? String) ?? "pending",
                rawText: nil
            )
            fetchSource(idx: leftIdx, core: core, force: true)
            fetchSource(idx: rightIdx, core: core, force: true)
        case "book_index_ready", "book_index_progress":
            if let status = event["index_status"] as? String {
                indexStatus = status
                bookSummariesComplete = bookSummariesComplete || status == "ready"
                if chatScope == .book, !canChatBook {
                    chatScope = .segment
                }
            }
        case "translation_ready":
            guard let idx = SegmentReadyEventParser.eventIndex(from: event) else { return }
            if let translation = event["translation"] as? String {
                let rawText = sourceCache[idx]?.rawText ?? ""
                let body = SegmentSourceBody(idx: idx, rawText: rawText, translation: translation)
                storeSourceCache(body)
                refreshingSourceIndices.remove(idx)
            } else if loadingSourceIndices.contains(idx) || sourceCache[idx] != nil {
                fetchSource(idx: idx, core: core, force: true, translationOnly: true)
            }
        default:
            break
        }
    }
}
