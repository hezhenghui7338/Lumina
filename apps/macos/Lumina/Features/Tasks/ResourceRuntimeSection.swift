import SwiftUI

struct ResourceRuntimeSection: View {
    let resources: [ResourceRuntimeRow]
    let lastCall: OpsLastCall?

    var body: some View {
        Section("API 资源") {
            if let lastCall, lastCall.resource_id != nil {
                VStack(alignment: .leading, spacing: 4) {
                    Text("最近调用")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    HStack {
                        Text(lastCall.resource_id ?? "—")
                        if let profile = lastCall.profile {
                            Text("· \(profile)")
                                .foregroundStyle(.secondary)
                        }
                        if let ms = lastCall.duration_ms {
                            Text("· \(ms) ms")
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        if let ok = lastCall.ok {
                            Image(systemName: ok ? "checkmark.circle.fill" : "xmark.circle.fill")
                                .foregroundStyle(ok ? .green : .red)
                        }
                    }
                    .font(.caption)
                }
            }

            ForEach(resources) { row in
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text(row.resource_id)
                            .font(.body)
                        Spacer()
                        probeBadge(row.probe)
                    }
                    if row.limit > 0 {
                        ProgressView(value: Double(row.in_use), total: Double(row.limit))
                        Text("\(row.in_use)/\(row.limit) 并发槽")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    if let probe = row.probe {
                        Text(probe.displayMessage)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                }
                .padding(.vertical, 2)
            }
        }
    }

    @ViewBuilder
    private func probeBadge(_ probe: ResourceStatus?) -> some View {
        if let probe {
            Text(probe.ready ? "就绪" : "未就绪")
                .font(.caption2)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(probe.ready ? Color.green.opacity(0.15) : Color.orange.opacity(0.15))
                .clipShape(Capsule())
        }
    }
}
