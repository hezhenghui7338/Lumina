import AppKit
import SwiftUI

struct ColdStartGateView: View {
    let phases: ColdStartPhaseSnapshot
    let startedAt: Date

    var body: some View {
        TimelineView(.periodic(from: startedAt, by: 1)) { context in
            VStack(spacing: 28) {
                Spacer()
                Image("LuminaLogo")
                    .resizable()
                    .scaledToFit()
                    .frame(maxWidth: 280)
                    .accessibilityLabel("Lumina")
                Text("正在准备…")
                    .font(.title3)
                    .foregroundStyle(LuminaTheme.textSecondary)

                VStack(alignment: .leading, spacing: 14) {
                    ForEach(ColdStartRowKind.allCases, id: \.self) { kind in
                        row(kind)
                    }
                }
                .frame(maxWidth: 360, alignment: .leading)
                .padding(.horizontal, 24)

                Text(elapsedLabel(at: context.date))
                    .font(.caption)
                    .foregroundStyle(LuminaTheme.textSecondary)
                    .monospacedDigit()

                Button("退出") {
                    NSApplication.shared.terminate(nil)
                }
                .buttonStyle(.bordered)
                Spacer()
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(LuminaTheme.background)
        }
    }

    private func elapsedLabel(at date: Date) -> String {
        let seconds = max(0, Int(date.timeIntervalSince(startedAt)))
        return "已用时 \(seconds) 秒"
    }

    @ViewBuilder
    private func row(_ kind: ColdStartRowKind) -> some View {
        let state = state(for: kind)
        let done = state == .done
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 12) {
                Image(systemName: done ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(done ? Color.accentColor : LuminaTheme.textSecondary)
                    .font(.title3)
                Text(
                    ColdStartReadiness.rowLabel(
                        kind: kind,
                        state: state,
                        cacheDetail: phases.cacheDetail
                    )
                )
                .font(.body.weight(done ? .regular : .medium))
                .foregroundStyle(LuminaTheme.textPrimary)
                if state == .running && (kind != .cache || phases.cacheProgress == nil) {
                    ProgressView()
                        .controlSize(.small)
                }
                Spacer(minLength: 0)
                if kind == .cache, state == .running, let p = phases.cacheProgress {
                    Text("\(Int(min(1.0, max(0.0, p)) * 100))%")
                        .font(.caption)
                        .foregroundStyle(LuminaTheme.textSecondary)
                        .monospacedDigit()
                }
            }
            if kind == .cache, state == .running, let p = phases.cacheProgress {
                ProgressView(value: min(1.0, max(0.0, p)), total: 1.0)
                    .progressViewStyle(.linear)
                    .tint(Color.accentColor)
                    .padding(.leading, 32)
            }
        }
        .accessibilityElement(children: .combine)
    }

    private func state(for kind: ColdStartRowKind) -> ColdStartPhaseState {
        switch kind {
        case .engine: return phases.engine
        case .data: return phases.data
        case .cache: return phases.cache
        }
    }
}
