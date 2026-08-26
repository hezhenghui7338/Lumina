import SwiftUI

enum ListenMiniBarMetrics {
    static let height: CGFloat = 44
}

struct ListenMiniBar: View {
    @ObservedObject var session: ListenSession
    var onClose: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            if let notice = session.skipNotice ?? session.statusMessage {
                Text(notice)
                    .font(.system(size: 11))
                    .foregroundStyle(LuminaTheme.textSecondary)
                    .lineLimit(1)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 12)
                    .padding(.top, 4)
            }
            HStack(spacing: 10) {
                Button(action: { session.skipBack() }) {
                    Image(systemName: "backward.fill")
                }
                .help("上一段")
                .disabled(!session.isActive)

                Button(action: { session.togglePause() }) {
                    Image(systemName: session.isPaused || !session.isPlaying ? "play.fill" : "pause.fill")
                }
                .help(session.isPaused || !session.isPlaying ? "继续" : "暂停")
                .disabled(!session.isActive)

                Button(action: { session.skipForward() }) {
                    Image(systemName: "forward.fill")
                }
                .help("下一段")
                .disabled(!session.isActive)

                if session.isLoading {
                    ProgressView()
                        .controlSize(.small)
                }

                Text(title)
                    .font(ReaderChromeBarMetrics.labelFont)
                    .lineLimit(1)
                    .frame(maxWidth: .infinity, alignment: .leading)

                Menu {
                    ForEach(ListenPreferences.rates, id: \.self) { value in
                        Button("\(formatRate(value))×") {
                            session.setRate(value)
                        }
                    }
                } label: {
                    Text("\(formatRate(session.rate))×")
                        .font(ReaderChromeBarMetrics.labelFont)
                        .frame(minWidth: 36)
                }
                .help("倍速")

                Button(action: onClose) {
                    Image(systemName: "xmark")
                }
                .help("停止朗读")
            }
            .buttonStyle(.borderless)
            .padding(.horizontal, 12)
            .frame(height: ListenMiniBarMetrics.height)
        }
        .background(.ultraThinMaterial)
        .overlay(alignment: .top) { Divider() }
        .absorbsReaderChromeClicks()
        .accessibilityIdentifier("lumina.reader.listen.miniBar")
    }

    private var title: String {
        let mode = session.mode.shortLabel
        if session.segmentLabel.isEmpty {
            return "听\(mode) · 段 \(session.currentIdx + 1)"
        }
        return "听\(mode) · \(session.segmentLabel)"
    }

    private func formatRate(_ value: Float) -> String {
        if abs(value - 1.0) < 0.01 { return "1" }
        if abs(value - value.rounded()) < 0.01 {
            return String(Int(value.rounded()))
        }
        return String(format: "%g", value)
    }
}
