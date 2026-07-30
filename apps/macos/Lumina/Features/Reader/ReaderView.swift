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
    @State private var exportSuccessURL: URL?
    @State private var pendingExport: PendingBookExport?
    @State private var showExportCancelled = false
    @State private var notesRefreshToken = 0
    @State private var noteError: String?
    @State private var actionError: String?
    @State private var showRegenerateConfirm = false
    @State private var readerSize: CGSize = .zero
    @State private var pendingEdge: ReaderEdgeTarget? = nil
    @State private var dwellTask: Task<Void, Never>? = nil
    @State private var userScrollingFeed = false
    @State private var scrollSelectionDebounceTask: Task<Void, Never>?
    @State private var prefetchDebounceTask: Task<Void, Never>?
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
            .sheet(isPresented: $showExport) {
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
                        pendingExport = PendingBookExport(
                            markdown: markdown,
                            bookTitle: viewModel.exportBookTitle
                        )
                    },
                    onError: { actionError = $0 }
                )
            }
            .onChange(of: showExport) { _, isShowing in
                guard !isShowing else { return }
                guard let pending = pendingExport else { return }
                pendingExport = nil
                Task { await finishExportSave(pending) }
            }
            .alert("导出成功", isPresented: exportSuccessPresented) {
                Button("在 Finder 中显示") {
                    if let url = exportSuccessURL {
                        NSWorkspace.shared.activateFileViewerSelecting([url])
                    }
                }
                Button("好", role: .cancel) {
                    exportSuccessURL = nil
                }
            } message: {
                if let url = exportSuccessURL {
                    Text("已保存至\n\(url.path)")
                }
            }
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
            .alert("已取消保存", isPresented: $showExportCancelled) {
                Button("好", role: .cancel) {}
            }
    }

    @MainActor
    private func finishExportSave(_ pending: PendingBookExport) async {
        try? await Task.sleep(nanoseconds: 150_000_000)
        do {
            switch try await BookMarkdownExporter.presentSavePanel(
                markdown: pending.markdown,
                bookTitle: pending.bookTitle
            ) {
            case .saved(let url):
                exportSuccessURL = url
            case .cancelled:
                showExportCancelled = true
            }
        } catch {
            actionError = error.localizedDescription
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

    private var exportSuccessPresented: Binding<Bool> {
        Binding(
            get: { exportSuccessURL != nil },
            set: { if !$0 { exportSuccessURL = nil } }
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
        }
        .onChange(of: segmentListPinned) { _, _ in
            beginSuppressScrollSync()
        }
        .onAppear {
            readerOverlayActive = overlay != .none
            readerChromeVisible = toolbarVisible
        }
        .onChange(of: viewModel.selectedIdx) { _, idx in
            guard let idx else { return }
            viewModel.selectSegment(idx)
            viewModel.scheduleProgressSave(idx, core: core)
            if contentMode == .summary {
                viewModel.prefetchSummaries(around: idx, core: core)
            }
            guard !suppressScrollSync, !userScrollingFeed else { return }
            Task { @MainActor in
                await Task.yield()
                syncScrollToSelectedSegment(idx)
            }
        }
        .onChange(of: scrollPosition) { _, idx in
            guard !suppressScrollSync, let idx else { return }
            userScrollingFeed = true
            scrollSelectionDebounceTask?.cancel()
            scrollSelectionDebounceTask = Task { @MainActor in
                try? await Task.sleep(nanoseconds: 120_000_000)
                guard !Task.isCancelled else { return }
                userScrollingFeed = false
                if viewModel.selectedIdx != idx {
                    viewModel.selectedIdx = idx
                }
            }
            prefetchDebounceTask?.cancel()
            prefetchDebounceTask = Task { @MainActor in
                try? await Task.sleep(nanoseconds: 150_000_000)
                guard !Task.isCancelled else { return }
                if contentMode == .original {
                    viewModel.prefetchSources(around: idx, core: core, radius: 3)
                } else {
                    viewModel.prefetchSummaries(around: idx, core: core)
                }
            }
        }
        .onChange(of: contentMode) { _, mode in
            ReaderPreferences.setContentMode(mode, for: bookId)
            viewModel.setContentMode(mode)
            let idx = scrollPosition ?? viewModel.selectedIdx ?? viewModel.segments.first?.idx ?? 0
            if mode == .original {
                viewModel.prefetchSources(around: idx, core: core, radius: 5)
            } else {
                viewModel.prefetchSummaries(around: idx, core: core)
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
            if let idx = viewModel.selectedIdx {
                if contentMode == .original {
                    viewModel.prefetchSources(around: idx, core: core, radius: 5)
                } else {
                    viewModel.prefetchSummaries(around: idx, core: core)
                }
            }
        }
        .onDisappear {
            scrollSelectionDebounceTask?.cancel()
            prefetchDebounceTask?.cancel()
            viewModel.flushProgressSave(core: core)
            viewModel.cancelAllTasks()
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
                    ForEach(viewModel.segments) { seg in
                        segmentBlock(for: seg)
                            .id(seg.idx)
                    }
                }
            }
            .scrollTargetLayout()
            .readingColumn()
            .padding(.horizontal, LuminaTheme.summaryPadding)
            .padding(.vertical, LuminaTheme.summaryPadding)
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

    @ViewBuilder
    private func segmentBlock(for seg: SegmentRow) -> some View {
        let sourceBody = viewModel.source(for: seg.idx)
        let idx = seg.idx
        SegmentReadingBlock(
            contentMode: contentMode,
            segment: seg,
            segmentTotal: viewModel.segments.count,
            isLast: viewModel.arrayIndex(forSegmentIdx: idx).map { $0 == viewModel.segments.count - 1 } ?? false,
            isHighlighted: highlightSegment == idx,
            isSourceExpanded: contentMode == .original || expandedSourceSegments.contains(idx),
            isSummaryExpanded: expandedSummarySegments.contains(idx),
            sourceBody: sourceBody,
            isSourceLoading: viewModel.isSourceLoading(idx: idx),
            isSourceRefreshing: viewModel.isSourceRefreshing(idx: idx),
            needsTranslation: viewModel.needsTranslation(for: sourceBody?.rawText),
            parsedSummary: viewModel.parsedSummary(for: idx),
            isSummaryLoading: viewModel.isSummaryLoading(idx: idx),
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
            onSourceAppear: contentMode == .original
                ? { viewModel.fetchSource(idx: idx, core: core) }
                : nil,
            onSummaryAppear: contentMode == .summary
                ? { viewModel.ensureSummaryLoaded(idx: idx, core: core) }
                : nil
        )
        .equatable()
    }

    private func syncScrollToSelectedSegment(_ idx: Int, force: Bool = false) {
        guard force || scrollPosition != idx else { return }
        suppressScrollSync = true
        if force, scrollPosition == idx {
            scrollPosition = nil
        }
        let delta = SegmentRenderWindow.segmentIndexDelta(
            from: scrollPosition ?? viewModel.selectedIdx,
            to: idx,
            in: viewModel.segments
        )
        let animate = delta <= SegmentRenderWindow.scrollAnimateThreshold
        if animate {
            withAnimation(.easeInOut(duration: segmentSwitchDuration)) {
                scrollPosition = idx
            }
        } else {
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
        guard let current,
              let pos = viewModel.arrayIndex(forSegmentIdx: current) else { return }
        let newPos = pos + delta
        guard newPos >= 0, newPos < viewModel.segments.count else { return }
        viewModel.selectedIdx = viewModel.segments[newPos].idx
        readerContentFocused = true
    }

    private func toggleContentMode() {
        contentMode = contentMode == .summary ? .original : .summary
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
                    if viewModel.summaryTotalCount > 0 {
                        Text("· 摘要 \(viewModel.summaryReadyCount)/\(viewModel.summaryTotalCount)")
                            .font(.caption)
                            .foregroundStyle(LuminaTheme.textSecondary)
                    }
                    Spacer(minLength: 0)
                    sidebarHeaderButtons
                }

                if viewModel.summaryTotalCount > 0 {
                    ProgressView(
                        value: Double(viewModel.summaryReadyCount),
                        total: Double(viewModel.summaryTotalCount)
                    )
                    .controlSize(.small)
                    .tint(LuminaTheme.accent)
                }

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
        SegmentSidebarView(
            items: viewModel.sidebarItems,
            selectedIdx: viewModel.selectedIdx,
            isSelectionMode: viewModel.isSegmentSelectionMode,
            checkedIndices: viewModel.checkedSegmentIndices,
            runningMetrics: viewModel.segmentRunningMetrics,
            segmentSwitchDuration: segmentSwitchDuration,
            onSelect: { selectSidebarSegment($0) },
            onToggleCheck: { viewModel.toggleCheck($0) },
            onRetrySegment: { idx in
                Task {
                    do { try await viewModel.retrySegment(idx, core: core) }
                    catch { actionError = error.localizedDescription }
                }
            },
            onRetryChecked: {
                Task {
                    do { try await viewModel.retryCheckedSegments(core: core) }
                    catch { actionError = error.localizedDescription }
                }
            }
        )
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

private struct PendingSegmentUpdate {
    var readyEvent: [String: Any]?
    var status: String?
    var statusEvent: [String: Any]?
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
    @Published var totalCharCount: Int?
    @Published private(set) var bookStatus = "unread"
    @Published var loadError: String?
    @Published var ingestProgress: IngestProgress?
    @Published private(set) var parsedSummaryCache: [Int: ParsedSummary] = [:]
    @Published private(set) var loadingSummaryIndices: Set<Int> = []
    @Published private(set) var sidebarItems: [SidebarSegmentItem] = []
    private var bookLanguage: String?
    private var bookTargetLanguage: String?
    private var bookTitle: String?
    private var globalTargetLanguage = "zh-CN"
    private var bookId = ""
    private var eventTask: Task<Void, Never>?
    private var detailTasks: [Int: Task<Void, Never>] = [:]
    private var summaryTasks: [Int: Task<Void, Never>] = [:]
    private var progressSaveTask: Task<Void, Never>?
    private var segmentFlushTask: Task<Void, Never>?
    private var pendingSegmentUpdates: [Int: PendingSegmentUpdate] = [:]
    private var pendingProgressIdx: Int?
    private var suppressProgressSave = false
    private var sourceCache: [Int: SegmentSourceBody] = [:]
    private var sourceCacheOrder: [Int] = []
    private var segmentIdxToArrayIndex: [Int: Int] = [:]
    private var contentMode: ReaderContentMode = .summary
    private let summaryModeCacheLimit = 5
    private let originalModeCacheLimit = 12
    private let summaryPrefetchRadius = 4

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
        guard let pos = arrayIndex(forSegmentIdx: idx) else { return }
        let start = max(0, pos - radius)
        let end = min(segments.count - 1, pos + radius)
        for i in start...end {
            let segmentIdx = segments[i].idx
            if sourceCache[segmentIdx] != nil {
                touchSourceCache(segmentIdx)
                continue
            }
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
        segmentFlushTask?.cancel()
        segmentFlushTask = nil
        pendingSegmentUpdates.removeAll()
        for task in detailTasks.values {
            task.cancel()
        }
        detailTasks.removeAll()
        for task in summaryTasks.values {
            task.cancel()
        }
        summaryTasks.removeAll()
        progressSaveTask?.cancel()
        progressSaveTask = nil
        loadingSourceIndices.removeAll()
        refreshingSourceIndices.removeAll()
        loadingSummaryIndices.removeAll()
    }

    func load(bookId: String, core: CoreClient, initialSegmentIndex: Int? = nil) async {
        flushProgressSave(core: core)
        cancelAllTasks()
        clearAllSourceCache()
        clearSummaryCache()
        sidebarItems = []
        segments = []
        segmentIdxToArrayIndex = [:]
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
            warmSummaryCache(from: list)
            rebuildSidebarItems()
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
            self.flushProgressSave(core: core)
        }
    }

    func flushProgressSave(core: CoreClient) {
        progressSaveTask?.cancel()
        progressSaveTask = nil
        guard let idx = pendingProgressIdx ?? selectedIdx, !bookId.isEmpty else { return }
        pendingProgressIdx = nil
        let bookId = self.bookId
        Task {
            try? await core.saveReadingProgress(bookId: bookId, segmentIndex: idx)
        }
    }

    /// Apply list meta only — never fetch or cache raw_text / translation in `segments[]`.
    func selectSegment(_ idx: Int) {
        guard let i = arrayIndex(forSegmentIdx: idx), i < segments.count else { return }
        currentSegment = segments[i]
    }

    func arrayIndex(forSegmentIdx idx: Int) -> Int? {
        segmentIdxToArrayIndex[idx]
    }

    func source(for idx: Int) -> SegmentSourceBody? {
        sourceCache[idx]
    }

    func cachedSource(for idx: Int) -> SegmentSourceBody? {
        guard let body = sourceCache[idx] else { return nil }
        touchSourceCache(idx)
        return body
    }

    private func touchSourceCache(_ idx: Int) {
        sourceCacheOrder.removeAll { $0 == idx }
        sourceCacheOrder.append(idx)
    }

    func isSourceLoading(idx: Int) -> Bool {
        loadingSourceIndices.contains(idx)
    }

    func isSourceRefreshing(idx: Int) -> Bool {
        refreshingSourceIndices.contains(idx)
    }

    func parsedSummary(for idx: Int) -> ParsedSummary? {
        parsedSummaryCache[idx]
    }

    func summaryBulletPreview(for idx: Int) -> String? {
        parsedSummaryCache[idx]?.bulletPreviewLine
    }

    func isSummaryLoading(idx: Int) -> Bool {
        loadingSummaryIndices.contains(idx)
    }

    func prefetchSummaries(around idx: Int, core: CoreClient, radius: Int? = nil) {
        let effectiveRadius = radius ?? summaryPrefetchRadius
        guard let pos = arrayIndex(forSegmentIdx: idx) else { return }
        let start = max(0, pos - effectiveRadius)
        let end = min(segments.count - 1, pos + effectiveRadius)
        for i in start...end {
            ensureSummaryLoaded(idx: segments[i].idx, core: core)
        }
    }

    func rebuildSidebarItems() {
        rebuildSegmentIndexMap()
        sidebarItems = segments.map { makeSidebarItem(for: $0) }
    }

    func patchSidebarItems(atSegmentIndices indices: Set<Int>) {
        for idx in indices {
            guard let arrayIndex = segmentIdxToArrayIndex[idx],
                  arrayIndex < segments.count,
                  arrayIndex < sidebarItems.count else { continue }
            sidebarItems[arrayIndex] = makeSidebarItem(for: segments[arrayIndex])
        }
    }

    private func rebuildSegmentIndexMap() {
        segmentIdxToArrayIndex = Dictionary(uniqueKeysWithValues: segments.enumerated().map { ($1.idx, $0) })
    }

    private func makeSidebarItem(for segment: SegmentRow) -> SidebarSegmentItem {
        SidebarSegmentItem.make(
            from: segment,
            bulletPreview: parsedSummaryCache[segment.idx]?.bulletPreviewLine,
            runningMetrics: segmentRunningMetrics[segment.idx]
        )
    }

    func ensureSummaryLoaded(idx: Int, core: CoreClient) {
        guard !bookId.isEmpty else { return }
        if parsedSummaryCache[idx] != nil { return }
        if loadingSummaryIndices.contains(idx) { return }
        guard let i = arrayIndex(forSegmentIdx: idx), i < segments.count else { return }
        guard segments[i].summary_status == "ready" else { return }

        if let json = segments[i].summary_json, !json.isEmpty {
            scheduleSummaryParse(idx: idx, json: json)
            return
        }

        loadingSummaryIndices.insert(idx)
        summaryTasks[idx]?.cancel()
        let bookId = self.bookId
        summaryTasks[idx] = Task { [weak self] in
            defer {
                Task { @MainActor in
                    self?.loadingSummaryIndices.remove(idx)
                    self?.summaryTasks.removeValue(forKey: idx)
                }
            }
            do {
                try Task.checkCancellation()
                let detail = try await core.fetchSegmentSummary(bookId: bookId, idx: idx)
                try Task.checkCancellation()
                await MainActor.run {
                    self?.applyFetchedSummary(idx: idx, detail: detail)
                }
            } catch is CancellationError {
                return
            } catch {
                return
            }
        }
    }

    private func clearSummaryCache() {
        for task in summaryTasks.values {
            task.cancel()
        }
        summaryTasks.removeAll()
        parsedSummaryCache = [:]
        loadingSummaryIndices.removeAll()
    }

    private func warmSummaryCache(from list: [SegmentRow]) {
        let items = list.compactMap { segment -> (Int, String)? in
            guard let json = segment.summary_json, !json.isEmpty else { return nil }
            return (segment.idx, json)
        }
        guard !items.isEmpty else { return }
        Task.detached(priority: .utility) { [weak self] in
            let parsed = ParsedSummary.parseBatch(items)
            guard !parsed.isEmpty else { return }
            await MainActor.run {
                self?.parsedSummaryCache.merge(parsed) { _, new in new }
                self?.patchSidebarItems(atSegmentIndices: Set(parsed.keys))
            }
        }
    }

    private func scheduleSummaryParse(idx: Int, json: String) {
        Task.detached(priority: .utility) { [weak self] in
            guard let parsed = ParsedSummary(json: json) else { return }
            await MainActor.run {
                self?.parsedSummaryCache[idx] = parsed
                self?.patchSidebarItems(atSegmentIndices: [idx])
            }
        }
    }

    private func applyFetchedSummary(idx: Int, detail: SegmentSummaryDetail) {
        guard let i = arrayIndex(forSegmentIdx: idx), i < segments.count else { return }
        var updated = segments[i]
        if let json = detail.summary_json, !json.isEmpty {
            updated.summary_json = json
            scheduleSummaryParse(idx: idx, json: json)
        }
        if let label = detail.label { updated.label = label }
        if let anchor = detail.anchor_label { updated.anchor_label = anchor }
        if let provider = detail.summary_provider { updated.summary_provider = provider }
        if let model = detail.summary_model { updated.summary_model = model }
        if let duration = detail.summary_duration_s { updated.summary_duration_s = duration }
        if let attempts = detail.summary_llm_attempts { updated.summary_llm_attempts = attempts }
        updated.summary_status = detail.summary_status ?? updated.summary_status
        segments[i] = updated
        syncCurrentSegment(from: updated)
        patchSidebarItems(atSegmentIndices: [idx])
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
        if !force, source(for: idx) != nil {
            touchSourceCache(idx)
            return
        }

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

    private func applySegmentStatus(idx: Int, status: String, label: String? = nil, event: [String: Any]? = nil) {
        guard let i = arrayIndex(forSegmentIdx: idx), i < segments.count else { return }
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
        applyRunningMetrics(idx: idx, status: status, event: event)
        patchSidebarItems(atSegmentIndices: [idx])
    }

    private func queueSegmentReady(idx: Int, event: [String: Any]) {
        var pending = pendingSegmentUpdates[idx] ?? PendingSegmentUpdate()
        pending.readyEvent = event
        pendingSegmentUpdates[idx] = pending
        scheduleSegmentFlush()
    }

    private func queueSegmentStatus(idx: Int, status: String, event: [String: Any]) {
        var pending = pendingSegmentUpdates[idx] ?? PendingSegmentUpdate()
        pending.status = status
        pending.statusEvent = event
        pendingSegmentUpdates[idx] = pending
        scheduleSegmentFlush()
    }

    private func scheduleSegmentFlush() {
        segmentFlushTask?.cancel()
        segmentFlushTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 75_000_000)
            guard !Task.isCancelled else { return }
            await MainActor.run {
                self?.flushPendingSegmentUpdates()
            }
        }
    }

    private func flushPendingSegmentUpdates() {
        guard !pendingSegmentUpdates.isEmpty else { return }
        let batch = pendingSegmentUpdates
        pendingSegmentUpdates.removeAll()
        segmentFlushTask = nil

        var updatedSegments = segments
        var jsonToParse: [(Int, String)] = []

        for (idx, update) in batch {
            guard let i = segmentIdxToArrayIndex[idx] ?? updatedSegments.firstIndex(where: { $0.idx == idx }) else { continue }
            var row = updatedSegments[i]

            if let event = update.readyEvent {
                row.summary_status = (event["summary_status"] as? String) ?? "ready"
                if let label = event["label"] as? String { row.label = label }
                if let summaryJSON = SegmentReadyEventParser.extractSummaryJSON(from: event) {
                    row.summary_json = summaryJSON
                    jsonToParse.append((idx, summaryJSON))
                }
                if let anchor = (event["anchor_label"] as? String) ?? (event["anchor"] as? String) {
                    row.anchor_label = anchor
                }
                if let provider = event["summary_provider"] as? String { row.summary_provider = provider }
                if let model = event["summary_model"] as? String { row.summary_model = model }
                if let duration = event["summary_duration_s"] as? Double {
                    row.summary_duration_s = duration
                } else if let duration = event["summary_duration_s"] as? Int {
                    row.summary_duration_s = Double(duration)
                }
                if let attempts = event["summary_llm_attempts"] as? Int {
                    row.summary_llm_attempts = attempts
                }
                segmentRunningMetrics.removeValue(forKey: idx)
                loadingSummaryIndices.remove(idx)
            } else if let status = update.status {
                row.summary_status = status
                if let label = update.statusEvent?["label"] as? String { row.label = label }
                if let retry = update.statusEvent?["retry_count"] as? Int {
                    row.retry_count = retry
                }
                if let duration = update.statusEvent?["summary_duration_s"] as? Double {
                    row.summary_duration_s = duration
                } else if let duration = update.statusEvent?["summary_duration_s"] as? Int {
                    row.summary_duration_s = Double(duration)
                }
                applyRunningMetrics(idx: idx, status: status, event: update.statusEvent)
            }

            updatedSegments[i] = row
            if selectedIdx == idx {
                currentSegment = row
            }
        }

        segments = updatedSegments
        rebuildSegmentIndexMap()
        patchSidebarItems(atSegmentIndices: Set(batch.keys))

        guard !jsonToParse.isEmpty else { return }
        Task.detached(priority: .utility) { [weak self] in
            let parsed = ParsedSummary.parseBatch(jsonToParse)
            guard !parsed.isEmpty else { return }
            await MainActor.run {
                self?.parsedSummaryCache.merge(parsed) { _, new in new }
                self?.patchSidebarItems(atSegmentIndices: Set(parsed.keys))
            }
        }
    }

    private func applyRunningMetrics(idx: Int, status: String, event: [String: Any]?) {
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
        } else {
            segmentRunningMetrics.removeValue(forKey: idx)
        }
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
            queueSegmentStatus(idx: idx, status: status, event: event)
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
            queueSegmentReady(idx: idx, event: event)
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
