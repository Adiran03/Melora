using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

[assembly: AssemblyTitle("Melora")]
[assembly: AssemblyProduct("Melora")]
[assembly: AssemblyDescription("Melora music player")]

internal static class MeloraLauncher
{
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    private static extern int SetCurrentProcessExplicitAppUserModelID(string appId);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern bool SetDllDirectory(string path);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr FindWindow(string className, string title);

    [DllImport("user32.dll")]
    private static extern bool ShowWindow(IntPtr window, int command);

    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr window);

    [STAThread]
    private static void Main()
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string runtime = Path.Combine(root, "launcher", "runtime");
        if (!File.Exists(Path.Combine(runtime, "Microsoft.Web.WebView2.WinForms.dll"))
            || !File.Exists(Path.Combine(runtime, "Microsoft.Web.WebView2.Core.dll"))
            || !File.Exists(Path.Combine(runtime, "WebView2Loader.dll")))
        {
            MessageBox.Show("Не найдены компоненты окна Melora. Запусти launcher\\build.ps1.",
                "Melora", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }
        SetCurrentProcessExplicitAppUserModelID("Melora.Desktop");
        SetDllDirectory(runtime);
        AppDomain.CurrentDomain.AssemblyResolve += (sender, args) =>
        {
            string name = new AssemblyName(args.Name).Name;
            if (!name.StartsWith("Microsoft.Web.WebView2.", StringComparison.Ordinal))
                return null;
            string path = Path.Combine(runtime, name + ".dll");
            return File.Exists(path) ? Assembly.LoadFrom(path) : null;
        };

        bool first;
        using (var instance = new Mutex(true, @"Local\Melora.Desktop", out first))
        {
            if (!first)
            {
                IntPtr window = FindWindow(null, "Melora");
                if (window != IntPtr.Zero)
                {
                    ShowWindow(window, 9);
                    SetForegroundWindow(window);
                }
                return;
            }
            try { OpenPlayer(root); }
            catch (Exception error)
            {
                MessageBox.Show("Не удалось открыть Melora.\n\n" + error.Message,
                    "Melora", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            finally { instance.ReleaseMutex(); }
        }
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void OpenPlayer(string root)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        using (var form = new PlayerWindow(root))
            Application.Run(form);
    }
}

internal sealed class PlayerWindow : Form
{
    private readonly string root;
    private readonly string sessionDirectory;
    private readonly string readyPath;
    private readonly CancellationTokenSource closing = new CancellationTokenSource();
    private Process backend;
    private readonly Label status;

    public PlayerWindow(string root)
    {
        this.root = root;
        sessionDirectory = Path.Combine(Path.GetTempPath(), "Melora-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(sessionDirectory);
        readyPath = Path.Combine(sessionDirectory, "server.url");
        Text = "Melora";
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(1160, 740);
        MinimumSize = new Size(420, 500);
        ShowInTaskbar = true;
        status = new Label { Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleCenter, Text = "Открываем Melora…" };
        Controls.Add(status);
        Shown += async (sender, args) => await InitializePlayer();
    }

    private async Task InitializePlayer()
    {
        try
        {
            backend = StartBackend();
            Uri address = await WaitForServer();
            if (closing.IsCancellationRequested)
                return;
            var browser = new WebView2 { Dock = DockStyle.Fill };
            Controls.Add(browser);
            string data = Environment.GetEnvironmentVariable("MELORA_DATA_DIR");
            if (String.IsNullOrWhiteSpace(data))
                data = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Melora");
            string profile = Path.Combine(data, "WebView2");
            var environment = await CoreWebView2Environment.CreateAsync(null, profile);
            if (closing.IsCancellationRequested)
                return;
            await browser.EnsureCoreWebView2Async(environment);
            if (closing.IsCancellationRequested)
                return;
            browser.CoreWebView2.NavigationStarting += (sender, args) =>
            {
                Uri target;
                args.Cancel = !Uri.TryCreate(args.Uri, UriKind.Absolute, out target)
                    || target.Scheme != address.Scheme || target.Host != address.Host || target.Port != address.Port;
            };
            browser.CoreWebView2.NewWindowRequested += (sender, args) => { args.Handled = true; };
            browser.BringToFront();
            browser.Source = address;
        }
        catch (OperationCanceledException) { }
        catch (Exception error)
        {
            if (!closing.IsCancellationRequested)
            {
                status.Text = "Не удалось запустить Melora.\n" + error.Message;
                status.BringToFront();
            }
        }
    }

    private Process StartBackend()
    {
        string bundledServer = Path.Combine(root, "backend", "Melora.Server.exe");
        if (File.Exists(bundledServer))
        {
            return Process.Start(new ProcessStartInfo
            {
                FileName = bundledServer,
                Arguments = "--native \"" + readyPath + "\"",
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = true
            });
        }
        string entry = Path.Combine(root, "desktop.py");
        if (!File.Exists(entry))
            throw new FileNotFoundException("Файл desktop.py должен быть в папке приложения.");
        string[] interpreters = {
            Path.Combine(root, ".venv", "Scripts", "pythonw.exe"), "pythonw.exe", "pyw.exe"
        };
        foreach (string python in interpreters)
        {
            try
            {
                return Process.Start(new ProcessStartInfo
                {
                    FileName = python,
                    Arguments = "-B \"" + entry + "\" --native \"" + readyPath + "\"",
                    WorkingDirectory = root,
                    UseShellExecute = false,
                    CreateNoWindow = true
                });
            }
            catch (System.ComponentModel.Win32Exception) { }
        }
        throw new InvalidOperationException("Python не найден. Установи Python или создай окружение .venv.");
    }

    private async Task<Uri> WaitForServer()
    {
        string errorPath = Path.ChangeExtension(readyPath, ".error");
        var timeout = Stopwatch.StartNew();
        while (timeout.Elapsed < TimeSpan.FromSeconds(15))
        {
            closing.Token.ThrowIfCancellationRequested();
            if (File.Exists(errorPath))
                throw new InvalidOperationException(File.ReadAllText(errorPath));
            if (File.Exists(readyPath))
            {
                Uri address;
                if (Uri.TryCreate(File.ReadAllText(readyPath), UriKind.Absolute, out address)
                    && address.Scheme == "http" && address.Host == "127.0.0.1")
                    return address;
            }
            if (backend.HasExited)
                throw new InvalidOperationException("Сервер плеера завершился во время запуска.");
            await Task.Delay(100, closing.Token);
        }
        throw new TimeoutException("Сервер плеера не ответил за 15 секунд.");
    }

    protected override void OnFormClosed(FormClosedEventArgs args)
    {
        closing.Cancel();
        try
        {
            if (backend != null)
            {
                File.WriteAllText(Path.ChangeExtension(readyPath, ".stop"), "");
                if (!backend.WaitForExit(1600))
                    backend.Kill();
                backend.Dispose();
            }
            foreach (string path in Directory.GetFiles(sessionDirectory))
                File.Delete(path);
            Directory.Delete(sessionDirectory);
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
        catch (InvalidOperationException) { }
        closing.Dispose();
        base.OnFormClosed(args);
    }
}
