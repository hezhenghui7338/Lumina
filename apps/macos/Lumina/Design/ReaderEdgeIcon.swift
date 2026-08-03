import SwiftUI

/// Floating edge affordance for reader panels — zero layout footprint.
struct ReaderEdgeIcon: View {
    let systemImage: String
    let label: String
    let isActive: Bool
    let action: () -> Void

    private let size: CGFloat = 36

    var body: some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(.system(size: 15, weight: .semibold))
                .symbolVariant(isActive ? .fill : .none)
                .foregroundStyle(isActive ? LuminaTheme.accent : LuminaTheme.textPrimary)
                .frame(width: size, height: size)
                .background(.ultraThinMaterial)
                .clipShape(RoundedRectangle(cornerRadius: 10))
                .overlay {
                    RoundedRectangle(cornerRadius: 10)
                        .stroke(
                            isActive ? LuminaTheme.accent.opacity(0.55) : LuminaTheme.border.opacity(0.6),
                            lineWidth: isActive ? 1.5 : 1
                        )
                }
                .shadow(color: .black.opacity(0.08), radius: 6, x: 0, y: 2)
        }
        .buttonStyle(.plain)
        .help(label)
        .accessibilityLabel(label)
        .accessibilityIdentifier("lumina.reader.control.edgeIcon.\(label)")
    }
}
