import Foundation

enum ImportConflictChoice: String, Equatable {
    case overwrite
    case skip
    case skipRemainingDuplicates
    case cancelRemaining
}

struct ImportConflictDecision: Equatable {
    var overwriteCurrent: Bool
    var skipRemainingDuplicates: Bool
    var continueQueue: Bool
}

enum ImportConflictPolicy {
    static func shouldPrompt(skipRemainingDuplicates: Bool) -> Bool {
        !skipRemainingDuplicates
    }

    static func showsSkipRemaining(pendingCount: Int) -> Bool {
        pendingCount > 0
    }

    static func decision(for choice: ImportConflictChoice) -> ImportConflictDecision {
        switch choice {
        case .overwrite:
            return ImportConflictDecision(
                overwriteCurrent: true,
                skipRemainingDuplicates: false,
                continueQueue: true
            )
        case .skip:
            return ImportConflictDecision(
                overwriteCurrent: false,
                skipRemainingDuplicates: false,
                continueQueue: true
            )
        case .skipRemainingDuplicates:
            return ImportConflictDecision(
                overwriteCurrent: false,
                skipRemainingDuplicates: true,
                continueQueue: true
            )
        case .cancelRemaining:
            return ImportConflictDecision(
                overwriteCurrent: false,
                skipRemainingDuplicates: false,
                continueQueue: false
            )
        }
    }

    static func dialogMessage(title: String, remainingCount: Int) -> String {
        let base = "《\(title)》已在书库中。覆盖将删除原有摘要、笔记，并重新分段与摘要"
        if remainingCount <= 0 {
            return "\(base)。"
        }
        return "\(base)；跳过会继续导入其他书籍。「跳过剩下所有」会跳过本书及后续重复书，不再询问，但仍导入新书。"
    }
}
