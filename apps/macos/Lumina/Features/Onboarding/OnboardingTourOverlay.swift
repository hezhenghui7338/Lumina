import SwiftUI

struct TourAnchorPreferenceKey: PreferenceKey {
    static var defaultValue: [TourAnchorID: Anchor<CGRect>] = [:]

    static func reduce(
        value: inout [TourAnchorID: Anchor<CGRect>],
        nextValue: () -> [TourAnchorID: Anchor<CGRect>]
    ) {
        value.merge(nextValue(), uniquingKeysWith: { _, new in new })
    }
}

private struct TourCardSizeKey: PreferenceKey {
    static var defaultValue: CGSize = .zero
    static func reduce(value: inout CGSize, nextValue: () -> CGSize) {
        let next = nextValue()
        if next != .zero { value = next }
    }
}

struct SpotlightHoleShape: Shape {
    var hole: CGRect?

    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.addRect(rect)
        if let hole {
            path.addRoundedRect(in: hole, cornerSize: CGSize(width: 8, height: 8))
        }
        return path
    }
}

struct OnboardingTourOverlay: View {
    let hole: CGRect?
    let title: String
    let bodyText: String
    let stepIndex: Int
    let stepCount: Int
    let isFirst: Bool
    let primaryTitle: String
    let onBack: () -> Void
    let onNext: () -> Void
    let onSkip: () -> Void

    @State private var cardSize: CGSize = CGSize(width: 320, height: 180)

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .topLeading) {
                SpotlightHoleShape(hole: hole)
                    .fill(Color.black.opacity(0.45), style: FillStyle(eoFill: true))
                    .allowsHitTesting(false)
                    .ignoresSafeArea()

                if let hole {
                    RoundedRectangle(cornerRadius: 8)
                        .strokeBorder(LuminaTheme.accent, lineWidth: 2)
                        .frame(width: hole.width, height: hole.height)
                        .offset(x: hole.minX, y: hole.minY)
                        .allowsHitTesting(false)
                }

                card
                    .offset(cardOffset(in: geo.size))
            }
        }
        .onPreferenceChange(TourCardSizeKey.self) { cardSize = $0 }
    }

    private var card: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(title)
                    .font(.headline)
                Spacer()
                Text("\(stepIndex + 1) / \(stepCount)")
                    .font(.caption)
                    .foregroundStyle(LuminaTheme.textSecondary)
            }
            Text(bodyText)
                .font(.callout)
                .foregroundStyle(LuminaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)

            HStack {
                Button("跳过引导", action: onSkip)
                    .font(.caption)
                Spacer()
                if !isFirst {
                    Button("上一步", action: onBack)
                }
                Button(primaryTitle, action: onNext)
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(16)
        .frame(width: 320, alignment: .leading)
        .background(LuminaTheme.surface, in: RoundedRectangle(cornerRadius: 12))
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .strokeBorder(LuminaTheme.border)
        )
        .shadow(color: .black.opacity(0.16), radius: 12, y: 4)
        .background(
            GeometryReader { proxy in
                Color.clear.preference(key: TourCardSizeKey.self, value: proxy.size)
            }
        )
    }

    private func cardOffset(in size: CGSize) -> CGSize {
        let width = max(cardSize.width, 1)
        let height = max(cardSize.height, 1)
        let margin: CGFloat = 16
        let gap: CGFloat = 12
        let x: CGFloat
        let y: CGFloat
        if let hole {
            x = min(
                max(margin, hole.midX - width / 2),
                max(margin, size.width - width - margin)
            )
            let below = hole.maxY + gap
            if below + height + margin <= size.height {
                y = below
            } else {
                y = max(margin, hole.minY - gap - height)
            }
        } else {
            x = (size.width - width) / 2
            y = (size.height - height) / 2
        }
        return CGSize(width: x, height: y)
    }
}

extension View {
    func tourAnchor(_ id: TourAnchorID) -> some View {
        anchorPreference(key: TourAnchorPreferenceKey.self, value: .bounds) { [id: $0] }
    }
}
