import XCTest
@testable import Lumina

final class ReaderChromeClickPolicyTests: XCTestCase {
    func testHiddenChromeIsRevealed() {
        XCTAssertEqual(
            ReaderChromeClickPolicy.outcome(
                overlayOpen: false,
                chromeHidden: true
            ),
            .reveal
        )
    }

    func testVisibleChromeCollapses() {
        XCTAssertEqual(
            ReaderChromeClickPolicy.outcome(
                overlayOpen: false,
                chromeHidden: false
            ),
            .collapse
        )
    }

    func testOpenOverlayOwnsTheClick() {
        for chromeHidden in [true, false] {
            XCTAssertEqual(
                ReaderChromeClickPolicy.outcome(
                    overlayOpen: true,
                    chromeHidden: chromeHidden
                ),
                .ignore
            )
        }
    }

    func testTourLocksChrome_doesNotCollapse() {
        XCTAssertEqual(
            ReaderChromeClickPolicy.outcome(
                overlayOpen: false,
                chromeHidden: false,
                tourLocksChrome: true
            ),
            .ignore
        )
        XCTAssertEqual(
            ReaderChromeClickPolicy.outcome(
                overlayOpen: false,
                chromeHidden: true,
                tourLocksChrome: true
            ),
            .reveal
        )
    }
}

/// Locks the architecture that fixed reader control clicks toggling the chrome.
///
/// Measured on macOS 15: a SwiftUI Button, a text label and blank space all
/// hit-test to the same `PlatformGroupContainer`, and `.buttonStyle(.bordered)`
/// creates no `NSButton` at all — so an AppKit hit-test walk can never tell a
/// control click from a reading click, and every reader button ends up toggling
/// the chrome. Ownership must stay with SwiftUI hit-testing: the frontmost
/// handler (the Button) takes the click, and only clicks that reach the reading
/// surface call `toggleChromeOnBlankClick()`.
final class ReaderChromeClickArchitectureTests: XCTestCase {
    private func source(_ relativePath: String) throws -> String {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()  // Unit
            .deletingLastPathComponent()  // LuminaTests
            .deletingLastPathComponent()  // macos
        return try String(
            contentsOf: macosRoot.appendingPathComponent(relativePath),
            encoding: .utf8
        )
    }

    private func readerSource() throws -> String {
        try source("Lumina/Features/Reader/ReaderView.swift")
    }

    private func topChromeBarSource(_ reader: String) -> String {
        let after = reader.components(separatedBy: "private var readerChromeBar: some View").last ?? ""
        return after.components(separatedBy: "private var readerBottomBarOverlay").first ?? ""
    }

    private func bottomFunctionBarSource(_ reader: String) -> String {
        let after = reader.components(separatedBy: "private var readerBottomBar: some View").last ?? ""
        return after.components(separatedBy: "private func readerBottomBarButton").first ?? ""
    }

    func testReaderNeverGuessesControlsFromAppKitOrAccessibility() throws {
        let source = try readerSource()
        for banned in [
            "ChromeClickTracker",
            "ChromeClickNSView",
            "ChromeClickHitPolicy",
            "AXUIElementCopyElementAtPosition",
            "isPointInReaderDocument",
            "addLocalMonitorForEvents(matching: .leftMouseDown",
            "addLocalMonitorForEvents(matching: .leftMouseUp",
        ] {
            XCTAssertFalse(
                source.contains(banned),
                "\(banned) resurrects control-hit guessing, which makes every reader button toggle the chrome"
            )
        }
    }

    func testReaderFeedOwnsTheChromeToggleGesture() throws {
        let source = try readerSource()
        XCTAssertTrue(
            source.contains(".onTapGesture { toggleChromeOnBlankClick() }"),
            "the reader feed must own the chrome toggle so controls can outrank it"
        )
        XCTAssertEqual(
            source.components(separatedBy: "toggleChromeOnBlankClick()").count - 1,
            2,
            "exactly one caller (the feed tap) plus the definition may exist"
        )
    }

    /// Locks the fix for "clicking blank space slides the text": the window
    /// toolbar row is a real layout row, so adding/removing it resized the
    /// content area and the reader's chrome animation played that as a slide.
    func testReaderChromeIsAFloatingBarWithNoLayoutFootprint() throws {
        let source = try readerSource()
        XCTAssertTrue(
            source.contains("readerChromeBarOverlay"),
            "the top reader bar must be an overlay so showing it cannot move the feed"
        )
        XCTAssertTrue(
            source.contains("readerBottomBarOverlay"),
            "the bottom function bar must be an overlay so showing it cannot move the feed"
        )
        for banned in ["ToolbarItem", "readerToolbar"] {
            XCTAssertFalse(
                source.contains(banned),
                "\(banned) puts reader chrome back in the window toolbar row, which resizes the reading surface"
            )
        }
    }

    func testReaderChromeBarAndInsetsShareTheBarHeight() throws {
        XCTAssertEqual(ReaderChromeBarMetrics.height, 44)
        let reader = try readerSource()
        XCTAssertEqual(
            reader.components(separatedBy: "ReaderChromeBarMetrics.height").count - 1,
            5,
            "top/bottom bar frames, notes top pad, and top/bottom feed insets must share the same reserved height"
        )
        XCTAssertTrue(reader.contains("ReaderChromeBarMetrics.labelFont"))
        XCTAssertTrue(reader.contains("ReaderChromeBarMetrics.controlSize"))
        let body = topChromeBarSource(reader)
        XCTAssertFalse(
            body.contains(".controlSize(.small)"),
            "the action bar must not pin controlSize.small or the icons and labels shrink again"
        )
    }

    func testListenMiniBarDoesNotCoverChatInput() throws {
        XCTAssertEqual(ListenMiniBarMetrics.clearance(isActive: false, hasNotice: true), 0)
        XCTAssertEqual(ListenMiniBarMetrics.clearance(isActive: true, hasNotice: false), ListenMiniBarMetrics.height)
        XCTAssertEqual(
            ListenMiniBarMetrics.clearance(isActive: true, hasNotice: true),
            ListenMiniBarMetrics.height + ListenMiniBarMetrics.noticeHeight
        )
        XCTAssertEqual(ListenMiniBarMetrics.height, ReaderChromeBarMetrics.height)
        XCTAssertEqual(
            ReaderBottomStackPolicy.overlayBottomPadding(
                listenActive: false,
                listenHasNotice: false
            ),
            ReaderChromeBarMetrics.height
        )
        XCTAssertEqual(
            ReaderBottomStackPolicy.overlayBottomPadding(
                listenActive: true,
                listenHasNotice: false
            ),
            ReaderChromeBarMetrics.height + ListenMiniBarMetrics.height
        )
        XCTAssertEqual(
            ReaderBottomStackPolicy.overlayBottomPadding(
                listenActive: true,
                listenHasNotice: true
            ),
            ReaderChromeBarMetrics.height
                + ListenMiniBarMetrics.height
                + ListenMiniBarMetrics.noticeHeight
        )
        XCTAssertEqual(
            ReaderBottomStackPolicy.miniBarBottomPadding(barsVisible: true),
            ReaderChromeBarMetrics.height
        )
        XCTAssertEqual(
            ReaderBottomStackPolicy.miniBarBottomPadding(barsVisible: false),
            0
        )

        let reader = try readerSource()
        XCTAssertEqual(
            reader.components(separatedBy: "overlayBottomPadding").count - 1,
            5,
            "the padding helper, its policy call, plus notes/chat/catalog must share overlayBottomPadding"
        )
        let layout = reader.components(separatedBy: "private var readerLayout: some View").last?
            .components(separatedBy: ".onExitCommand").first ?? ""
        XCTAssertTrue(
            layout.contains(".padding(.bottom, overlayBottomPadding)"),
            "chat and catalog must lift above the listen mini-bar, not share its bottom edge"
        )
        XCTAssertTrue(
            layout.contains("ReaderBottomStackPolicy.miniBarBottomPadding(barsVisible: barsVisible)"),
            "the mini-bar still sits on the function bar when chrome is visible"
        )
        let miniBar = try source("Lumina/Features/Reader/Listen/ListenMiniBar.swift")
        XCTAssertTrue(
            miniBar.contains(".frame(height: ListenMiniBarMetrics.noticeHeight)"),
            "the skip caption must occupy noticeHeight so overlay padding matches the bar"
        )
        XCTAssertTrue(miniBar.contains(".frame(height: ListenMiniBarMetrics.height)"))
        guard
            let chatRange = layout.range(of: "chatDrawer"),
            let miniRange = layout.range(of: "ListenMiniBar")
        else {
            return XCTFail("readerLayout must host both the chat drawer and the listen mini-bar")
        }
        XCTAssertLessThan(
            chatRange.lowerBound,
            miniRange.lowerBound,
            "the mini-bar stays above the chat layer in ZStack order so playback remains visible"
        )
    }

    func testReaderChromeActionLabelsShareOneRegularFont() throws {
        XCTAssertEqual(ReaderChromeBarMetrics.labelSize, 14)
        XCTAssertEqual(ReaderChromeBarMetrics.labelWeight, .regular)

        let policy = try source("Lumina/Features/Reader/ReaderChromeClickPolicy.swift")
        XCTAssertFalse(
            policy.contains("textActionFont"),
            "a second action font splits 笔记/提问 from the rest of the bar"
        )
        XCTAssertFalse(
            policy.contains("weight: .bold") || policy.contains("weight(.bold)"),
            "bold action labels look off in the chrome bar"
        )
        XCTAssertFalse(
            policy.contains("weight: .semibold") || policy.contains("weight(.semibold)"),
            "semibold is still a bold face; the bar uses one regular weight"
        )
        XCTAssertTrue(policy.contains(".font(ReaderChromeBarMetrics.labelFont)"))

        let reader = try readerSource()
        let chromeBarBody = topChromeBarSource(reader)
        let fontPins = chromeBarBody.components(separatedBy: "ReaderChromeBarMetrics.labelFont").count - 1
        XCTAssertGreaterThanOrEqual(
            fontPins,
            2,
            "the HStack and the mode picker labels must share labelFont with the text actions"
        )
        XCTAssertFalse(
            chromeBarBody.contains(".bold") || chromeBarBody.contains("weight(.semibold)"),
            "the chrome bar must not pin a second heavier face on some actions"
        )
    }

    func testReaderChromeTextActionsAreBorderlessWithHover() throws {
        XCTAssertEqual(
            ReaderChromeTextActionRole.resolve(isEnabled: true, hovering: false),
            .idle
        )
        XCTAssertEqual(
            ReaderChromeTextActionRole.resolve(isEnabled: true, hovering: true),
            .hover
        )
        XCTAssertEqual(
            ReaderChromeTextActionRole.resolve(isEnabled: false, hovering: true),
            .disabled,
            "disabled text actions must stay grey even when the pointer is over them"
        )

        let reader = try readerSource()
        let chromeBarBody = topChromeBarSource(reader)
        let textActionPrefixHits =
            chromeBarBody.components(separatedBy: ".readerChromeTextAction()").count - 1
        XCTAssertEqual(
            textActionPrefixHits,
            1,
            "only the center book title is a chrome text action; icon clusters stay icon-styled"
        )
        XCTAssertTrue(
            chromeBarBody.contains("displayBookTitle"),
            "the top bar must show the current book title"
        )
        XCTAssertTrue(
            chromeBarBody.contains("lineLimit(1)"),
            "long book titles must truncate on one line"
        )
        XCTAssertTrue(
            chromeBarBody.contains("ReaderChromeBarMetrics.titleMaxWidth"),
            "the title must share a capped width so side icons stay usable"
        )
        XCTAssertEqual(
            chromeBarBody.components(separatedBy: ".help(\"返回书架\")").count - 1,
            2,
            "back chevron and book title are both return-to-bookshelf entries"
        )
        XCTAssertFalse(
            chromeBarBody.contains(".readerChromeTextActionLook()"),
            "分段 is an icon+popover like 摘要, not a Menu trigger with look-only"
        )
        XCTAssertFalse(
            chromeBarBody.contains(".readerChromeTextActionMenu()"),
            "分段 must not use a Menu; the system chevron made it unlike 摘要"
        )
        XCTAssertFalse(
            chromeBarBody.contains(".buttonStyle(.bordered)"),
            "a bordered style on the chrome bar brings back the grey bezels"
        )
        let hstackModifiers = chromeBarBody.components(separatedBy: ".help(\"导入书籍\")").last ?? ""
        XCTAssertFalse(
            hstackModifiers.contains("readerChromeTextAction"),
            "the text-action style must not sit on the whole HStack or icon buttons and the mode picker flatten too"
        )
        XCTAssertTrue(
            chromeBarBody.contains(".absorbsReaderChromeClicks()"),
            "plain text actions still leave disabled hits unowned; the bar must swallow them"
        )

        let policy = try source("Lumina/Features/Reader/ReaderChromeClickPolicy.swift")
        XCTAssertTrue(policy.contains("ReaderChromeTextActionButtonStyle"))
        XCTAssertTrue(policy.contains("labelFont"))
        XCTAssertTrue(policy.contains(".onHover"))
        XCTAssertFalse(
            policy.contains("menuIndicator(.visible)"),
            "toolbar Menus must not show a system chevron beside icon-only actions"
        )
    }

    func testReaderChromeIconActionsHaveNoBezel() throws {
        let policy = try source("Lumina/Features/Reader/ReaderChromeClickPolicy.swift")
        XCTAssertTrue(policy.contains("struct ReaderChromeIconButtonStyle"))
        XCTAssertTrue(policy.contains("func readerChromeIconAction()"))
        let styleBody = policy
            .components(separatedBy: "struct ReaderChromeIconButtonStyle")
            .last?
            .components(separatedBy: "enum ReaderChromeClickPolicy")
            .first ?? ""
        XCTAssertFalse(
            styleBody.contains("foregroundStyle"),
            "the icon style must not override Label foreground; active icons stay accent"
        )
        XCTAssertTrue(styleBody.contains("contentShape(Rectangle())"))
        XCTAssertTrue(styleBody.contains("isPressed"))

        let reader = try readerSource()
        let chromeBarBody = topChromeBarSource(reader)
        XCTAssertEqual(
            chromeBarBody.components(separatedBy: ".readerChromeIconAction()").count - 1,
            5,
            "返回, 摘要, 分段, 导出, and 导入 must each drop the system bezel"
        )
        XCTAssertTrue(chromeBarBody.contains("chevron.left"))
        XCTAssertTrue(chromeBarBody.contains("square.and.arrow.up"))
        XCTAssertTrue(
            chromeBarBody.contains(".pickerStyle(.segmented)"),
            "摘要 | 原文 stays a system segmented control"
        )
        XCTAssertTrue(
            chromeBarBody.contains("listenChromeControl"),
            "听文本 sits beside 摘要 | 原文"
        )
        let hstackModifiers = chromeBarBody.components(separatedBy: ".help(\"导入书籍\")").last ?? ""
        XCTAssertFalse(
            hstackModifiers.contains("readerChromeIconAction"),
            "the icon style must not sit on the whole HStack or the mode picker flattens too"
        )
        XCTAssertFalse(
            chromeBarBody.contains(".buttonStyle(.bordered)"),
            "a bordered style on the chrome bar brings back the grey bezels"
        )

        let helper = reader
            .components(separatedBy: "private func readerBottomBarButton(")
            .last?
            .components(separatedBy: "private var readerLayout")
            .first ?? ""
        XCTAssertTrue(
            helper.contains(".readerChromeIconAction()"),
            "段列表 / 深聊 / 笔记 / 显示 share one borderless icon helper"
        )
        XCTAssertTrue(
            helper.contains(".contentShape(Rectangle())"),
            "plain icons must keep the expanded cell tappable"
        )
        XCTAssertTrue(helper.contains("frame(maxWidth: .infinity"))
        XCTAssertTrue(
            helper.contains("isActive ? LuminaTheme.accent"),
            "active icons keep their own accent; the icon style must not paint it"
        )
    }

    func testReaderChromeSummaryMenuDoesNotRestyleMenuItems() throws {
        let policy = try source("Lumina/Features/Reader/ReaderChromeClickPolicy.swift")
        let iconAction = policy
            .components(separatedBy: "func readerChromeIconAction()")
            .last?
            .components(separatedBy: "}")
            .first ?? ""
        XCTAssertTrue(
            policy.contains("Never put this `buttonStyle` on a Menu"),
            "buttonStyle on Menu is inherited by nested items; custom styles make NSMenuItems unselectable"
        )
        XCTAssertTrue(iconAction.contains("buttonStyle(ReaderChromeIconButtonStyle())"))

        let split = try source("Lumina/Features/Shared/SummarizeChevronSplit.swift")
        XCTAssertTrue(split.contains("Button(title, action: primary)"))
        XCTAssertTrue(split.contains("chevron.down"))
        XCTAssertTrue(split.contains(".menuStyle(.borderlessButton)"))
        XCTAssertTrue(split.contains(".menuIndicator(.hidden)"))
        XCTAssertFalse(
            split.contains("primaryAction"),
            "a nested Menu+primaryAction opens advanced on hover"
        )
        let menuBlock = split.components(separatedBy: "Menu(content: advancedMenu)").last ?? ""
        XCTAssertFalse(
            menuBlock.contains(".buttonStyle"),
            "buttonStyle on the chevron Menu restyles NSMenuItems"
        )

        let reader = try readerSource()
        let chromeBarBody = topChromeBarSource(reader)
        let summarizeBlock = chromeBarBody
            .components(separatedBy: "listenChromeControl")
            .last?
            .components(separatedBy: "Label(\"分段\"")
            .first ?? ""
        XCTAssertTrue(
            summarizeBlock.contains(".popover(isPresented: $showSummarizePopover"),
            "摘要 opens a popover so inner splits are not NSMenu submenus"
        )
        XCTAssertTrue(summarizeBlock.contains("SummarizeChevronSplit(title: \"开始摘要\")"))
        XCTAssertTrue(summarizeBlock.contains("SummarizeChevronSplit(title: \"重新摘要整书\")"))
        XCTAssertTrue(summarizeBlock.contains("Button(\"停止摘要\")"))
        XCTAssertTrue(summarizeBlock.contains("高级摘要（仅未摘要）"))
        XCTAssertTrue(summarizeBlock.contains("高级摘要（覆盖全书）"))
        XCTAssertTrue(summarizeBlock.contains("showAdvancedStartConfirm"))
        XCTAssertTrue(summarizeBlock.contains("showRegenerateConfirm"))
        XCTAssertTrue(
            summarizeBlock.contains("点旁边箭头才展开高级（悬停不弹出）"),
            "the tooltip must say click the chevron; hover must not open advanced"
        )
        XCTAssertFalse(
            summarizeBlock.contains("primaryAction"),
            "listen and 摘要 splits must not use primaryAction; long-press menus are undiscoverable"
        )
        XCTAssertFalse(
            summarizeBlock.contains(".contextMenu"),
            "advanced is the chevron Menu, not a hidden right-click menu"
        )
        XCTAssertFalse(
            chromeBarBody.contains("Menu(\"摘要\")"),
            "Menu(\"摘要\") plus a cascading buttonStyle restyles every item inside"
        )
        XCTAssertFalse(chromeBarBody.contains("Menu(\"开始摘要\")"))
        XCTAssertFalse(chromeBarBody.contains("Menu(\"全书重新摘要\")"))
        XCTAssertFalse(chromeBarBody.contains("Menu(\"重新摘要整书\")"))

        XCTAssertTrue(
            chromeBarBody.contains("Button(\"调整分段\")"),
            "调整分段 is a menu item, not the icon's primaryAction"
        )
        XCTAssertFalse(
            chromeBarBody.contains("Button(\"导出\")"),
            "export is an icon button, not a text label"
        )
        XCTAssertTrue(chromeBarBody.contains("rectangle.split.3x1"))
        XCTAssertTrue(
            chromeBarBody.contains("Label(\"导出\", systemImage: \"square.and.arrow.up\")")
        )

        let segmentMenu = chromeBarBody
            .components(separatedBy: "accessibilityLabel(\"摘要\")")
            .last?
            .components(separatedBy: "square.and.arrow.up")
            .first ?? ""
        XCTAssertTrue(chromeBarBody.contains("Button(\"整书重新分段\")"))
        XCTAssertTrue(
            segmentMenu.contains(".popover(isPresented: $showSegmentPopover"),
            "分段 opens a popover like 摘要; a Menu would show a system chevron"
        )
        XCTAssertTrue(segmentMenu.contains(".readerChromeIconAction()"))
        XCTAssertFalse(
            segmentMenu.contains("Menu {") || segmentMenu.contains("Menu("),
            "分段 must not be a Menu; the indicator next to the icon was unlike 摘要"
        )
        XCTAssertFalse(
            segmentMenu.contains("menuIndicator"),
            "分段 has no dropdown chevron beside the icon"
        )
        XCTAssertFalse(
            segmentMenu.contains("primaryAction"),
            "clicking 分段 must open the menu; it must not adjust the boundary immediately"
        )
        XCTAssertTrue(segmentMenu.contains("openBoundaryEditor()"))
        XCTAssertTrue(
            segmentMenu.contains("viewModel.segments.count < 2"),
            "adjusting a boundary needs two segments"
        )
        XCTAssertTrue(
            segmentMenu.contains("点图标选择调整分段或整书重新分段")
        )
        XCTAssertTrue(segmentMenu.contains("prepareResegment()"))
        XCTAssertFalse(
            segmentMenu.contains(".readerChromeTextAction()"),
            "the 分段 popover trigger must not take the text-action buttonStyle"
        )
    }

    func testListenChevronSplitPlaysBriefOnIconClick() throws {
        let reader = try readerSource()
        let listen = reader
            .components(separatedBy: "private var listenStartIdx: Int")
            .last?
            .components(separatedBy: "private var originalSearchChromeControl")
            .first ?? ""
        XCTAssertTrue(listen.contains("listenTargetShowsOriginal"))
        XCTAssertTrue(listen.contains("ListenChromePolicy.isShowingOriginal"))
        XCTAssertFalse(
            listen.contains("if contentMode == .original"),
            "speaker must follow the visible panel, including per-segment 切换原文"
        )
        XCTAssertTrue(
            listen.contains("startListening(.original)"),
            "when the visible panel is original, the speaker must read raw_text"
        )
        XCTAssertTrue(listen.contains("ReaderChromeIconChevronSplit("))
        XCTAssertTrue(listen.contains("Button(\"听简要摘要\") { startListening(.summary) }"))
        XCTAssertTrue(listen.contains("Button(\"听完整摘要\") { startListening(.detailed) }"))
        XCTAssertTrue(
            listen.contains("startListening(.summary)"),
            "when the visible panel is summary, the speaker plays the brief summary"
        )
        XCTAssertTrue(
            listen.contains(".padding(.horizontal, 6)"),
            "the original speaker must keep the same padded hit target as the summary split"
        )
        XCTAssertFalse(
            listen.contains("primaryAction:"),
            "Menu+primaryAction hides 听完整摘要 behind a long-press"
        )
        XCTAssertFalse(
            listen.contains("lastSummaryMode"),
            "clicking 听 must not replay the last full-summary choice"
        )
        XCTAssertTrue(listen.contains("primaryHelp: \"听简要摘要\""))
        XCTAssertTrue(listen.contains("chevronHelp: \"选择听简要摘要或听完整摘要\""))

        let block = try source("Lumina/Features/Reader/SegmentReadingBlock.swift")
        XCTAssertTrue(
            block.contains("ListenChromePolicy.isShowingOriginal"),
            "the reading panel and the speaker must share one visible-layer rule"
        )

        let split = try source("Lumina/Features/Shared/ReaderChromeIconChevronSplit.swift")
        XCTAssertTrue(split.contains("chevron.down"))
        XCTAssertTrue(split.contains(".menuStyle(.borderlessButton)"))
        XCTAssertTrue(split.contains(".menuIndicator(.hidden)"))
        XCTAssertTrue(split.contains(".readerChromeIconAction()"))
        XCTAssertFalse(
            split.contains("primaryAction:"),
            "the icon must be a Button, not Menu+primaryAction"
        )
        let menuBlock = split.components(separatedBy: "Menu(content: menu)").last ?? ""
        XCTAssertFalse(
            menuBlock.contains(".buttonStyle"),
            "buttonStyle on the chevron Menu restyles NSMenuItems"
        )
    }

    func testReaderFeedInsetsNeverDependOnTheChrome() throws {
        let source = try readerSource()
        for edge in [".safeAreaInset(edge: .top", ".safeAreaInset(edge: .bottom"] {
            let insets = source.components(separatedBy: edge)
            XCTAssertGreaterThan(
                insets.count,
                1,
                "the reader feed must still reserve \(edge) insets"
            )
            for inset in insets.dropFirst() {
                let head = inset.prefix(900)
                XCTAssertFalse(
                    head.contains("toolbarVisible") || head.contains("barsVisible"),
                    "an inset that follows the chrome steals feed height and slides the text"
                )
            }
        }
    }

    func testReaderSummaryProgressInsetHasReservedHeight() throws {
        let source = try readerSource()
        let insets = source.components(separatedBy: ".safeAreaInset(edge: .top")
        let bannerInset = insets.first(where: { $0.contains("SummaryProgressBanner") }) ?? ""
        XCTAssertFalse(
            bannerInset.isEmpty,
            "the feed must still host the summary progress banner in a top inset"
        )
        XCTAssertTrue(
            bannerInset.contains("SummaryProgressBannerMetrics.reservedHeight"),
            "a banner whose height follows captions will slide the reading surface on every SSE tick"
        )
        let head = bannerInset.prefix(900)
        XCTAssertFalse(
            head.contains("padding(.vertical"),
            "vertical padding outside reservedHeight makes optional caption rows steal feed height"
        )
    }

    func testReaderBottomBarHostsSegmentNotesChat() throws {
        let reader = try readerSource()
        XCTAssertTrue(reader.contains("readerBottomBarOverlay"))
        XCTAssertTrue(reader.contains("if barsVisible"))

        let top = topChromeBarSource(reader)
        XCTAssertFalse(
            top.contains("toggleCoverPage(.segments)"),
            "the top bar is for book ops; the catalog belongs on the bottom bar"
        )
        XCTAssertFalse(top.contains("Button(\"笔记\")"))
        XCTAssertFalse(top.contains("Button(\"提问\")"))

        let bottom = bottomFunctionBarSource(reader)
        XCTAssertTrue(bottom.contains("title: \"段列表\""))
        XCTAssertTrue(bottom.contains("title: \"深聊\""))
        XCTAssertTrue(bottom.contains("title: \"笔记\""))
        XCTAssertTrue(bottom.contains("title: \"显示\""))
        let listIdx = try XCTUnwrap(bottom.range(of: "title: \"段列表\""))
        let chatIdx = try XCTUnwrap(bottom.range(of: "title: \"深聊\""))
        let notesIdx = try XCTUnwrap(bottom.range(of: "title: \"笔记\""))
        let displayIdx = try XCTUnwrap(bottom.range(of: "title: \"显示\""))
        XCTAssertLessThan(listIdx.lowerBound, chatIdx.lowerBound)
        XCTAssertLessThan(chatIdx.lowerBound, notesIdx.lowerBound)
        XCTAssertLessThan(notesIdx.lowerBound, displayIdx.lowerBound)
        XCTAssertTrue(bottom.contains("textformat.size"))
        XCTAssertTrue(bottom.contains("toggleCoverPage(.segments)"))
        XCTAssertTrue(bottom.contains("toggleOverlay(.notes)"))
        XCTAssertTrue(bottom.contains("toggleOverlay(.chat)"))
        XCTAssertTrue(bottom.contains("showAppearancePopover"))
        XCTAssertTrue(bottom.contains(".popover("))
    }

    func testReaderHasNoEdgeHoverChrome() throws {
        let reader = try readerSource()
        for banned in [
            "ReaderEdgeIcon",
            "EdgeHoverTracker",
            "edgeHotZone",
            "beginEdgePeek",
            "handleEdgePointer",
            "cancelEdgeDwell",
            "ReaderEdgeTarget",
            "pendingEdge",
            "dwellTask",
            "edgeDwellNanoseconds",
        ] {
            XCTAssertFalse(
                reader.contains(banned),
                "\(banned) brings back edge-dwell chrome"
            )
        }
    }

    func testReaderPaperStaysOnTheReadingSurface() throws {
        let reader = try readerSource()
        XCTAssertTrue(
            reader.contains(".environment(\\.readerPaper"),
            "the feed must inject readerPaper so body text can follow the page"
        )
        XCTAssertTrue(reader.contains("theme.readerPaper.page"))
        XCTAssertTrue(reader.contains("fontScale: theme.readingFontScale"))
        XCTAssertFalse(
            reader.contains("preferredColorScheme"),
            "paper is not the app appearance; the window color scheme stays in LuminaApp"
        )
        XCTAssertFalse(
            reader.contains("theme.appearance"),
            "choosing night paper must not flip ThemeManager.appearance"
        )
    }

    func testSegmentHeaderDoesNotScaleWithReadingFont() throws {
        let block = try source("Lumina/Features/Reader/SegmentReadingBlock.swift")
        let header = block.components(separatedBy: "private var segmentHeaderRow").last?
            .components(separatedBy: "private var resolvedAnchorText").first ?? ""
        XCTAssertFalse(
            header.contains("scaled("),
            "turn buttons and header metadata must keep a stable size when body type scales"
        )
    }

    func testSegmentBoundaryAdjustButtonIsCenteredAccent() throws {
        let block = try source("Lumina/Features/Reader/SegmentReadingBlock.swift")
        let separator = block.components(separatedBy: "private var segmentBoundarySeparator").last?
            .components(separatedBy: "private var showingSource").first ?? ""
        XCTAssertTrue(
            separator.contains("LuminaTheme.accent"),
            "the between-segment adjust control must use the product accent, not muted paper text"
        )
        XCTAssertFalse(
            separator.contains("paper.textSecondary"),
            "muted secondary text made the adjust control look like decoration"
        )
        XCTAssertEqual(
            separator.components(separatedBy: ".fill(paper.border)").count - 1,
            2,
            "a line on each side of the button keeps it in the middle of the boundary"
        )
        let firstLine = try XCTUnwrap(separator.range(of: ".fill(paper.border)"))
        let button = try XCTUnwrap(separator.range(of: "Button(action: onAdjustBoundary)"))
        XCTAssertLessThan(firstLine.lowerBound, button.lowerBound)
        XCTAssertNotNil(
            separator[button.upperBound...].range(of: ".fill(paper.border)"),
            "the second boundary line must follow the button so the icon sits on the divider, not at the trailing edge"
        )
    }

    func testBoundaryEditorUsesClickNotDrag() throws {
        let editor = try source("Lumina/Features/Reader/SegmentBoundaryEditor.swift")
        XCTAssertTrue(editor.contains("点击正文中要作为新分界的位置"))
        XCTAssertTrue(editor.contains("点「保存」才落库并重新摘要这两段"))
        XCTAssertTrue(editor.contains("Button(\"保存\")"))
        XCTAssertTrue(editor.contains("preview(atUTF16:"))
        XCTAssertFalse(editor.contains("点击后立即保存并重新摘要这两段"))
        XCTAssertTrue(editor.contains("characterIndexForInsertion"))
        XCTAssertTrue(editor.contains("NSScrollView"))
        XCTAssertFalse(editor.contains("上一处"))
        XCTAssertFalse(editor.contains("下一处"))
        XCTAssertFalse(editor.contains("DragGesture"))
    }

    func testWindowToolbarDoesNotFollowReaderChrome() throws {
        let content = try source("Lumina/ContentView.swift")
        XCTAssertFalse(
            content.contains("readerChromeVisible"),
            "driving window toolbar visibility from reader chrome resizes the content area on every blank click"
        )
    }

    func testDisableableControlStripsKeepTheirOwnClicks() throws {
        let block = try source("Lumina/Features/Reader/SegmentReadingBlock.swift")
        XCTAssertEqual(
            block.components(separatedBy: ".absorbsReaderChromeClicks()").count - 1,
            2,
            "the panel toggle strip and the segment turn strip both hold disabled "
                + "buttons, which are not hit-testable and would leak clicks to the chrome toggle"
        )
    }
}

/// Reading body text has to be selectable with the mouse: copying a phrase used
/// to require the panel's "复制" button, which takes the whole segment.
/// Selectable text swallows its own mouse events, so the click that shows and
/// hides the chrome has to be told apart from a selection.
final class ReaderBodyTextSelectionPolicyTests: XCTestCase {
    func testBareClickOnTextStillReachesTheChrome() {
        XCTAssertEqual(
            LuminaBodyTextClickPolicy.outcome(
                clickCount: 1,
                hadSelectionBefore: false,
                selectionLengthAfter: 0
            ),
            .plainClick
        )
    }

    func testDragThatPickedTextOutIsASelection() {
        XCTAssertEqual(
            LuminaBodyTextClickPolicy.outcome(
                clickCount: 1,
                hadSelectionBefore: false,
                selectionLengthAfter: 12
            ),
            .selection
        )
    }

    func testMultiClickIsASelectionEvenWhenItSelectedNothing() {
        for clickCount in [2, 3] {
            XCTAssertEqual(
                LuminaBodyTextClickPolicy.outcome(
                    clickCount: clickCount,
                    hadSelectionBefore: false,
                    selectionLengthAfter: 0
                ),
                .selection,
                "clickCount=\(clickCount) means the user is picking a word or line, not toggling chrome"
            )
        }
    }

    func testClickThatDropsASelectionOnlyDismissesIt() {
        XCTAssertEqual(
            LuminaBodyTextClickPolicy.outcome(
                clickCount: 1,
                hadSelectionBefore: true,
                selectionLengthAfter: 0
            ),
            .dismissSelection,
            "the click that clears a selection must not also flip the chrome"
        )
    }

    func testSelectionMenuNeedsANonBlankQuote() {
        XCTAssertFalse(
            LuminaSelectionActionPolicy.shouldShowMenu(
                clickOutcome: .plainClick,
                selectedText: "有字也不弹"
            )
        )
        XCTAssertFalse(
            LuminaSelectionActionPolicy.shouldShowMenu(
                clickOutcome: .dismissSelection,
                selectedText: "有字也不弹"
            )
        )
        XCTAssertFalse(
            LuminaSelectionActionPolicy.shouldShowMenu(
                clickOutcome: .selection,
                selectedText: "   \n"
            ),
            "double-click is a selection to the chrome, but a blank quote must not raise the menu"
        )
        XCTAssertEqual(
            LuminaSelectionActionPolicy.capturedQuote(from: "  反向传播  "),
            "反向传播"
        )
        XCTAssertTrue(
            LuminaSelectionActionPolicy.shouldShowMenu(
                clickOutcome: .selection,
                selectedText: "  反向传播  "
            )
        )
    }

    func testSelectionDoesNotToggleChromeEvenWhenTheMenuShows() {
        XCTAssertEqual(
            LuminaBodyTextClickPolicy.outcome(
                clickCount: 1,
                hadSelectionBefore: false,
                selectionLengthAfter: 8
            ),
            .selection
        )
        XCTAssertNotEqual(
            LuminaBodyTextClickPolicy.outcome(
                clickCount: 1,
                hadSelectionBefore: false,
                selectionLengthAfter: 8
            ),
            .plainClick,
            "a real selection must not be treated as a chrome toggle"
        )
    }

    private func source(_ relativePath: String) throws -> String {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()  // Unit
            .deletingLastPathComponent()  // LuminaTests
            .deletingLastPathComponent()  // macos
        return try String(
            contentsOf: macosRoot.appendingPathComponent(relativePath),
            encoding: .utf8
        )
    }

    func testBodyTextStaysSelectableAndCopyable() throws {
        let view = try source("Lumina/Features/Shared/SelectableTextView.swift")
        XCTAssertTrue(
            view.contains("textView.isSelectable = true"),
            "reader body text must stay mouse-selectable so a phrase can be copied without the whole segment"
        )
        XCTAssertFalse(
            view.contains("textView.isSelectable = false"),
            "isSelectable = false is what forced users through the copy-everything button"
        )
        for banned in ["becomeFirstResponder() -> Bool { false }", "acceptsFirstResponder: Bool { false }"] {
            XCTAssertFalse(
                view.contains(banned),
                "\(banned) keeps the text view out of the responder chain, so Cmd+C cannot reach the selection"
            )
        }
    }

    func testPlainClicksTravelThroughThePolicyAndNotAMouseMonitor() throws {
        let view = try source("Lumina/Features/Shared/SelectableTextView.swift")
        XCTAssertTrue(
            view.contains("LuminaBodyTextClickPolicy.outcome"),
            "the text view must classify its own mouse-down instead of guessing"
        )
        XCTAssertFalse(
            view.contains("addLocalMonitorForEvents"),
            "a global mouse monitor is the control-hit guessing that made every button toggle the chrome"
        )

        let reader = try source("Lumina/Features/Reader/ReaderView.swift")
        XCTAssertTrue(
            reader.contains(".onReaderBodyTextPlainClick(toggleChromeOnBlankClick)"),
            "the reading surface must hand selectable text a sink for clicks that were not selections"
        )
        XCTAssertTrue(
            reader.contains("readerSelectionNoteContext"),
            "the feed must supply book/segment note context so 写想法 can save without opening the drawer"
        )
        XCTAssertTrue(
            reader.contains("readerSelectionNoteAnchor"),
            "each segment block must pin notes to the segment that owns the selected text"
        )
        XCTAssertTrue(
            reader.contains("LuminaSelectionActionPopover.dismiss()"),
            "leaving the reader or jumping segments must close the selection popover"
        )
    }

    func testSelectionMenuIsRaisedAfterMouseUpAndDoesNotBlockTheUI() throws {
        let view = try source("Lumina/Features/Shared/SelectableTextView.swift")
        let mouseDown = view
            .components(separatedBy: "override func mouseDown").last?
            .components(separatedBy: "override func viewDidMoveToWindow").first ?? ""
        XCTAssertTrue(
            mouseDown.contains("LuminaSelectionActionPolicy.shouldShowMenu"),
            "the menu must use the quote policy, not appear on every classified selection"
        )
        XCTAssertTrue(
            mouseDown.contains("LuminaSelectionActionPopover.present"),
            "mouse-up after a selection should present the copy / write-idea popover"
        )
        XCTAssertFalse(
            mouseDown.contains("invalidateIntrinsicContentSize"),
            "selection must not relayout CJK body text"
        )
        XCTAssertFalse(
            mouseDown.contains("createNote"),
            "mouse-down must not hit /notes synchronously"
        )

        let bar = try source("Lumina/Features/Reader/ReaderSelectionActionBar.swift")
        XCTAssertTrue(
            bar.contains("Task {"),
            "saving a thought must be async so the reader stays tappable"
        )
        XCTAssertTrue(bar.contains("createNote("))
        XCTAssertTrue(
            bar.contains("quote: self.quote") || bar.contains("quote: quote"),
            "the saved note must keep the selected phrase as quote"
        )
    }
}

/// A 1Hz `@Published` clock on the reader view model rebuilds the window
/// toolbar and every `.help()` control. AppKit then re-shows Help Tags and
/// auto-dismisses them on the next tick.
final class ReaderHelpTooltipPolicyTests: XCTestCase {
    func testShouldApply_skipsUnchangedToolbarVisibility() {
        XCTAssertTrue(WindowToolbarVisibilityPolicy.shouldApply(applied: nil, desired: true))
        XCTAssertTrue(WindowToolbarVisibilityPolicy.shouldApply(applied: false, desired: true))
        XCTAssertTrue(WindowToolbarVisibilityPolicy.shouldApply(applied: true, desired: false))
        XCTAssertFalse(WindowToolbarVisibilityPolicy.shouldApply(applied: true, desired: true))
        XCTAssertFalse(WindowToolbarVisibilityPolicy.shouldApply(applied: false, desired: false))
    }

    func testReaderDoesNotPublishOneHertzHelpTagClock() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let reader = try String(
            contentsOf: macosRoot.appendingPathComponent("Lumina/Features/Reader/ReaderView.swift"),
            encoding: .utf8
        )
        for banned in ["sidebarClock", "sidebarClockTask", "setSidebarVisible", "statusClock"] {
            XCTAssertFalse(
                reader.contains(banned),
                "\(banned) republishes the whole reader every second and retriggers button help tags"
            )
        }
        let models = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Features/Reader/SegmentSidebarModels.swift"
            ),
            encoding: .utf8
        )
        XCTAssertFalse(
            models.contains("TimelineView"),
            "catalog first line must not host live summarize captions"
        )
        let reading = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Features/Reader/SegmentReadingBlock.swift"
            ),
            encoding: .utf8
        )
        XCTAssertTrue(
            reading.contains("TimelineView(.periodic(from: .now, by: 1))"),
            "reading-block live captions must tick locally via TimelineView, not a view-model clock"
        )
    }

    func testWindowToolbarVisibility_gatesReapply() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let source = try String(
            contentsOf: macosRoot.appendingPathComponent("Lumina/Design/WindowToolbarVisibility.swift"),
            encoding: .utf8
        )
        XCTAssertTrue(source.contains("WindowToolbarVisibilityPolicy.shouldApply"))
        XCTAssertTrue(source.contains("setDesiredVisible"))
        XCTAssertFalse(
            source.contains("didSet { applyVisibility() }"),
            "didSet on every SwiftUI updateNSView retriggers help tags"
        )
    }
}
