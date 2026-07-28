import SwiftUI

struct OnboardingView: View {
    @Binding var isPresented: Bool
    @EnvironmentObject private var sidecar: SidecarManager
    @EnvironmentObject private var core: CoreClient
    @State private var step = 0
    @State private var ollamaReady = false
    @State private var checkingOllama = false

    var body: some View {
        VStack(spacing: 24) {
            Spacer()
            Image(systemName: icon)
                .font(.system(size: 56))
                .foregroundStyle(LuminaTheme.accent)

            Text(title)
                .font(.title.bold())
            Text(subtitle)
                .font(.body)
                .foregroundStyle(LuminaTheme.textSecondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 440)

            statusRow

            if step == 1, !ollamaReady {
                Button("下载并安装 Ollama") {
                    OllamaSetupHelper.openDownloadPage()
                }
                .controlSize(.large)
                Button("我已安装，检查状态") {
                    Task { await refreshOllamaStatus() }
                }
            }

            if let err = sidecar.launchError {
                Text(err)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)
            }

            Spacer()

            HStack {
                if step > 0 {
                    Button("上一步") { step -= 1 }
                }
                Spacer()
                Button(primaryButtonTitle) {
                    advance()
                }
                .keyboardShortcut(.defaultAction)
                .disabled(step == 0 && !sidecar.isRunning)
            }
        }
        .padding(40)
        .frame(width: 540, height: 460)
        .task {
            await sidecar.ensureRunning()
            await refreshOllamaStatus()
        }
    }

    @ViewBuilder
    private var statusRow: some View {
        VStack(alignment: .leading, spacing: 8) {
            statusLine(
                ok: sidecar.isRunning,
                label: sidecar.isRunning ? "Lumina 引擎已就绪" : "正在启动 Lumina 引擎…"
            )
            if step >= 1 {
                statusLine(
                    ok: ollamaReady,
                    label: ollamaReady ? "AI 模型服务已就绪" : "需要安装 Ollama（本地 AI，免费）"
                )
            }
        }
        .font(.caption)
    }

    private func statusLine(ok: Bool, label: String) -> some View {
        HStack(spacing: 8) {
            Circle()
                .fill(ok ? Color.green : Color.orange)
                .frame(width: 8, height: 8)
            Text(label)
        }
    }

    private var primaryButtonTitle: String {
        switch step {
        case 0: return "下一步"
        case 1: return ollamaReady ? "下一步" : "稍后设置"
        case 2: return "开始使用"
        default: return "下一步"
        }
    }

    private func advance() {
        if step < 2 {
            step += 1
            if step == 1 { Task { await refreshOllamaStatus() } }
        } else {
            isPresented = false
        }
    }

    private func refreshOllamaStatus() async {
        checkingOllama = true
        defer { checkingOllama = false }
        if let status = try? await core.fetchOllamaStatus() {
            ollamaReady = status.ready
            if status.ready == false, OllamaSetupHelper.isInstalled(), status.served {
                OllamaSetupHelper.pullRecommendedModel(model: status.model)
            }
        } else {
            ollamaReady = OllamaSetupHelper.isInstalled()
        }
    }

    private var icon: String {
        switch step {
        case 0: return "sparkles"
        case 1: return "cpu"
        default: return "books.vertical"
        }
    }

    private var title: String {
        switch step {
        case 0: return "欢迎使用 Lumina"
        case 1: return "启用本地 AI"
        default: return "导入第一本书"
        }
    }

    private var subtitle: String {
        switch step {
        case 0:
            return "AI 伴读助手：分段摘要、深聊、自动翻译。书籍与笔记都在你的 Mac 上，无需编程或命令行。"
        case 1:
            return "Lumina 通过 Ollama 在本机运行 AI（约 3 GB 模型，仅首次下载）。安装后菜单栏会出现 Llama 图标。"
        default:
            return "支持 PDF、EPUB、MOBI、TXT。点书库「导入」选文件即可；第一段准备好就能开始读。"
        }
    }
}
