import SwiftUI
import AppKit

struct ReaderView: View {
    let bookId: String
    var initialSegmentIndex: Int? = nil
    @EnvironmentObject private var core: CoreClient

    @StateObject private var viewModel = ReaderViewModel()
    @State private var chatInput = ""
    @State private var quoteText = ""
    @State private var highlightSegment: Int?
    @State private var showExport = false
    @State private var exportIncludeNotes = false

    var body: some View {
        HStack(spacing: 0) {
            segmentSidebar
            Divider()
            VStack(spacing: 0) {
                segmentContent
                Divider()
                chatPanel
            }
            Divider()
            NotesPanel(
                bookId: bookId,
                segmentId: viewModel.currentSegment?.id
            )
        }
        .task { await viewModel.load(bookId: bookId, core: core, initialSegmentIndex: initialSegmentIndex) }
        .toolbar {
            ToolbarItemGroup {
                Button("导出") { showExport = true }
                Button("填入选区") { fillQuoteFromPasteboard() }
            }
        }
        .sheet(isPresented: $showExport) {
            ExportSheet(isPresented: $showExport, includeNotes: $exportIncludeNotes) {
                Task { await viewModel.exportMarkdown(core: core, includeNotes: exportIncludeNotes) }
            }
        }
    }

    private var segmentSidebar: some View {
        List(viewModel.segments, selection: $viewModel.selectedIdx) { seg in
            HStack {
                statusIcon(seg.summary_status)
                VStack(alignment: .leading) {
                    Text(seg.label ?? "段 \(seg.idx + 1)")
                        .font(.subheadline)
                    if let ch = seg.chapter {
                        Text(ch).font(.caption2).foregroundStyle(.secondary)
                    }
                }
            }
            .tag(seg.idx)
        }
        .frame(width: 240)
        .onChange(of: viewModel.selectedIdx) { _, idx in
            guard let idx else { return }
            Task { await viewModel.selectSegment(idx, core: core) }
        }
    }

    private var segmentContent: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                if let detail = viewModel.currentSegment {
                    if let summary = detail.summary_json {
                        SummaryBlock(json: summary)
                    }
                    Text(detail.raw_text ?? "")
                        .textSelection(.enabled)
                    if let tr = detail.translation, !tr.isEmpty {
                        Text(tr).foregroundStyle(.secondary)
                    }
                } else {
                    ProgressView("加载段内容…")
                }
            }
            .padding()
            .background(highlightSegment == viewModel.selectedIdx ? LuminaTheme.accentMuted : Color.clear)
            .animation(.easeOut(duration: 0.4), value: highlightSegment)
        }
        .frame(maxHeight: .infinity)
    }

    private var chatPanel: some View {
        VStack(spacing: 8) {
            if !quoteText.isEmpty {
                HStack {
                    Text("引用: \(quoteText)")
                        .font(.caption)
                        .lineLimit(1)
                        .foregroundStyle(LuminaTheme.accent)
                    Spacer()
                    Button("清除") { quoteText = "" }
                        .font(.caption)
                }
                .padding(.horizontal)
            }

            ScrollView {
                LazyVStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(viewModel.messages.enumerated()), id: \.element.id) { index, msg in
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text(msg.role == "user" ? "你" : "深聊")
                                    .font(.caption.bold())
                                Spacer()
                                if msg.role == "assistant", !msg.content.isEmpty {
                                    Button("存为笔记") {
                                        Task { await viewModel.saveAsNote(msg.content, core: core) }
                                    }
                                    .font(.caption)
                                }
                            }
                            Text(msg.content)
                            ForEach(msg.citations, id: \.segment_index) { c in
                                Button(c.label) {
                                    viewModel.selectedIdx = c.segment_index
                                    highlightSegment = c.segment_index
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
            }
            .frame(height: 220)

            HStack {
                TextField("提问…", text: $chatInput)
                    .textFieldStyle(.roundedBorder)
                Button("发送") {
                    let text = chatInput
                    let quote = quoteText.isEmpty ? nil : quoteText
                    chatInput = ""
                    quoteText = ""
                    Task { await viewModel.sendChat(text, quote: quote, core: core) }
                }
                .disabled(chatInput.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            .padding(.horizontal)
            .padding(.bottom, 8)
        }
    }

    private func fillQuoteFromPasteboard() {
        if let text = NSPasteboard.general.string(forType: .string), !text.isEmpty {
            quoteText = String(text.prefix(500))
        }
    }

    @ViewBuilder
    private func statusIcon(_ status: String) -> some View {
        switch status {
        case "ready": Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
        case "running": ProgressView().scaleEffect(0.6)
        case "failed", "error": Image(systemName: "exclamationmark.circle").foregroundStyle(.red)
        default: Image(systemName: "circle").foregroundStyle(.secondary)
        }
    }
}

struct SummaryBlock: View {
    let json: String
    var body: some View {
        if let data = json.data(using: .utf8),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            VStack(alignment: .leading, spacing: 6) {
                if let sentences = obj["sentences"] as? [String] {
                    ForEach(sentences, id: \.self) { Text($0).font(.subheadline) }
                }
                if let bullets = obj["bullets"] as? [String] {
                    ForEach(bullets, id: \.self) { Text("• \($0)").font(.caption) }
                }
            }
            .padding(10)
            .background(LuminaTheme.accentMuted)
            .clipShape(RoundedRectangle(cornerRadius: 10))
        }
    }
}

@MainActor
final class ReaderViewModel: ObservableObject {
    @Published var segments: [SegmentRow] = []
    @Published var selectedIdx: Int?
    @Published var currentSegment: SegmentRow?
    @Published var messages: [ChatMessage] = []
    private var bookId = ""
    private var eventTask: Task<Void, Never>?

    func load(bookId: String, core: CoreClient, initialSegmentIndex: Int? = nil) async {
        self.bookId = bookId
        try? await core.openBook(id: bookId)
        segments = (try? await core.listSegments(bookId: bookId)) ?? []
        selectedIdx = initialSegmentIndex ?? segments.first?.idx
        if let idx = selectedIdx {
            await selectSegment(idx, core: core)
        }
        eventTask?.cancel()
        eventTask = core.subscribeEvents(bookId: bookId) { [weak self] event in
            Task { @MainActor in
                self?.handleEvent(event, core: core)
            }
        }
    }

    func selectSegment(_ idx: Int, core: CoreClient) async {
        currentSegment = try? await core.getSegment(bookId: bookId, idx: idx)
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

    func saveAsNote(_ content: String, core: CoreClient) async {
        _ = try? await core.createNote(
            bookId: bookId,
            content: content,
            segmentId: currentSegment?.id,
            type: "ai"
        )
    }

    func exportMarkdown(core: CoreClient, includeNotes: Bool) async {
        guard let md = try? await core.exportMarkdown(bookId: bookId, includeNotes: includeNotes) else { return }
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "summary.md"
        panel.begin { resp in
            guard resp == .OK, let url = panel.url else { return }
            try? md.write(to: url, atomically: true, encoding: .utf8)
        }
    }

    private func handleEvent(_ event: [String: Any], core: CoreClient) {
        guard event["type"] as? String == "segment_ready" else { return }
        Task {
            segments = (try? await core.listSegments(bookId: bookId)) ?? segments
            if selectedIdx == event["idx"] as? Int {
                await selectSegment(selectedIdx ?? 0, core: core)
            }
        }
    }
}
