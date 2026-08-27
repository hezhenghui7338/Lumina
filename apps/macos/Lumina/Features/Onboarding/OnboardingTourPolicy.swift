import Foundation

enum OnboardingTourStep: String, Equatable, CaseIterable {
    case importBook
    case openBook
    case configureAPI
    case summarize
    case toggleMode
    case chat
    case notes
    case readerOverview
}

enum OnboardingTourSurface: Equatable {
    case library
    case settings
    case reader
}

enum TourAnchorID: Hashable {
    case importButton
    case bookshelf
    case apiResources
    case summarize
    case modePicker
    case chat
    case notes
}

struct OnboardingTourCopy: Equatable {
    var title: String
    var body: String
}

enum OnboardingTourPolicy {
    static func steps(hasOpenableBook: Bool) -> [OnboardingTourStep] {
        if hasOpenableBook {
            return [
                .importBook, .openBook, .configureAPI,
                .summarize, .toggleMode, .chat, .notes,
            ]
        }
        return [.importBook, .openBook, .configureAPI, .readerOverview]
    }

    static func resolve(
        _ step: OnboardingTourStep,
        hasOpenableBook: Bool
    ) -> OnboardingTourStep {
        let visible = steps(hasOpenableBook: hasOpenableBook)
        if visible.contains(step) { return step }
        switch step {
        case .summarize, .toggleMode, .chat, .notes:
            return hasOpenableBook ? .summarize : .readerOverview
        case .readerOverview:
            return hasOpenableBook ? .summarize : .readerOverview
        default:
            return visible[0]
        }
    }

    static func next(
        after step: OnboardingTourStep,
        hasOpenableBook: Bool
    ) -> OnboardingTourStep? {
        let visible = steps(hasOpenableBook: hasOpenableBook)
        let current = resolve(step, hasOpenableBook: hasOpenableBook)
        guard let idx = visible.firstIndex(of: current) else { return visible.first }
        let nextIdx = visible.index(after: idx)
        return nextIdx < visible.endIndex ? visible[nextIdx] : nil
    }

    static func previous(
        before step: OnboardingTourStep,
        hasOpenableBook: Bool
    ) -> OnboardingTourStep? {
        let visible = steps(hasOpenableBook: hasOpenableBook)
        let current = resolve(step, hasOpenableBook: hasOpenableBook)
        guard let idx = visible.firstIndex(of: current), idx > visible.startIndex else {
            return nil
        }
        return visible[visible.index(before: idx)]
    }

    static func surface(for step: OnboardingTourStep) -> OnboardingTourSurface {
        switch step {
        case .importBook, .openBook, .readerOverview:
            return .library
        case .configureAPI:
            return .settings
        case .summarize, .toggleMode, .chat, .notes:
            return .reader
        }
    }

    static func anchor(
        for step: OnboardingTourStep,
        hasOpenableBook: Bool
    ) -> TourAnchorID {
        switch step {
        case .importBook:
            return hasOpenableBook ? .bookshelf : .importButton
        case .openBook, .readerOverview:
            return .bookshelf
        case .configureAPI:
            return .apiResources
        case .summarize:
            return .summarize
        case .toggleMode:
            return .modePicker
        case .chat:
            return .chat
        case .notes:
            return .notes
        }
    }

    static func copy(
        for step: OnboardingTourStep,
        hasOpenableBook: Bool
    ) -> OnboardingTourCopy {
        switch step {
        case .importBook:
            if hasOpenableBook {
                return OnboardingTourCopy(
                    title: "导入书籍",
                    body: "点右上角导入图标，或把文件拖到书架上。"
                )
            }
            return OnboardingTourCopy(
                title: "导入书籍",
                body: "点这里或把文件拖到书架，支持 PDF、EPUB、TXT 等。"
            )
        case .openBook:
            return OnboardingTourCopy(
                title: "选择书籍阅读",
                body: "点一本书打开阅读器，第一段就绪就能读。"
            )
        case .configureAPI:
            return OnboardingTourCopy(
                title: "配置摘要 API",
                body: "在此添加本机 Ollama 或外部 API Key，摘要与深聊都会用到。"
            )
        case .summarize:
            return OnboardingTourCopy(
                title: "点击摘要",
                body: "点顶栏摘要图标，开始为各段生成摘要。"
            )
        case .toggleMode:
            return OnboardingTourCopy(
                title: "切换摘要与原文",
                body: "用顶栏「摘要 | 原文」随时对照。"
            )
        case .chat:
            return OnboardingTourCopy(
                title: "深聊",
                body: "底栏「深聊」可针对当前段追问。"
            )
        case .notes:
            return OnboardingTourCopy(
                title: "笔记",
                body: "底栏「笔记」记下想法，并挂在当前段上。"
            )
        case .readerOverview:
            return OnboardingTourCopy(
                title: "阅读器里还可以",
                body: "打开书后：顶栏点摘要、切换摘要与原文；底栏可深聊和记笔记。"
            )
        }
    }

    static func isFirst(_ step: OnboardingTourStep, hasOpenableBook: Bool) -> Bool {
        steps(hasOpenableBook: hasOpenableBook).first == resolve(step, hasOpenableBook: hasOpenableBook)
    }

    static func isLast(_ step: OnboardingTourStep, hasOpenableBook: Bool) -> Bool {
        steps(hasOpenableBook: hasOpenableBook).last == resolve(step, hasOpenableBook: hasOpenableBook)
    }

    static func primaryButtonTitle(
        for step: OnboardingTourStep,
        hasOpenableBook: Bool
    ) -> String {
        isLast(step, hasOpenableBook: hasOpenableBook) ? "知道了" : "下一步"
    }

    static func index(of step: OnboardingTourStep, hasOpenableBook: Bool) -> Int {
        let visible = steps(hasOpenableBook: hasOpenableBook)
        let current = resolve(step, hasOpenableBook: hasOpenableBook)
        return visible.firstIndex(of: current) ?? 0
    }

    static func count(hasOpenableBook: Bool) -> Int {
        steps(hasOpenableBook: hasOpenableBook).count
    }
}
