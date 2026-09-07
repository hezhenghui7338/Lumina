import Foundation

enum UsageGuideCopy {
    static let title = "使用指南"

    struct Item: Equatable, Identifiable {
        var id: String { title }
        let title: String
        let body: String
    }

    static let items: [Item] = [
        Item(title: "导入", body: "书库点「导入」，或把文件拖到书架。"),
        Item(title: "阅读", body: "点书进入。点空白显隐顶栏与底栏。"),
        Item(title: "摘要 / 原文", body: "顶栏切换。默认看摘要，随时回原文。"),
        Item(title: "听", body: "顶栏「听」总结或原文；播放中可换段、倍速。"),
        Item(title: "深聊", body: "底栏「深聊」；回答里的段号可跳回原文。"),
        Item(title: "查找", body: "书内 ⌘F；跨书笔记与摘要 ⌘K。"),
        Item(title: "开始摘要", body: "导入默认只分段；打开书后点「开始摘要」。引擎与 Ollama 在「设置」。"),
    ]
}

enum UsageGuidePresentationPolicy {
    static var shouldResetOnboardingOnReopen: Bool { false }
    static var shouldPresentGuideAfterFirstRun: Bool { true }

    static func marksOnboardingComplete(reopenOnly: Bool) -> Bool {
        !reopenOnly
    }
}
