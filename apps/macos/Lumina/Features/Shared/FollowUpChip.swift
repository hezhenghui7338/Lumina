import SwiftUI

/// Tappable follow-up question chip used in segment summaries and news deep-read.
struct FollowUpChip: View {
    let text: String
    let index: Int

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Text("\(index).")
                .font(.system(size: LuminaTheme.summaryBulletSize, weight: .medium))
                .foregroundStyle(LuminaTheme.accent)
                .frame(minWidth: 16, alignment: .trailing)
            Text(text)
                .font(.system(size: LuminaTheme.summaryBulletSize, weight: .regular))
                .foregroundStyle(LuminaTheme.textPrimary)
                .lineSpacing(LuminaTheme.summaryBulletLineSpacing)
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(LuminaTheme.accentMuted.opacity(0.35))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(LuminaTheme.accent.opacity(0.25), lineWidth: 1)
        )
    }
}
