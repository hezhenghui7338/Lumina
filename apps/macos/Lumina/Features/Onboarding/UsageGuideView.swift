import SwiftUI

struct UsageGuideView: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(UsageGuideCopy.title)
                .font(.title2.bold())
            ForEach(UsageGuideCopy.items) { item in
                VStack(alignment: .leading, spacing: 4) {
                    Text(item.title)
                        .font(.headline)
                    Text(item.body)
                        .font(.callout)
                        .foregroundStyle(LuminaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct UsageGuideSheet: View {
    @Binding var isPresented: Bool

    var body: some View {
        VStack(spacing: 20) {
            ScrollView {
                UsageGuideView()
            }
            HStack {
                Spacer()
                Button("好") { isPresented = false }
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(32)
        .frame(width: 520, height: 520)
    }
}
