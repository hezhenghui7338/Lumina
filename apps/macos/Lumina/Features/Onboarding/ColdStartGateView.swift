import AppKit
import SwiftUI

struct ColdStartGateView: View {
    let phases: ColdStartPhaseSnapshot
    let startedAt: Date

    var body: some View {
        TimelineView(.periodic(from: startedAt, by: 1)) { context in
            VStack(spacing: 28) {
                Spacer()
                Text("Lumina")
                    .font(.system(size: 36, weight: .semibold, design: .rounded))
                    .foregroundStyle(LuminaTheme.textPrimary)
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
        let done = state == .done || (kind == .news && state == .failed)
        HStack(spacing: 12) {
            Image(systemName: done ? "checkmark.circle.fill" : "circle")
                .foregroundStyle(done ? Color.accentColor : LuminaTheme.textSecondary)
                .font(.title3)
            Text(
                ColdStartReadiness.rowLabel(
                    kind: kind,
                    state: state,
                    newsFailed: phases.news == .failed
                )
            )
            .font(.body.weight(done ? .regular : .medium))
            .foregroundStyle(LuminaTheme.textPrimary)
            if state == .running {
                ProgressView()
                    .controlSize(.small)
            }
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .combine)
    }

    private func state(for kind: ColdStartRowKind) -> ColdStartPhaseState {
        switch kind {
        case .engine: return phases.engine
        case .data: return phases.data
        case .cache: return phases.cache
        case .news: return phases.news
        }
    }
}
