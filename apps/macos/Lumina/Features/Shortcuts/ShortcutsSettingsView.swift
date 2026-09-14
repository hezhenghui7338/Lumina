import AppKit
import SwiftUI

struct ShortcutsSettingsView: View {
    @ObservedObject private var store = ShortcutStore.shared
    @State private var recording: ShortcutAction?
    @State private var bindError: String?

    var body: some View {
        Form {
            ForEach(ShortcutGroup.allCases) { group in
                Section {
                    ForEach(actions(in: group)) { action in
                        shortcutRow(action)
                    }
                } header: {
                    Text(group.title)
                } footer: {
                    footer(for: group)
                }
            }

            Section {
                Button("全部恢复默认", role: .destructive) {
                    store.resetAll()
                    recording = nil
                    bindError = nil
                }
            }
        }
        .formStyle(.grouped)
        .navigationTitle("快捷键")
        .onChange(of: recording) { _, newValue in
            store.isRecordingBinding = newValue != nil
        }
        .onDisappear {
            store.isRecordingBinding = false
            recording = nil
        }
        .background(ShortcutRecorderRepresentable(
            isRecording: recording != nil,
            onEvent: handleRecordedEvent
        ))
    }

    private func actions(in group: ShortcutGroup) -> [ShortcutAction] {
        ShortcutCatalog.allActions.filter { $0.group == group }
    }

    @ViewBuilder
    private func footer(for group: ShortcutGroup) -> some View {
        switch group {
        case .global:
            Text("在应用内全局生效。")
        case .reader:
            Text("打开书籍后生效。摘要菜单 / 分段菜单只打开对应面板，不直接执行危险操作。")
        case .fixed:
            Text("连续滚动与 Esc 关闭浮层为阅读原语，不可修改。")
        }
    }

    @ViewBuilder
    private func shortcutRow(_ action: ShortcutAction) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(action.title)
                    if let detail = action.detail {
                        Text(detail)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                Spacer()
                if action.isCustomizable {
                    Button {
                        bindError = nil
                        recording = (recording == action) ? nil : action
                    } label: {
                        Text(recording == action ? "按下新快捷键…" : store.display(for: action))
                            .font(.body.monospaced())
                            .foregroundStyle(recording == action ? LuminaTheme.accent : LuminaTheme.textPrimary)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 4)
                            .background(
                                RoundedRectangle(cornerRadius: 6)
                                    .fill(LuminaTheme.surface.opacity(0.8))
                            )
                    }
                    .buttonStyle(.plain)
                    .help(recording == action ? "再点取消录制" : "点击录制新快捷键")

                    if store.isOverridden(action) {
                        Button("恢复") {
                            store.reset(action)
                            if recording == action { recording = nil }
                            bindError = nil
                        }
                        .buttonStyle(.borderless)
                    }
                } else {
                    Text(store.display(for: action))
                        .font(.body.monospaced())
                        .foregroundStyle(.secondary)
                }
            }
            if recording == action, let bindError {
                Text(bindError)
                    .font(.caption)
                    .foregroundStyle(.red)
            }
        }
    }

    private func handleRecordedEvent(_ event: NSEvent) -> Bool {
        guard let action = recording else { return false }
        if event.keyCode == 53 && ShortcutModifiers.from(event.modifierFlags).isEmpty {
            recording = nil
            bindError = nil
            return true
        }
        guard let chord = ShortcutChord.from(event: event) else {
            bindError = "无法识别该按键"
            return true
        }
        switch store.setChord(chord, for: action) {
        case .ok:
            recording = nil
            bindError = nil
        case .reserved:
            bindError = "该组合为系统保留，请换一组"
        case .conflict(let other):
            bindError = "与「\(other.title)」冲突"
        case .notCustomizable:
            bindError = "该项不可修改"
        }
        return true
    }
}

private struct ShortcutRecorderRepresentable: NSViewRepresentable {
    var isRecording: Bool
    var onEvent: (NSEvent) -> Bool

    func makeNSView(context: Context) -> RecorderNSView {
        let view = RecorderNSView()
        view.onEvent = onEvent
        view.isRecording = isRecording
        return view
    }

    func updateNSView(_ nsView: RecorderNSView, context: Context) {
        nsView.onEvent = onEvent
        nsView.isRecording = isRecording
    }

    final class RecorderNSView: NSView {
        var isRecording = false
        var onEvent: ((NSEvent) -> Bool)?
        private var monitor: Any?

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            if window != nil {
                install()
            } else {
                remove()
            }
        }

        deinit {
            if let monitor {
                NSEvent.removeMonitor(monitor)
            }
        }

        private func install() {
            guard monitor == nil else { return }
            monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
                guard let self, self.isRecording else { return event }
                if self.onEvent?(event) == true {
                    return nil
                }
                return event
            }
        }

        private func remove() {
            if let monitor {
                NSEvent.removeMonitor(monitor)
                self.monitor = nil
            }
        }
    }
}
