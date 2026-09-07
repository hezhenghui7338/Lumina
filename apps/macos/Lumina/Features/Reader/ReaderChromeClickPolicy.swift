import SwiftUI

/// What a click on reader reading content means for the chrome.
///
/// Who receives the click is decided by SwiftUI hit-testing, not by inspecting
/// AppKit views: a SwiftUI Button, a text label and blank space all hit-test to
/// the same `PlatformGroupContainer`, so an AppKit/AX guess cannot tell them
/// apart. Controls therefore keep their own clicks, and only clicks that reach
/// the reading surface arrive here.
enum ReaderChromeClickOutcome: Equatable {
    /// An overlay owns the click (its dimmed backdrop closes it instead).
    case ignore
    case collapse
    case reveal
}

/// The reader action bar floats above the reading surface, so its height is a
/// constant the chrome panels reserve rather than something the feed gives up.
enum ReaderChromeBarMetrics {
    static let height: CGFloat = 44
    static let controlSize: ControlSize = .regular
    /// One face for every action label in the bar (text, 摘要 trigger, mode picker).
    static let labelSize: CGFloat = 14
    static let labelWeight: Font.Weight = .regular
    static let labelFont: Font = .system(size: labelSize, weight: labelWeight)
    static let modePickerWidth: CGFloat = 140
    /// Center book title; long names truncate. Keeps side icon clusters usable.
    static let titleMaxWidth: CGFloat = 220
}

/// Bottom overlays share one stack from the window edge: function bar, then
/// the listen mini-bar. Chat / notes / catalog sit on top of that stack so the
/// mini-bar cannot cover the deep-chat field.
enum ReaderBottomStackPolicy {
    static func overlayBottomPadding(listenActive: Bool, listenHasNotice: Bool) -> CGFloat {
        ReaderChromeBarMetrics.height
            + ListenMiniBarMetrics.clearance(isActive: listenActive, hasNotice: listenHasNotice)
    }

    static func miniBarBottomPadding(barsVisible: Bool) -> CGFloat {
        barsVisible ? ReaderChromeBarMetrics.height : 0
    }
}

enum ReaderChromeTextActionRole: Equatable {
    case disabled
    case hover
    case idle

    static func resolve(isEnabled: Bool, hovering: Bool) -> ReaderChromeTextActionRole {
        if !isEnabled { return .disabled }
        if hovering { return .hover }
        return .idle
    }

    var foreground: Color {
        switch self {
        case .disabled: return LuminaTheme.textSecondary
        case .hover: return LuminaTheme.accent
        case .idle: return LuminaTheme.textPrimary
        }
    }
}

/// Plain text chrome actions: no system bezel, hover tints accent, press dims.
struct ReaderChromeTextActionAppearance: ViewModifier {
    var isPressed: Bool = false
    @State private var hovering = false
    @Environment(\.isEnabled) private var isEnabled

    func body(content: Content) -> some View {
        content
            .font(ReaderChromeBarMetrics.labelFont)
            .foregroundStyle(
                ReaderChromeTextActionRole
                    .resolve(isEnabled: isEnabled, hovering: hovering)
                    .foreground
            )
            .padding(.horizontal, 6)
            .padding(.vertical, 4)
            .contentShape(Rectangle())
            .onHover { hovering = $0 }
            .opacity(isPressed ? 0.7 : 1)
    }
}

struct ReaderChromeTextActionButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .modifier(ReaderChromeTextActionAppearance(isPressed: configuration.isPressed))
    }
}

/// Icon chrome actions: no system bezel, press dims. Does not set
/// `foregroundStyle`, so an active icon can stay accent on its own.
struct ReaderChromeIconButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .contentShape(Rectangle())
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}

enum ReaderChromeClickPolicy {
    static func outcome(
        overlayOpen: Bool,
        chromeHidden: Bool,
        tourLocksChrome: Bool = false
    ) -> ReaderChromeClickOutcome {
        if tourLocksChrome { return chromeHidden ? .reveal : .ignore }
        if overlayOpen { return .ignore }
        return chromeHidden ? .reveal : .collapse
    }
}

/// Catalog overlay: slides over the reader, never resizes it.
struct ReaderCoverPageShell<Content: View>: View {
    @ViewBuilder var content: () -> Content

    var body: some View {
        content()
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(LuminaTheme.background)
    }
}

/// What a mouse-down on selectable reading body text meant once the mouse came
/// back up.
enum LuminaBodyTextClickOutcome: Equatable {
    /// The user was picking text out, by dragging or by multi-click.
    case selection
    /// A bare click that only dropped an existing selection.
    case dismissSelection
    /// A bare click on text with nothing selected before or after, which the
    /// reader still treats as a click on the reading surface.
    case plainClick
}

/// Selectable body text swallows its own mouse events, so the reading surface
/// would lose the chrome toggle unless a click is told apart from a selection.
/// `NSTextView.mouseDown` tracks the drag itself and returns after mouse-up,
/// so the verdict is read off the selection it left behind.
enum LuminaBodyTextClickPolicy {
    static func outcome(
        clickCount: Int,
        hadSelectionBefore: Bool,
        selectionLengthAfter: Int
    ) -> LuminaBodyTextClickOutcome {
        if clickCount > 1 { return .selection }
        if selectionLengthAfter > 0 { return .selection }
        if hadSelectionBefore { return .dismissSelection }
        return .plainClick
    }
}

/// Whether a finished body-text click should raise the copy / write-idea menu.
/// Click policy still classifies double-clicks as `.selection` even when nothing
/// was selected; the menu only appears once there is a non-blank quote.
enum LuminaSelectionActionPolicy {
    static func capturedQuote(from selectedText: String) -> String? {
        let trimmed = selectedText.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    static func shouldShowMenu(
        clickOutcome: LuminaBodyTextClickOutcome,
        selectedText: String
    ) -> Bool {
        guard clickOutcome == .selection else { return false }
        return capturedQuote(from: selectedText) != nil
    }
}

/// Book + segment the selected phrase belongs to (the block that owns the text,
/// not whichever segment currently has scroll focus).
struct ReaderSelectionNoteAnchor: Equatable {
    let bookId: String
    let segmentId: String
}

private struct ReaderBodyTextPlainClickKey: EnvironmentKey {
    static let defaultValue: (() -> Void)? = nil
}

private struct ReaderSelectionNoteAnchorKey: EnvironmentKey {
    static let defaultValue: ReaderSelectionNoteAnchor? = nil
}

private struct ReaderSelectionNoteClientKey: EnvironmentKey {
    static let defaultValue: CoreClient? = nil
}

private struct ReaderSelectionNoteSavedKey: EnvironmentKey {
    static let defaultValue: (() -> Void)? = nil
}

extension EnvironmentValues {
    var readerBodyTextPlainClick: (() -> Void)? {
        get { self[ReaderBodyTextPlainClickKey.self] }
        set { self[ReaderBodyTextPlainClickKey.self] = newValue }
    }

    var readerSelectionNoteAnchor: ReaderSelectionNoteAnchor? {
        get { self[ReaderSelectionNoteAnchorKey.self] }
        set { self[ReaderSelectionNoteAnchorKey.self] = newValue }
    }

    var readerSelectionNoteClient: CoreClient? {
        get { self[ReaderSelectionNoteClientKey.self] }
        set { self[ReaderSelectionNoteClientKey.self] = newValue }
    }

    var readerSelectionNoteSaved: (() -> Void)? {
        get { self[ReaderSelectionNoteSavedKey.self] }
        set { self[ReaderSelectionNoteSavedKey.self] = newValue }
    }
}

extension View {
    /// Makes a reader control strip own every click inside it. A disabled
    /// SwiftUI Button is not hit-testable, so without this a click on a greyed
    /// out control (or on the gap between controls) falls through and toggles
    /// the chrome.
    func absorbsReaderChromeClicks() -> some View {
        contentShape(Rectangle())
            .onTapGesture {}
    }

    /// Text commands on the reader action bar: no grey bezel, hover → accent.
    /// Never put this `buttonStyle` on a Menu: nested items inherit it and
    /// become unselectable.
    func readerChromeTextAction() -> some View {
        buttonStyle(ReaderChromeTextActionButtonStyle())
    }

    /// Gives every selectable body text view below this point somewhere to send
    /// clicks that turned out not to be selections.
    func onReaderBodyTextPlainClick(_ action: @escaping () -> Void) -> some View {
        environment(\.readerBodyTextPlainClick, action)
    }

    /// Lets selection popovers create a note on the segment that owns the text.
    func readerSelectionNoteContext(
        client: CoreClient,
        onSaved: @escaping () -> Void
    ) -> some View {
        environment(\.readerSelectionNoteClient, client)
            .environment(\.readerSelectionNoteSaved, onSaved)
    }

    func readerSelectionNoteAnchor(_ anchor: ReaderSelectionNoteAnchor) -> some View {
        environment(\.readerSelectionNoteAnchor, anchor)
    }

    /// Icon commands on the reader chrome: no grey bezel. Never put this
    /// `buttonStyle` on a Menu — nested items inherit it and become unselectable.
    func readerChromeIconAction() -> some View {
        buttonStyle(ReaderChromeIconButtonStyle())
    }
}
