import AppKit
import SwiftUI

/// Brand splash overlay while product readiness completes (PRD §3.5).
struct ColdStartGateView: View {
    let phases: ColdStartPhaseSnapshot
    let startedAt: Date
    var launchError: String? = nil
    var onRetry: (() -> Void)? = nil

    var body: some View {
        TimelineView(.periodic(from: startedAt, by: 1)) { context in
            let elapsed = max(0, context.date.timeIntervalSince(startedAt))
            let failed = launchError.map { !$0.isEmpty } ?? false
            let showDetail = failed
                || ColdStartReadiness.shouldRevealTechnicalDetail(elapsedSeconds: elapsed)
            ZStack {
                Rectangle()
                    .fill(.ultraThinMaterial)
                    .overlay(LuminaTheme.background.opacity(0.55))
                    .ignoresSafeArea()

                VStack(spacing: 28) {
                    Spacer(minLength: 0)

                    ColdStartBouncingLogo()

                    if showDetail {
                        VStack(spacing: 10) {
                            if failed, let launchError {
                                Text(launchError)
                                    .font(.callout)
                                    .foregroundStyle(LuminaTheme.textSecondary)
                                    .multilineTextAlignment(.center)
                            } else {
                                Text(
                                    ColdStartReadiness.technicalDetail(
                                        phases,
                                        launchError: launchError
                                    )
                                )
                                .font(.caption)
                                .foregroundStyle(LuminaTheme.textSecondary)
                                .multilineTextAlignment(.center)
                            }

                            Text(elapsedLabel(seconds: Int(elapsed)))
                                .font(.caption2)
                                .foregroundStyle(LuminaTheme.textSecondary.opacity(0.85))
                                .monospacedDigit()

                            HStack(spacing: 12) {
                                if failed, let onRetry {
                                    Button("重试") { onRetry() }
                                        .buttonStyle(.borderedProminent)
                                }
                                Button("退出") {
                                    NSApplication.shared.terminate(nil)
                                }
                                .buttonStyle(.bordered)
                            }
                        }
                        .frame(maxWidth: 360)
                        .transition(.opacity)
                    }

                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 32)
            }
            .animation(.easeInOut(duration: 0.25), value: showDetail)
        }
        .accessibilityElement(children: .contain)
    }

    private func elapsedLabel(seconds: Int) -> String {
        "已用时 \(seconds) 秒"
    }
}

/// Soft bounce with a landing puddle centered directly under the logo.
private struct ColdStartBouncingLogo: View {
    @State private var airborne = false

    var body: some View {
        ZStack(alignment: .bottom) {
            Image("LuminaLogo")
                .resizable()
                .interpolation(.high)
                .scaledToFit()
                .frame(maxWidth: 220)
                .scaleEffect(x: airborne ? 1.0 : 1.04, y: airborne ? 1.0 : 0.94, anchor: .bottom)
                .offset(y: airborne ? -22 : 0)
                .shadow(
                    color: Color.black.opacity(airborne ? 0.08 : 0.16),
                    radius: airborne ? 16 : 7,
                    y: airborne ? 12 : 3
                )
                .accessibilityLabel("Lumina")
                .padding(.bottom, 14)

            // Landing spot: sits on the ZStack bottom center (logo正下方).
            ZStack {
                Ellipse()
                    .fill(
                        RadialGradient(
                            colors: [
                                Color.accentColor.opacity(airborne ? 0.08 : 0.28),
                                Color.accentColor.opacity(0.0),
                            ],
                            center: .center,
                            startRadius: 2,
                            endRadius: airborne ? 28 : 48
                        )
                    )
                    .frame(width: airborne ? 56 : 96, height: airborne ? 10 : 16)
                    .blur(radius: airborne ? 1 : 0.5)

                Ellipse()
                    .fill(Color.primary.opacity(airborne ? 0.06 : 0.14))
                    .frame(width: airborne ? 36 : 64, height: airborne ? 5 : 9)
            }
            .frame(maxWidth: .infinity)
            .accessibilityHidden(true)
        }
        .frame(maxWidth: 220)
        .onAppear {
            withAnimation(
                .easeInOut(duration: 0.62)
                .repeatForever(autoreverses: true)
            ) {
                airborne = true
            }
        }
    }
}
