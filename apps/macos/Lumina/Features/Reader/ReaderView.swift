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

struct ReaderView: View {
    let bookId: String
    var initialSegmentIndex: Int? = nil
    @Binding var segmentListPeeking: Bool
    @Binding var readerOverlayActive: Bool
    @Binding var readerChromeVisible: Bool
    @EnvironmentObject private var core: CoreClient

    @StateObject private var viewModel = ReaderViewModel()
    @AppStorage("lumina.reader.segmentListPinned") private var segmentListPinned = false

    init(
        bookId: String,
        initialSegmentIndex: Int? = nil,
        segmentListPeeking: Binding<Bool> = .constant(false),
        readerOverlayActive: Binding<Bool> = .constant(false),
        readerChromeVisible: Binding<Bool> = .constant(false)
    ) {
        self.bookId = bookId
        self.initialSegmentIndex = initialSegmentIndex
        _segmentListPeeking = segmentListPeeking
        _readerOverlayActive = readerOverlayActive
        _readerChromeVisible = readerChromeVisible
    }
    @State private var expandedSourceSegments: Set<Int> = []
    @State private var expandedSummarySegments: Set<Int> = []
    @State private var contentMode: ReaderContentMode = .summary
    @State private var scrollPosition: Int?
    @State private var suppressScrollSync = false
    @State private var suppressScrollSyncTask: Task<Void, Never>?
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
    @State private var readerSize: CGSize = .zero
    @State private var pendingEdge: ReaderEdgeTarget? = nil
    @State private var dwellTask: Task<Void, Never>? = nil
    @State private var chromeMode: ReaderChromeMode = .hidden
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
        chromeMode == .revealed || overlay != .none
    }

    private var segmentListOverlayVisible: Bool {
        segmentListPeeking && !segmentListPinned
    }

    private var segmentListInlineVisible: Bool {
        segmentListPinned && chromeVisible
    }

    private var segmentListAnyVisible: Bool {
        segmentListOverlayVisible || segmentListInlineVisible
    }

    private var shouldShowContentSummaryProgress: Bool {
        viewModel.summaryTotalCount > 0
            && viewModel.summaryReadyCount < viewModel.summaryTotalCount
            && !segmentListAnyVisible
    }

    var body: some View {
        readerLayout
            .toolbar {
                if toolbarVisible {
                    readerToolbar
                }
            }
            .background { readerModeShortcutButton }
            .confirmationDialog(
                "全书重新摘要",
                isPresented: $showRegenerateConfirm,
                titleVisibility: .visible
            ) {
                Button("重新生成全书摘要") {
                    Task {
                        do { try await viewModel.regenerateAllSummaries(core: core) }
                        catch { actionError = error.localizedDescription }
                    }
                }
                Button("取消", role: .cancel) {}
            } message: {
                Text("将重新生成全书 \(viewModel.segments.count) 个段的摘要，已有摘要将被覆盖。")
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
        ToolbarItemGroup {
            Button {
                toggleSegmentList()
            } label: {
                Label("段列表", systemImage: "list.bullet.rectangle")
                    .symbolVariant(segmentListAnyVisible ? .fill : .none)
                    .foregroundStyle(segmentListAnyVisible ? LuminaTheme.accent : .primary)
            }
            .help(segmentListAnyVisible ? "收起段列表" : "展开段列表")

            Picker("阅读模式", selection: $contentMode) {
                ForEach(ReaderContentMode.allCases, id: \.self) { mode in
                    Text(mode.label).tag(mode)
                }
            }
            .pickerStyle(.segmented)
            .frame(width: 120)
            .help("切换摘要 / 原文阅读模式（⌘⇧O）")

            Button("笔记") {
                setChromeMode(.revealed)
                openOverlay(.notes, engaged: true)
            }
            Button("提问") {
                setChromeMode(.revealed)
                openOverlay(.chat, engaged: true)
            }

            Button("开始摘要") {
                Task {
                    do { try await viewModel.startSummarize(core: core) }
                    catch { actionError = error.localizedDescription }
                }
            }
            Button("停止摘要") {
                Task {
                    do { try await viewModel.stopSummarize(core: core) }
                    catch { actionError = error.localizedDescription }
                }
            }
            Button("全书重新摘要") {
                showRegenerateConfirm = true
            }
            Button("导出") { showExport = true }
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
                segmentListPeeking = false
                setChromeMode(.revealed)
            } else {
                readerContentFocused = true
                setChromeMode(.revealed)
            }
        }
        .onChange(of: overlayEngaged) { _, engaged in
            if engaged, overlay == .chat { chatFocused = true }
        }
        .onChange(of: chromeMode) { _, mode in
            readerChromeVisible = mode != .hidden || overlay != .none
            beginSuppressScrollSync()
            updateSidebarTimer()
        }
        .onChange(of: segmentListPinned) { _, _ in
            beginSuppressScrollSync()
            updateSidebarTimer()
        }
        .onChange(of: segmentListPeeking) { _, _ in
            updateSidebarTimer()
        }
        .onAppear {
            readerOverlayActive = overlay != .none
            readerChromeVisible = toolbarVisible
            updateSidebarTimer()
        }
        .onChange(of: viewModel.selectedIdx) { _, idx in
            guard let idx else { return }
            viewModel.selectSegment(idx)
            viewModel.scheduleProgressSave(idx, core: core)
            guard !suppressScrollSync else { return }
            syncScrollToSelectedSegment(idx)
        }
        .onChange(of: scrollPosition) { _, idx in
            guard !suppressScrollSync, let idx else { return }
            if viewModel.selectedIdx != idx {
                viewModel.selectedIdx = idx
            }
            viewModel.prefetchSummaries(around: idx, core: core, radius: 3)
            if contentMode == .original {
                viewModel.prefetchSources(around: idx, core: core, radius: 3)
            }
        }
        .onChange(of: contentMode) { _, mode in
            ReaderPreferences.setContentMode(mode, for: bookId)
            viewModel.setContentMode(mode)
            if mode == .original {
                let idx = scrollPosition ?? viewModel.selectedIdx ?? viewModel.segments.first?.idx ?? 0
                viewModel.prefetchSources(around: idx, core: core, radius: 5)
            }
        }
        .task(id: bookId) {
            overlay = .none
            overlayEngaged = false
            segmentListPeeking = false
            chromeMode = .hidden
            readerChromeVisible = false
            expandedSourceSegments = []
            expandedSummarySegments = []
            contentMode = ReaderPreferences.contentMode(for: bookId)
            viewModel.setContentMode(contentMode)
            scrollPosition = nil
            await viewModel.load(bookId: bookId, core: core, initialSegmentIndex: initialSegmentIndex)
            scrollPosition = viewModel.selectedIdx
            readerContentFocused = true
            if contentMode == .original, let idx = viewModel.selectedIdx {
                viewModel.prefetchSources(around: idx, core: core, radius: 5)
            }
            if let idx = viewModel.selectedIdx {
                viewModel.prefetchSummaries(around: idx, core: core, radius: 5)
            }
        }
        .onDisappear {
            Task {
                await viewModel.flushProgressSave(core: core)
                viewModel.cancelAllTasks()
            }
        }
    }

    // MARK: - Content

    private var processingContent: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("正在解析文档…")
                .font(.headline)
            if let progress = viewModel.ingestProgress, progress.total > 0 {
                Text(progress.label)
                    .font(.caption)
                    .foregroundStyle(LuminaTheme.textSecondary)
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
            Text("解析完成后将自动开始分段与摘要。")
                .font(.caption)
                .foregroundStyle(LuminaTheme.textSecondary)
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
                Task { await viewModel.reload(core: core, initialSegmentIndex: initialSegmentIndex) }
            }
            .buttonStyle(.borderedProminent)
            .tint(LuminaTheme.accent)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(LuminaTheme.summaryPadding)
    }

    private var segmentContent: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: segmentFeedGap) {
                if let error = viewModel.loadError {
                    loadErrorContent(error)
                } else if viewModel.bookStatus == "processing" {
                    processingContent
                } else if viewModel.segments.isEmpty {
                    ProgressView()
                        .controlSize(.small)
                        .frame(maxWidth: .infinity)
                        .padding(LuminaTheme.summaryPadding)
                } else {
                    ForEach(Array(viewModel.segments.enumerated()), id: \.element.id) { index, seg in
                        segmentBlock(for: seg, at: index)
                    }
                }
            }
            .scrollTargetLayout()
            .readingColumn()
            .padding(.horizontal, LuminaTheme.summaryPadding)
            .padding(.vertical, LuminaTheme.summaryPadding)
        }
        .safeAreaInset(edge: .top, spacing: 0) {
            if shouldShowContentSummaryProgress {
                SummaryProgressBanner(
                    readyCount: viewModel.summaryReadyCount,
                    totalCount: viewModel.summaryTotalCount,
                    activeLabelProvider: viewModel.activeSummarizeLabel
                )
                .readingColumn()
                .padding(.horizontal, LuminaTheme.summaryPadding)
                .padding(.vertical, 8)
                .background(LuminaTheme.background)
            }
        }
        .background {
            ScrollViewKeyHandler(
                enabled: overlay == .none && !chatFocused && readerContentFocused
            )
            ChromeClickTracker(
                enabled: overlay == .none
            ) {
                toggleChromeOnBlankClick()
            }
        }
            .scrollPosition(id: $scrollPosition, anchor: .top)
        .animation(.easeOut(duration: 0.2), value: contentMode)
        .background(LuminaTheme.background)
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
        .onKeyPress(.upArrow) {
            guard readerContentFocused, overlay == .none, !chatFocused else { return .ignored }
            NotificationCenter.default.post(name: .luminaScrollContent, object: nil, userInfo: ["delta": -80.0])
            return .handled
        }
        .onKeyPress(.downArrow) {
            guard readerContentFocused, overlay == .none, !chatFocused else { return .ignored }
            NotificationCenter.default.post(name: .luminaScrollContent, object: nil, userInfo: ["delta": 80.0])
            return .handled
        }
        .onKeyPress(.pageUp) {
            guard readerContentFocused, overlay == .none, !chatFocused else { return .ignored }
            NotificationCenter.default.post(name: .luminaScrollContent, object: nil, userInfo: ["page": -1])
            return .handled
        }
        .onKeyPress(.pageDown) {
            guard readerContentFocused, overlay == .none, !chatFocused else { return .ignored }
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
    private func segmentBlock(for seg: SegmentRow, at index: Int) -> some View {
        let cachedSource = viewModel.cachedSource(for: seg.idx)
        let idx = seg.idx
        SegmentReadingBlock(
            contentMode: contentMode,
            segment: seg,
            segmentTotal: viewModel.segments.count,
            isLast: index == viewModel.segments.count - 1,
            isHighlighted: highlightSegment == idx,
            isSourceExpanded: contentMode == .original || expandedSourceSegments.contains(idx),
            isSummaryExpanded: expandedSummarySegments.contains(idx),
            sourceBody: cachedSource,
            isSourceLoading: viewModel.isSourceLoading(idx: idx),
            isSourceRefreshing: viewModel.isSourceRefreshing(idx: idx),
            needsTranslation: viewModel.needsTranslation(for: cachedSource?.rawText),
            summaryProgressMessage: viewModel.segmentProgressMessage(for: idx),
            runningMetrics: viewModel.segmentRunningMetrics[idx],
            onToggleSource: { toggleSource(for: idx) },
            onToggleSummary: { toggleSummary(for: idx) },
            onFollowUp: { question in
                openOverlay(.chat, engaged: true)
                Task { await viewModel.sendChat(question, core: core) }
            },
            onRetrySummary: {
                Task {
                    do { try await viewModel.retrySegment(idx, core: core) }
                    catch { actionError = error.localizedDescription }
                }
            },
            onSendToChat: { quote in
                viewModel.selectedIdx = idx
                openOverlay(.chat, engaged: true)
                Task {
                    await viewModel.sendChat("请解释以下内容", quote: quote, core: core)
                }
            },
            onSourceAppear: contentMode == .original
                ? { viewModel.fetchSource(idx: idx, core: core) }
                : nil
        )
        .id(idx)
        .onAppear {
            viewModel.hydrateSummary(idx: idx, core: core)
        }
    }

    private func syncScrollToSelectedSegment(_ idx: Int, force: Bool = false) {
        guard force || scrollPosition != idx else { return }
        suppressScrollSync = true
        if force, scrollPosition == idx {
            scrollPosition = nil
        }
        withAnimation(.easeInOut(duration: segmentSwitchDuration)) {
            scrollPosition = idx
        }
        Task {
            try? await Task.sleep(nanoseconds: 150_000_000)
            suppressScrollSync = false
        }
    }

    private func navigateSegment(delta: Int) {
        guard overlay == .none, !chatFocused else { return }
        let current = viewModel.selectedIdx ?? scrollPosition
        guard let current else { return }
        let sorted = viewModel.segments.map(\.idx).sorted()
        guard let pos = sorted.firstIndex(of: current) else { return }
        let newPos = pos + delta
        guard newPos >= 0, newPos < sorted.count else { return }
        viewModel.selectedIdx = sorted[newPos]
        readerContentFocused = true
    }

    private func navigateToSegment(_ idx: Int) {
        viewModel.selectedIdx = idx
        readerContentFocused = true
    }

    private func selectSidebarSegment(_ idx: Int) {
        if viewModel.selectedIdx == idx {
            syncScrollToSelectedSegment(idx, force: true)
        } else {
            viewModel.selectedIdx = idx
        }
    }

    // MARK: - Sidebar & drawers

    private var readerEdgeIconsOverlay: some View {
        ZStack {
            HStack(spacing: 0) {
                ReaderEdgeIcon(
                    systemImage: "list.bullet.rectangle",
                    label: "段列表",
                    isActive: segmentListAnyVisible
                ) {
                    toggleSegmentList()
                }
                .padding(.leading, 6)
                Spacer(minLength: 0)
                ReaderEdgeIcon(
                    systemImage: "note.text",
                    label: "笔记",
                    isActive: overlay == .notes
                ) {
                    setChromeMode(.revealed)
                    openOverlay(.notes, engaged: true)
                }
                .padding(.trailing, 6)
            }
            .frame(maxHeight: .infinity)

            VStack(spacing: 0) {
                Spacer(minLength: 0)
                ReaderEdgeIcon(
                    systemImage: "bubble.left.and.bubble.right",
                    label: "深聊",
                    isActive: overlay == .chat
                ) {
                    setChromeMode(.revealed)
                    openOverlay(.chat, engaged: true)
                }
                .padding(.bottom, 8)
            }
        }
        .allowsHitTesting(true)
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
                    activeLabelProvider: viewModel.activeSummarizeLabel,
                    hideWhenComplete: false
                )

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
                    segmentListPinned = true
                    segmentListPeeking = false
                    setChromeMode(.revealed)
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
                segmentListPinned = false
                segmentListPeeking = false
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
                LazyVStack(spacing: 0) {
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

    private func updateSidebarTimer() {
        viewModel.setSidebarVisible(segmentListAnyVisible)
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
                bulletsPreview: viewModel.sidebarPreviewByIdx[seg.idx],
                statusClock: viewModel.sidebarClock
            )
        }
        .contentShape(Rectangle())
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(
            viewModel.selectedIdx == seg.idx
                ? LuminaTheme.accentMuted.opacity(0.45)
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

            ScrollView {
                LazyVStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(viewModel.messages.enumerated()), id: \.element.id) { _, msg in
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text(msg.role == "user" ? "你" : "深聊")
                                    .font(.caption.bold())
                                Spacer()
                                if msg.role == "assistant", !msg.content.isEmpty {
                                    Button("存为笔记") {
                                        Task { await saveChatAsNote(msg.content) }
                                    }
                                    .font(.caption)
                                }
                            }
                            Text(msg.content)
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
                        }
                        .padding(8)
                        .background(msg.role == "user" ? Color.blue.opacity(0.08) : Color.gray.opacity(0.08))
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                    }
                }
                .padding(.horizontal)
            }

            HStack {
                TextField("提问…", text: $chatInput)
                    .textFieldStyle(.roundedBorder)
                    .focused($chatFocused)
                    .onChange(of: chatInput) { _, newValue in
                        if !newValue.isEmpty { overlayEngaged = true }
                    }
                Button("发送") {
                    let text = chatInput
                    chatInput = ""
                    Task { await viewModel.sendChat(text, core: core) }
                }
                .disabled(chatInput.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            .padding(.horizontal)
            .padding(.bottom, 8)
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
                    segmentListPeeking = false
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
            withAnimation(.easeInOut(duration: 0.25)) {
                switch target {
                case .segments:
                    if segmentListPinned {
                        setChromeMode(.revealed)
                    } else {
                        segmentListPeeking = true
                    }
                case .notes:
                    overlayEngaged = false
                    overlay = .notes
                case .chat:
                    overlayEngaged = false
                    overlay = .chat
                }
            }
        }
    }

    private func isPointerInSegmentList(_ point: CGPoint, size: CGSize) -> Bool {
        guard point.y > topEdgeExclusionZone else { return false }
        return point.x <= segmentsWidth
    }

    private func isPointerInLeftEdge(_ point: CGPoint) -> Bool {
        point.x <= edgeHotZone && point.y > topEdgeExclusionZone
    }

    private func beginSuppressScrollSync() {
        suppressScrollSync = true
        suppressScrollSyncTask?.cancel()
        suppressScrollSyncTask = Task {
            try? await Task.sleep(nanoseconds: 350_000_000)
            guard !Task.isCancelled else { return }
            suppressScrollSync = false
        }
    }

    private func setChromeMode(_ mode: ReaderChromeMode) {
        guard chromeMode != mode else { return }
        withAnimation(.easeInOut(duration: 0.25)) {
            chromeMode = mode
        }
    }

    private func collapseAllChrome() {
        chromeMode = .hidden
        segmentListPeeking = false
        overlay = .none
        overlayEngaged = false
    }

    private func toggleChromeOnBlankClick() {
        guard overlay == .none else { return }
        withAnimation(.easeInOut(duration: 0.25)) {
            if segmentListOverlayVisible {
                segmentListPeeking = false
            } else if chromeMode != .hidden {
                collapseAllChrome()
            } else {
                setChromeMode(.revealed)
            }
        }
    }

    private func toggleSegmentList() {
        guard overlay == .none else { return }
        withAnimation(.easeInOut(duration: 0.25)) {
            if segmentListAnyVisible {
                segmentListPinned = false
                segmentListPeeking = false
            } else {
                segmentListPeeking = true
            }
        }
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
        withAnimation(.easeInOut(duration: 0.25)) {
            setChromeMode(.revealed)
            overlayEngaged = engaged
            overlay = kind
        }
    }

    private func saveChatAsNote(_ content: String) async {
        do {
            try await viewModel.saveAsNote(content, core: core)
            notesRefreshToken += 1
        } catch {
            noteError = error.localizedDescription
        }
    }

    @ViewBuilder
    private func statusIcon(for seg: SegmentRow) -> some View {
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
}

struct SegmentSidebarRow: View {
    let segment: SegmentRow
    var runningMetrics: SegmentRunningMetrics?
    var bulletsPreview: String?
    var statusClock: Date

    private var chapterTitle: String {
        if let ch = segment.chapter, !ch.isEmpty { return ch }
        return "段 \(segment.idx + 1)"
    }

    private var outlineLabel: String? {
        if let label = segment.label, !label.isEmpty { return label }
        switch segment.summary_status {
        case "running", "pending":
            return statusCaption(at: statusClock)
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
            if let outline = outlineLabel {
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

/// Detects left-clicks on non-interactive reading areas to toggle chrome visibility.
private struct ChromeClickTracker: NSViewRepresentable {
    var enabled: Bool
    var onBlankClick: () -> Void

    func makeNSView(context: Context) -> ChromeClickNSView {
        let view = ChromeClickNSView()
        view.onBlankClick = onBlankClick
        view.isTrackingEnabled = enabled
        return view
    }

    func updateNSView(_ nsView: ChromeClickNSView, context: Context) {
        nsView.onBlankClick = onBlankClick
        nsView.isTrackingEnabled = enabled
    }
}

private final class ChromeClickNSView: NSView {
    var onBlankClick: (() -> Void)?
    var isTrackingEnabled = true
    private var monitor: Any?

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        removeMonitor()
        guard window != nil else { return }
        monitor = NSEvent.addLocalMonitorForEvents(matching: .leftMouseDown) { [weak self] event in
            guard let self, self.isTrackingEnabled, event.window == self.window else { return event }
            let windowPoint = event.locationInWindow
            let localPoint = self.convert(windowPoint, from: nil)
            guard self.bounds.contains(localPoint) else { return event }
            let hitView = self.window?.contentView?.hitTest(windowPoint)
            if Self.isInteractive(hitView) { return event }
            self.onBlankClick?()
            return event
        }
    }

    deinit {
        removeMonitor()
    }

    private func removeMonitor() {
        if let monitor {
            NSEvent.removeMonitor(monitor)
            self.monitor = nil
        }
    }

    private static func isInteractive(_ view: NSView?) -> Bool {
        var current = view
        while let v = current {
            if v is NSControl { return true }
            if v is NSTextView { return true }
            current = v.superview
        }
        return false
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

private final class ScrollViewKeyNSView: NSView {
    var isEnabled = true
    private var observer: NSObjectProtocol?

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
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
    }

    private func handleScroll(_ note: Notification) {
        guard isEnabled, let scrollView = enclosingScrollView else { return }
        let clipView = scrollView.contentView
        var origin = clipView.bounds.origin

        if let delta = note.userInfo?["delta"] as? CGFloat {
            origin.y += delta
        } else if let page = note.userInfo?["page"] as? Int {
            let pageHeight = max(clipView.bounds.height * 0.9, 120)
            origin.y += CGFloat(page) * pageHeight
        } else {
            return
        }

        let docHeight = scrollView.documentView?.bounds.height ?? 0
        let maxY = max(0, docHeight - clipView.bounds.height)
        origin.y = min(max(0, origin.y), maxY)
        clipView.setBoundsOrigin(origin)
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
    @Published var summaryReadyCount = 0
    @Published var summaryTotalCount = 0
    @Published var segmentRunningMetrics: [Int: SegmentRunningMetrics] = [:]
    @Published var sidebarPreviewByIdx: [Int: String] = [:]
    @Published var sidebarClock = Date()
    @Published var totalCharCount: Int?
    @Published private(set) var bookStatus = "unread"
    @Published var loadError: String?
    @Published var ingestProgress: IngestProgress?
    private var bookLanguage: String?
    private var bookTargetLanguage: String?
    private var bookTitle: String?
    private var globalTargetLanguage = "zh-CN"
    private var bookId = ""
    private var eventTask: Task<Void, Never>?
    private var detailTasks: [Int: Task<Void, Never>] = [:]
    private var summaryHydrateTasks: [Int: Task<Void, Never>] = [:]
    private var sidebarPreviewTasks: [Int: Task<Void, Never>] = [:]
    private var sidebarClockTask: Task<Void, Never>?
    private var hydratingSummaryIndices: Set<Int> = []
    private var progressSaveTask: Task<Void, Never>?
    private var pendingProgressIdx: Int?
    private var suppressProgressSave = false
    private var sourceCache: [Int: SegmentSourceBody] = [:]
    private var sourceCacheOrder: [Int] = []
    private var contentMode: ReaderContentMode = .summary
    private let summaryModeCacheLimit = 5
    private let originalModeCacheLimit = 12

    private var effectiveCacheLimit: Int {
        contentMode == .original ? originalModeCacheLimit : summaryModeCacheLimit
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

    func cancelAllTasks() {
        eventTask?.cancel()
        eventTask = nil
        for task in detailTasks.values {
            task.cancel()
        }
        detailTasks.removeAll()
        for task in summaryHydrateTasks.values {
            task.cancel()
        }
        summaryHydrateTasks.removeAll()
        cancelSidebarPreviewTasks()
        setSidebarVisible(false)
        hydratingSummaryIndices.removeAll()
        progressSaveTask?.cancel()
        progressSaveTask = nil
        loadingSourceIndices.removeAll()
        refreshingSourceIndices.removeAll()
    }

    func setSidebarVisible(_ visible: Bool) {
        sidebarClockTask?.cancel()
        sidebarClockTask = nil
        guard visible else { return }
        sidebarClock = Date()
        sidebarClockTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                guard !Task.isCancelled, let self else { return }
                self.sidebarClock = Date()
            }
        }
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

    func load(bookId: String, core: CoreClient, initialSegmentIndex: Int? = nil) async {
        await flushProgressSave(core: core)
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
        totalCharCount = nil
        bookLanguage = nil
        bookTargetLanguage = nil
        bookTitle = nil
        globalTargetLanguage = "zh-CN"
        pendingProgressIdx = nil
        bookStatus = "unread"
        loadError = nil
        ingestProgress = nil
        self.bookId = bookId
        do {
            try Task.checkCancellation()
            async let bookTask = core.fetchBook(id: bookId)
            async let settingsTask = core.fetchSettings()
            let book = try await bookTask
            let settings = try await settingsTask
            try Task.checkCancellation()
            bookStatus = book.status
            bookTitle = book.title
            globalTargetLanguage = settings.target_language
            eventTask = core.subscribeEvents(bookId: bookId) { [weak self] event in
                Task { @MainActor in
                    self?.handleEvent(event, core: core)
                }
            }
            guard book.status != "processing" else { return }

            async let openTask = core.openBook(id: bookId)
            async let listTask = core.listSegments(bookId: bookId)
            let open = try await openTask
            try Task.checkCancellation()
            let list = try await listTask
            try Task.checkCancellation()
            segments = list
            scheduleSidebarPreviews(for: list)
            summaryReadyCount = book.summary_ready_count ?? list.filter { $0.summary_status == "ready" }.count
            summaryTotalCount = book.summary_total_count ?? list.count
            totalCharCount = book.total_char_count
            bookLanguage = book.language
            bookTargetLanguage = book.target_language
            let saved = open.current_segment_index
            let idx = initialSegmentIndex
                ?? segments.first(where: { $0.idx == saved })?.idx
                ?? segments.first?.idx
            suppressProgressSave = true
            selectedIdx = idx
            if let idx {
                selectSegment(idx)
                prefetchSummaries(around: idx, core: core, radius: 3)
            }
            suppressProgressSave = false
        } catch is CancellationError {
            return
        } catch {
            loadError = ConnectionError.userMessage(for: error, fallback: "加载失败，请重试。")
        }
    }

    func reload(core: CoreClient, initialSegmentIndex: Int? = nil) async {
        await load(bookId: bookId, core: core, initialSegmentIndex: initialSegmentIndex)
    }

    func scheduleProgressSave(_ idx: Int, core: CoreClient) {
        guard !suppressProgressSave, !bookId.isEmpty else { return }
        pendingProgressIdx = idx
        progressSaveTask?.cancel()
        progressSaveTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 300_000_000)
            guard !Task.isCancelled, let self else { return }
            await self.flushProgressSave(core: core)
        }
    }

    func flushProgressSave(core: CoreClient) async {
        progressSaveTask?.cancel()
        progressSaveTask = nil
        guard let idx = pendingProgressIdx ?? selectedIdx, !bookId.isEmpty else { return }
        pendingProgressIdx = nil
        let bookId = self.bookId
        try? await core.saveReadingProgress(bookId: bookId, segmentIndex: idx)
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
        guard needsSummaryHydration(seg) else { return }
        guard !hydratingSummaryIndices.contains(idx) else { return }

        summaryHydrateTasks[idx]?.cancel()
        hydratingSummaryIndices.insert(idx)
        let bookId = self.bookId

        summaryHydrateTasks[idx] = Task.detached { [bookId] in
            let detail = try? await core.getSegment(bookId: bookId, idx: idx)
            guard !Task.isCancelled else { return }
            await MainActor.run { [weak self] in
                guard let self else { return }
                self.summaryHydrateTasks.removeValue(forKey: idx)
                self.hydratingSummaryIndices.remove(idx)
                guard let detail else { return }
                self.mergeSegmentDetail(detail, at: idx)
            }
        }
    }

    private func needsSummaryHydration(_ seg: SegmentRow) -> Bool {
        seg.summary_status == "ready"
            && (seg.summary_json == nil || seg.summary_json?.isEmpty == true)
    }

    private func mergeSegmentDetail(_ detail: SegmentRow, at idx: Int) {
        guard let i = segments.firstIndex(where: { $0.idx == idx }) else { return }
        var updated = segments[i]
        if let value = detail.summary_json, !value.isEmpty { updated.summary_json = value }
        if let value = detail.label { updated.label = value }
        if let value = detail.anchor_label { updated.anchor_label = value }
        if let value = detail.summary_provider { updated.summary_provider = value }
        if let value = detail.summary_model { updated.summary_model = value }
        if let value = detail.summary_duration_s { updated.summary_duration_s = value }
        if let value = detail.summary_llm_attempts { updated.summary_llm_attempts = value }
        updated.summary_status = detail.summary_status
        segments[i] = updated
        syncCurrentSegment(from: updated)
        scheduleSidebarPreview(idx: idx, summaryJSON: updated.summary_json)
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

    func startSummarize(core: CoreClient) async throws {
        try await core.startSummarize(bookId: bookId)
        for seg in segments where seg.summary_status == "failed" || seg.summary_status == "error" {
            applySegmentStatus(idx: seg.idx, status: "pending")
        }
    }

    func stopSummarize(core: CoreClient) async throws {
        try await core.stopSummarize(bookId: bookId)
    }

    func retrySegment(_ idx: Int, core: CoreClient) async throws {
        try await core.retrySegment(bookId: bookId, idx: idx)
        applySegmentStatus(idx: idx, status: "pending")
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
        exitSegmentSelectionMode()
    }

    func regenerateAllSummaries(core: CoreClient) async throws {
        try await core.regenerateBookSummaries(bookId: bookId)
        for seg in segments {
            applySegmentStatus(idx: seg.idx, status: "pending")
        }
        exitSegmentSelectionMode()
    }

    func sendChat(_ text: String, quote: String? = nil, core: CoreClient) async {
        messages.append(ChatMessage(role: "user", content: text))
        guard let idx = selectedIdx else { return }

        var assistant = ChatMessage(role: "assistant", content: "")
        messages.append(assistant)
        let assistantIndex = messages.count - 1

        do {
            let resp = try await core.chatStream(
                bookId: bookId,
                message: text,
                segmentIndex: idx,
                quote: quote
            ) { token in
                Task { @MainActor in
                    self.messages[assistantIndex].content += token
                }
            }
            messages[assistantIndex].content = resp.answer
            messages[assistantIndex].citations = resp.citations
        } catch {
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
        case "pending", "running":
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
        scheduleSidebarPreview(idx: idx, summaryJSON: updated.summary_json)
    }

    private func syncCurrentSegment(from segment: SegmentRow) {
        guard selectedIdx == segment.idx else { return }
        currentSegment = segment
    }

    private func handleEvent(_ event: [String: Any], core: CoreClient) {
        if let ready = event["summary_ready_count"] as? Int {
            summaryReadyCount = ready
        }
        if let total = event["summary_total_count"] as? Int {
            summaryTotalCount = total
        }

        let type = event["type"] as? String
        switch type {
        case "ingest_progress":
            let page = event["page"] as? Int ?? 0
            let total = event["total"] as? Int ?? 0
            let message = event["message"] as? String ?? ""
            ingestProgress = IngestProgress(page: page, total: total, message: message)
        case "ingest_complete":
            ingestProgress = nil
            Task { await reload(core: core, initialSegmentIndex: selectedIdx) }
        case "ingest_failed":
            ingestProgress = nil
            bookStatus = "error"
            loadError = event["message"] as? String ?? "文档解析失败"
        case "segment_status":
            guard let idx = SegmentReadyEventParser.eventIndex(from: event),
                  let status = event["status"] as? String else { return }
            applySegmentStatus(idx: idx, status: status, event: event)
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
