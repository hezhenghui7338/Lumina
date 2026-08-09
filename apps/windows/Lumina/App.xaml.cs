using Lumina.Services;
using Microsoft.UI.Xaml;

namespace Lumina;

public partial class App : Application
{
    private Window? _window;
    public static SidecarHost Sidecar { get; } = new();
    public static CoreClient Core { get; private set; } = null!;

    public App()
    {
        InitializeComponent();
        Core = new CoreClient(Sidecar.BaseUrl);
        UnhandledException += (_, e) =>
        {
            System.Diagnostics.Debug.WriteLine(e.Exception);
            e.Handled = true;
        };
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        _window = new MainWindow();
        _window.Closed += async (_, _) =>
        {
            try { await Sidecar.StopAsync().ConfigureAwait(false); }
            catch { /* best-effort shutdown */ }
        };
        _window.Activate();
        _ = Sidecar.EnsureRunningAsync();
    }
}
