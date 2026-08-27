import Foundation

@MainActor
final class OnboardingTourController: ObservableObject {
    @Published private(set) var isActive = false
    @Published private(set) var step: OnboardingTourStep?
    @Published private(set) var completed = false
    @Published private(set) var hasOpenableBook = false
    @Published private(set) var firstOpenableBookId: String?

    var copy: OnboardingTourCopy {
        guard let step else {
            return OnboardingTourCopy(title: "", body: "")
        }
        return OnboardingTourPolicy.copy(for: step, hasOpenableBook: hasOpenableBook)
    }

    var isFirst: Bool {
        guard let step else { return true }
        return OnboardingTourPolicy.isFirst(step, hasOpenableBook: hasOpenableBook)
    }

    var isLast: Bool {
        guard let step else { return true }
        return OnboardingTourPolicy.isLast(step, hasOpenableBook: hasOpenableBook)
    }

    var primaryButtonTitle: String {
        guard let step else { return "知道了" }
        return OnboardingTourPolicy.primaryButtonTitle(
            for: step,
            hasOpenableBook: hasOpenableBook
        )
    }

    var stepIndex: Int {
        guard let step else { return 0 }
        return OnboardingTourPolicy.index(of: step, hasOpenableBook: hasOpenableBook)
    }

    var stepCount: Int {
        OnboardingTourPolicy.count(hasOpenableBook: hasOpenableBook)
    }

    var surface: OnboardingTourSurface? {
        guard let step else { return nil }
        return OnboardingTourPolicy.surface(for: step)
    }

    var anchorID: TourAnchorID? {
        guard let step else { return nil }
        return OnboardingTourPolicy.anchor(for: step, hasOpenableBook: hasOpenableBook)
    }

    func start() {
        guard !isActive, !completed else { return }
        isActive = true
        step = OnboardingTourPolicy.steps(hasOpenableBook: hasOpenableBook).first
    }

    func syncLibrary(hasOpenableBook: Bool, firstBookId: String?) {
        self.hasOpenableBook = hasOpenableBook
        firstOpenableBookId = firstBookId
        guard isActive, let step else { return }
        self.step = OnboardingTourPolicy.resolve(step, hasOpenableBook: hasOpenableBook)
    }

    func advance() {
        guard isActive, let step else { return }
        if let next = OnboardingTourPolicy.next(after: step, hasOpenableBook: hasOpenableBook) {
            self.step = next
        } else {
            finish()
        }
    }

    func back() {
        guard isActive, let step else { return }
        if let previous = OnboardingTourPolicy.previous(
            before: step,
            hasOpenableBook: hasOpenableBook
        ) {
            self.step = previous
        }
    }

    func skip() {
        finish()
    }

    func finish() {
        isActive = false
        step = nil
        completed = true
    }
}
