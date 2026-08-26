import AppKit
import SwiftUI

/// Copy / write-idea menu that appears after a reader body selection.
struct ReaderSelectionActionBar: View {
    @ObservedObject var model: ReaderSelectionActionModel
    @FocusState private var ideaFocused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 4) {
                Button("复制") {
                    model.copyToPasteboard()
                }
                .accessibilityIdentifier("lumina.reader.selection.copy")

                if model.canWriteNote {
                    Button("写想法") {
                        model.beginComposing()
                    }
                    .accessibilityIdentifier("lumina.reader.selection.writeIdea")
                    .disabled(model.isComposing)
                }
            }
            .buttonStyle(.borderless)
            .controlSize(.regular)

            if model.isComposing {
                Text("「\(model.quote)」")
                    .font(.caption)
                    .foregroundStyle(LuminaTheme.accent)
                    .lineLimit(4)
                    .frame(maxWidth: 260, alignment: .leading)

                TextField("写想法…", text: $model.draft, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(2...4)
                    .frame(minWidth: 220, maxWidth: 260)
                    .focused($ideaFocused)

                if let error = model.error, !error.isEmpty {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .frame(maxWidth: 260, alignment: .leading)
                }

                HStack {
                    Spacer()
                    Button("保存") {
                        model.save()
                    }
                    .accessibilityIdentifier("lumina.reader.selection.save")
                    .disabled(!model.canSave)
                    .buttonStyle(.borderedProminent)
                    .tint(LuminaTheme.accent)
                    .controlSize(.small)
                }
            }
        }
        .padding(10)
        .frame(minWidth: model.isComposing ? 244 : 108, alignment: .leading)
        .onChange(of: model.isComposing) { _, composing in
            if composing { ideaFocused = true }
        }
    }
}

@MainActor
final class ReaderSelectionActionModel: ObservableObject {
    let quote: String
    let canWriteNote: Bool

    @Published var isComposing = false
    @Published var draft = ""
    @Published var error: String?
    @Published var isSaving = false

    private let core: CoreClient?
    private let anchor: ReaderSelectionNoteAnchor?
    private let onSaved: (() -> Void)?
    private let onDismiss: () -> Void
    private let onComposerOpened: () -> Void
    private var saveTask: Task<Void, Never>?

    var canSave: Bool {
        !isSaving && !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    init(
        quote: String,
        core: CoreClient?,
        anchor: ReaderSelectionNoteAnchor?,
        onSaved: (() -> Void)?,
        onDismiss: @escaping () -> Void,
        onComposerOpened: @escaping () -> Void
    ) {
        self.quote = quote
        self.core = core
        self.anchor = anchor
        self.canWriteNote = core != nil && anchor != nil
        self.onSaved = onSaved
        self.onDismiss = onDismiss
        self.onComposerOpened = onComposerOpened
    }

    func copyToPasteboard() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(quote, forType: .string)
        onDismiss()
    }

    func beginComposing() {
        guard canWriteNote, !isComposing else { return }
        isComposing = true
        onComposerOpened()
    }

    func save() {
        guard canSave else { return }
        let content = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let core, let anchor else { return }
        isSaving = true
        error = nil
        saveTask?.cancel()
        saveTask = Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                _ = try await core.createNote(
                    bookId: anchor.bookId,
                    content: content,
                    segmentId: anchor.segmentId,
                    quote: self.quote,
                    type: "manual"
                )
                guard !Task.isCancelled else { return }
                self.onSaved?()
                self.onDismiss()
            } catch {
                guard !Task.isCancelled else { return }
                self.isSaving = false
                if let message = error.userFacingMessage, !message.isEmpty {
                    self.error = message
                } else if !error.isCancellation {
                    self.error = "保存失败"
                }
            }
        }
    }

    func cancelSave() {
        saveTask?.cancel()
        saveTask = nil
    }
}

/// One reader-wide selection popover. Transient for the two buttons; semitransient
/// once the idea field needs first-responder so the popover does not self-dismiss.
@MainActor
enum LuminaSelectionActionPopover {
    static func dismiss() {
        Controller.shared.dismiss()
    }

    static func present(
        quote: String,
        relativeTo rect: NSRect,
        of view: NSView,
        core: CoreClient?,
        anchor: ReaderSelectionNoteAnchor?,
        onSaved: (() -> Void)?
    ) {
        Controller.shared.present(
            quote: quote,
            relativeTo: rect,
            of: view,
            core: core,
            anchor: anchor,
            onSaved: onSaved
        )
    }

    static func dismissIfPresenting(from view: NSView) {
        Controller.shared.dismissIfPresenting(from: view)
    }

    @MainActor
    fileprivate final class Controller: NSObject, NSPopoverDelegate {
        static let shared = Controller()

        private var popover: NSPopover?
        private var model: ReaderSelectionActionModel?
        private var hosting: NSHostingController<ReaderSelectionActionBar>?
        private var scrollObserver: NSObjectProtocol?
        private weak var presentingView: NSView?

        func present(
            quote: String,
            relativeTo rect: NSRect,
            of view: NSView,
            core: CoreClient?,
            anchor: ReaderSelectionNoteAnchor?,
            onSaved: (() -> Void)?
        ) {
            dismiss()
            let model = ReaderSelectionActionModel(
                quote: quote,
                core: core,
                anchor: anchor,
                onSaved: onSaved,
                onDismiss: { [weak self] in self?.dismiss() },
                onComposerOpened: { [weak self] in self?.enterComposerMode() }
            )
            let hosting = NSHostingController(rootView: ReaderSelectionActionBar(model: model))
            hosting.sizingOptions = [.intrinsicContentSize, .preferredContentSize]
            let popover = NSPopover()
            popover.contentViewController = hosting
            popover.behavior = .transient
            popover.animates = true
            popover.delegate = self
            self.model = model
            self.hosting = hosting
            self.popover = popover
            self.presentingView = view
            watchScroll(of: view)
            popover.show(relativeTo: rect, of: view, preferredEdge: .minY)
            fitSize()
        }

        func dismiss() {
            model?.cancelSave()
            stopWatchingScroll()
            if let popover, popover.isShown {
                popover.performClose(nil)
            }
            popover = nil
            hosting = nil
            model = nil
            presentingView = nil
        }

        func popoverDidClose(_ notification: Notification) {
            guard (notification.object as? NSPopover) === popover else { return }
            model?.cancelSave()
            stopWatchingScroll()
            popover = nil
            hosting = nil
            model = nil
            presentingView = nil
        }

        private func enterComposerMode() {
            guard let model else { return }
            popover?.behavior = .semitransient
            hosting?.rootView = ReaderSelectionActionBar(model: model)
            fitSize()
        }

        func dismissIfPresenting(from view: NSView) {
            if presentingView === view {
                dismiss()
            }
        }

        private func fitSize() {
            guard let hosting, let popover else { return }
            hosting.view.layoutSubtreeIfNeeded()
            let fitted = hosting.view.fittingSize
            popover.contentSize = NSSize(
                width: max(fitted.width, 1),
                height: max(fitted.height, 1)
            )
        }

        private func watchScroll(of view: NSView) {
            guard let clip = view.enclosingScrollView?.contentView else { return }
            clip.postsBoundsChangedNotifications = true
            scrollObserver = NotificationCenter.default.addObserver(
                forName: NSView.boundsDidChangeNotification,
                object: clip,
                queue: .main
            ) { [weak self] _ in
                Task { @MainActor in
                    self?.dismiss()
                }
            }
        }

        private func stopWatchingScroll() {
            if let scrollObserver {
                NotificationCenter.default.removeObserver(scrollObserver)
            }
            scrollObserver = nil
        }
    }
}
