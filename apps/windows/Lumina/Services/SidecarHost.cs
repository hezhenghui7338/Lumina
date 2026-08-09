using System.Diagnostics;
using System.Net.Http;

namespace Lumina.Services;

/// <summary>Starts / stops bundled or dev lumina-core on 127.0.0.1:17432.</summary>
public sealed class SidecarHost : IDisposable
{
    private const string Host = "127.0.0.1";
    private const int Port = 17432;
    private const int MaxLaunchAttempts = 5;
    private const int HealthPollAttempts = 120;

    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(2) };
    private Process? _process;
    private readonly object _gate = new();

    public Uri BaseUrl { get; } = new($"http://{Host}:{Port}");
    public bool IsRunning { get; private set; }
    public bool IsBootstrapping { get; private set; }
    public string? LaunchError { get; private set; }

    public event Action? StateChanged;

    public async Task EnsureRunningAsync(CancellationToken ct = default)
    {
        lock (_gate)
        {
            if (IsBootstrapping) return;
            IsBootstrapping = true;
            LaunchError = null;
        }
        Notify();

        try
        {
            if (_process is { HasExited: false } && await IsHealthyAsync(ct).ConfigureAwait(false))
            {
                IsRunning = true;
                return;
            }

            if (_process is null && await IsHealthyAsync(ct).ConfigureAwait(false))
            {
                IsRunning = true;
                return;
            }

            string? lastError = null;
            for (var attempt = 1; attempt <= MaxLaunchAttempts; attempt++)
            {
                ct.ThrowIfCancellationRequested();
                var outcome = LaunchSidecar();
                if (outcome.Fatal)
                {
                    IsRunning = false;
                    LaunchError = outcome.Error;
                    return;
                }
                if (outcome.Started)
                {
                    for (var i = 0; i < HealthPollAttempts; i++)
                    {
                        await Task.Delay(250, ct).ConfigureAwait(false);
                        if (await IsHealthyAsync(ct).ConfigureAwait(false))
                        {
                            IsRunning = true;
                            LaunchError = null;
                            return;
                        }
                    }
                    lastError = "AI 引擎启动超时，请重试或退出。";
                }
                else
                {
                    lastError = outcome.Error;
                }

                if (attempt < MaxLaunchAttempts)
                    await Task.Delay(750, ct).ConfigureAwait(false);
            }

            IsRunning = false;
            LaunchError = lastError ?? "AI 引擎启动超时，请重试或退出。";
        }
        catch (OperationCanceledException)
        {
            IsRunning = false;
            LaunchError = "启动已取消";
        }
        finally
        {
            IsBootstrapping = false;
            Notify();
        }
    }

    public async Task StopAsync()
    {
        try
        {
            using var req = new HttpRequestMessage(HttpMethod.Post, new Uri(BaseUrl, "/shutdown"));
            await _http.SendAsync(req).ConfigureAwait(false);
        }
        catch { /* ignore */ }

        lock (_gate)
        {
            try
            {
                if (_process is { HasExited: false })
                {
                    _process.Kill(entireProcessTree: true);
                    _process.Dispose();
                }
            }
            catch { /* ignore */ }
            _process = null;
            IsRunning = false;
        }
        Notify();
    }

    public void Dispose()
    {
        _ = StopAsync();
        _http.Dispose();
    }

    private async Task<bool> IsHealthyAsync(CancellationToken ct)
    {
        try
        {
            using var resp = await _http.GetAsync(new Uri(BaseUrl, "/health"), ct).ConfigureAwait(false);
            return resp.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    private LaunchOutcome LaunchSidecar()
    {
        lock (_gate)
        {
            try
            {
                if (_process is { HasExited: false })
                {
                    _process.Kill(entireProcessTree: true);
                    _process.Dispose();
                }
            }
            catch { /* ignore */ }
            _process = null;
        }

        var psi = new ProcessStartInfo
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        psi.Environment["LUMINA_DATA_DIR"] = DefaultDataDirectory();
        foreach (var key in new[]
                 {
                     "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"
                 })
        {
            psi.Environment.Remove(key);
        }

        var bundled = BundledSidecarExecutable();
        if (bundled is not null)
        {
            psi.FileName = bundled;
            psi.WorkingDirectory = Path.GetDirectoryName(bundled)!;
            psi.ArgumentList.Add("--host");
            psi.ArgumentList.Add(Host);
            psi.ArgumentList.Add("--port");
            psi.ArgumentList.Add(Port.ToString());
        }
        else
        {
            var devDir = ResolveDevCoreDirectory();
            if (devDir is null)
            {
                return LaunchOutcome.Fail(
                    "未找到内置 AI 引擎。请从官网下载完整安装包，或设置环境变量 LUMINA_CORE_DIR。",
                    fatal: true);
            }

            var uv = FindUv();
            if (uv is null)
            {
                return LaunchOutcome.Fail(
                    "开发模式需要 uv。请安装 https://docs.astral.sh/uv/ 或设置 LUMINA_CORE_DIR。",
                    fatal: true);
            }

            psi.FileName = uv;
            psi.WorkingDirectory = devDir;
            psi.ArgumentList.Add("run");
            psi.ArgumentList.Add("lumina-core");
            psi.ArgumentList.Add("--host");
            psi.ArgumentList.Add(Host);
            psi.ArgumentList.Add("--port");
            psi.ArgumentList.Add(Port.ToString());
        }

        try
        {
            var logPath = OpenSidecarLogPath();
            var proc = new Process { StartInfo = psi };
            if (logPath is not null)
            {
                proc.OutputDataReceived += (_, e) => AppendLog(logPath, e.Data);
                proc.ErrorDataReceived += (_, e) => AppendLog(logPath, e.Data);
            }
            if (!proc.Start())
                return LaunchOutcome.Fail("无法启动 AI 引擎进程。", fatal: false);
            proc.BeginOutputReadLine();
            proc.BeginErrorReadLine();
            lock (_gate) { _process = proc; }
            return LaunchOutcome.Ok();
        }
        catch (Exception ex)
        {
            return LaunchOutcome.Fail($"无法启动 AI 引擎：{ex.Message}", fatal: false);
        }
    }

    private static string DefaultDataDirectory()
    {
        var appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
        return Path.Combine(appData, "Lumina");
    }

    private static string? BundledSidecarExecutable()
    {
        var baseDir = AppContext.BaseDirectory;
        var candidates = new[]
        {
            Path.Combine(baseDir, "lumina-core", "lumina-core.exe"),
            Path.Combine(baseDir, "lumina-core", "lumina-core"),
        };
        return candidates.FirstOrDefault(File.Exists);
    }

    private static string? ResolveDevCoreDirectory()
    {
        var env = Environment.GetEnvironmentVariable("LUMINA_CORE_DIR");
        if (!string.IsNullOrWhiteSpace(env) && Directory.Exists(env))
            return env;

        var cwd = Directory.GetCurrentDirectory();
        var candidates = new[]
        {
            Path.Combine(cwd, "packages", "lumina-core"),
            Path.GetFullPath(Path.Combine(cwd, "..", "packages", "lumina-core")),
            Path.GetFullPath(Path.Combine(cwd, "..", "..", "packages", "lumina-core")),
            Path.GetFullPath(Path.Combine(cwd, "..", "..", "..", "packages", "lumina-core")),
            Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..", "packages", "lumina-core")),
        };
        return candidates.FirstOrDefault(Directory.Exists);
    }

    private static string? FindUv()
    {
        var path = Environment.GetEnvironmentVariable("PATH") ?? "";
        foreach (var dir in path.Split(Path.PathSeparator))
        {
            var exe = Path.Combine(dir, "uv.exe");
            if (File.Exists(exe)) return exe;
            exe = Path.Combine(dir, "uv");
            if (File.Exists(exe)) return exe;
        }
        var local = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            ".local", "bin", "uv.exe");
        return File.Exists(local) ? local : null;
    }

    private static string? OpenSidecarLogPath()
    {
        try
        {
            var dir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Lumina", "Logs");
            Directory.CreateDirectory(dir);
            return Path.Combine(dir, "sidecar.log");
        }
        catch
        {
            return null;
        }
    }

    private static void AppendLog(string path, string? line)
    {
        if (string.IsNullOrEmpty(line)) return;
        try { File.AppendAllText(path, line + Environment.NewLine); }
        catch { /* ignore */ }
    }

    private void Notify() => StateChanged?.Invoke();

    private readonly record struct LaunchOutcome(bool Started, bool Fatal, string? Error)
    {
        public static LaunchOutcome Ok() => new(true, false, null);
        public static LaunchOutcome Fail(string error, bool fatal) => new(false, fatal, error);
    }
}
