import SwiftUI

@MainActor
final class TaskManagerViewModel: ObservableObject {
    @Published var overview: OpsOverview?
    @Published var tasks: [OpsTask] = []
    @Published var resources: [ResourceRuntimeRow] = []
    @Published var lastCall: OpsLastCall?
    @Published var error: String?
    @Published var debugModeDisabled = false
    @Published var actionMessage: String?
    @Published var isRefreshing = false

    private var pollTask: Task<Void, Never>?

    func startPolling(core: CoreClient) {
        pollTask?.cancel()
        pollTask = Task {
            while !Task.isCancelled {
                await refresh(core: core, silent: true)
                try? await Task.sleep(for: .seconds(2))
            }
        }
    }

    func stopPolling() {
        pollTask?.cancel()
        pollTask = nil
    }

    func refresh(core: CoreClient, silent: Bool = false) async {
        if !silent { isRefreshing = true }
        defer { if !silent { isRefreshing = false } }
        do {
            async let overviewReq = core.fetchOpsOverview()
            async let tasksReq = core.fetchOpsTasks()
            async let runtimeReq = core.fetchResourceRuntime()
            let (ov, taskResp, runtime) = try await (overviewReq, tasksReq, runtimeReq)
            overview = ov
            tasks = taskResp.tasks
            resources = runtime.resources
            lastCall = runtime.last_call ?? ov.last_call
            error = nil
            debugModeDisabled = false
        } catch let err {
            if err.isCancellation { return }
            if (err as NSError).code == 403 {
                debugModeDisabled = true
                overview = nil
                error = nil
            } else {
                debugModeDisabled = false
                error = err.localizedDescription
            }
        }
    }

    func startSummarizeAll(core: CoreClient) async {
        do {
            try await core.startSummarizeAll()
            actionMessage = "已恢复全部摘要"
            await refresh(core: core)
        } catch {
            actionMessage = error.localizedDescription
        }
    }

    func stopSummarizeAll(core: CoreClient) async {
        do {
            try await core.stopSummarizeAll()
            actionMessage = "已暂停全部摘要"
            await refresh(core: core)
        } catch {
            actionMessage = error.localizedDescription
        }
    }

    func cancelTask(_ task: OpsTask, core: CoreClient) async {
        do {
            try await core.cancelOpsTask(id: task.id)
            await refresh(core: core)
        } catch {
            actionMessage = error.localizedDescription
        }
    }

    var runningTasks: [OpsTask] {
        tasks.filter { $0.status == "running" }
    }

    var queuedTasks: [OpsTask] {
        tasks.filter { $0.status == "queued" }
    }

    var pausedTasks: [OpsTask] {
        tasks.filter { $0.status == "paused" }
    }

    var recentTasks: [OpsTask] {
        tasks.filter { ["completed", "failed", "cancelled"].contains($0.status) }
    }
}

struct TaskManagerView: View {
    @EnvironmentObject private var core: CoreClient
    @StateObject private var viewModel = TaskManagerViewModel()

    var body: some View {
        Form {
            if viewModel.debugModeDisabled {
                ContentUnavailableView(
                    "请先开启调试模式",
                    systemImage: "ladybug",
                    description: Text("在设置 → 高级 中打开「调试模式」后再查看后台任务。")
                )
            } else if let overview = viewModel.overview {
                Section("概览") {
                    overviewRow("运行中", value: "\(overview.task_counts.running)")
                    overviewRow("排队", value: "\(overview.task_counts.queued)")
                    if let paused = overview.task_counts.paused, paused > 0 {
                        overviewRow("已暂停", value: "\(paused)")
                    }
                    overviewRow("队列深度", value: "\(overview.job_queue.queue_depth)")
                    if let backlog = overview.job_queue.paused_backlog_depth, backlog > 0 {
                        overviewRow("暂停积压", value: "\(backlog)")
                    }
                    overviewRow("Worker", value: "\(overview.job_queue.worker_count)/\(overview.job_queue.worker_target)")
                    if overview.job_queue.user_paused_all {
                        Label("摘要全局已暂停", systemImage: "pause.circle.fill")
                            .foregroundStyle(.orange)
                    }
                    if overview.job_queue.chat_preempted {
                        Label("深聊抢占中", systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(.yellow)
                    }
                }

                Section("控制") {
                    Button("开始全部摘要") {
                        Task { await viewModel.startSummarizeAll(core: core) }
                    }
                    Button("停止全部摘要") {
                        Task { await viewModel.stopSummarizeAll(core: core) }
                    }
                    if let msg = viewModel.actionMessage {
                        Text(msg)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                if !viewModel.runningTasks.isEmpty {
                    Section("运行中") {
                        ForEach(viewModel.runningTasks) { task in
                            TaskRowView(task: task) {
                                Task { await viewModel.cancelTask(task, core: core) }
                            }
                        }
                    }
                }

                if !viewModel.queuedTasks.isEmpty {
                    Section("排队") {
                        ForEach(viewModel.queuedTasks) { task in
                            TaskRowView(task: task)
                        }
                    }
                }

                if !viewModel.pausedTasks.isEmpty {
                    Section("已暂停") {
                        ForEach(viewModel.pausedTasks) { task in
                            TaskRowView(task: task)
                        }
                    }
                }

                if !viewModel.recentTasks.isEmpty {
                    Section("最近完成") {
                        ForEach(viewModel.recentTasks.prefix(20)) { task in
                            TaskRowView(task: task)
                        }
                    }
                }

                ResourceRuntimeSection(resources: viewModel.resources, lastCall: viewModel.lastCall)
            } else if let error = viewModel.error {
                ContentUnavailableView("无法加载", systemImage: "exclamationmark.triangle", description: Text(error))
            } else {
                ProgressView("加载任务…")
            }
        }
        .formStyle(.grouped)
        .navigationTitle("后台任务")
        .task {
            viewModel.startPolling(core: core)
            await viewModel.refresh(core: core)
        }
        .onDisappear {
            viewModel.stopPolling()
        }
        .refreshable {
            await viewModel.refresh(core: core)
        }
        .overlay(alignment: .topTrailing) {
            if viewModel.isRefreshing {
                ProgressView()
                    .controlSize(.small)
                    .padding(12)
            }
        }
    }

    private func overviewRow(_ label: String, value: String) -> some View {
        HStack {
            Text(label)
            Spacer()
            Text(value)
                .foregroundStyle(.secondary)
                .monospacedDigit()
        }
    }
}
