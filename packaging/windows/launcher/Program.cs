using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Net;
using System.Reflection;
using System.Security.Cryptography;
using System.Windows.Forms;

namespace AnkiImageUpdater;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        Application.Run(new LauncherForm(args));
    }
}

internal sealed class LauncherForm : Form
{
    private readonly Process? _child;
    private readonly System.Windows.Forms.Timer _pollTimer = new() { Interval = 250 };
    private int _attemptsRemaining = 720;

    public LauncherForm(string[] args)
    {
        Text = "Anki Image Updater";
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = true;
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(440, 130);

        var label = new Label
        {
            AutoSize = false,
            Bounds = new Rectangle(16, 12, 408, 56),
            Text =
                "Preparing the app. The first launch can take a minute while Python and libraries are set up. "
                + "This window hides automatically when the tool is ready in your browser.",
        };

        var progress = new ProgressBar
        {
            Style = ProgressBarStyle.Marquee,
            MarqueeAnimationSpeed = 30,
            Bounds = new Rectangle(16, 78, 408, 22),
        };

        Controls.Add(label);
        Controls.Add(progress);

        string pyapp;
        try
        {
            pyapp = MaterializePyAppFromEmbeddedResource();
        }
        catch (Exception ex)
        {
            MessageBox.Show(
                $"Could not prepare Anki Image Updater:\n{ex.Message}",
                "Error",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            Close();
            return;
        }

        var psi = new ProcessStartInfo
        {
            FileName = pyapp,
            UseShellExecute = false,
            WorkingDirectory = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
        };
        if (args.Length > 0)
            psi.Arguments = string.Join(" ", Array.ConvertAll(args, EscapeWindowsArg));

        try
        {
            _child = Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show($"Could not start Anki Image Updater:\n{ex.Message}", "Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            Close();
            return;
        }

        _pollTimer.Tick += (_, _) =>
        {
            if (_attemptsRemaining-- <= 0)
            {
                _pollTimer.Stop();
                return;
            }

            if (!ProbeLocalServer())
                return;
            _pollTimer.Stop();
            Hide();
            ShowInTaskbar = false;
        };
        _pollTimer.Start();

        FormClosing += (_, _) =>
        {
            _pollTimer.Stop();
            try
            {
                if (_child is { HasExited: false })
                    _child.Kill(entireProcessTree: true);
            }
            catch
            {
                /* ignore */
            }
        };

        if (_child != null)
        {
            _child.EnableRaisingEvents = true;
            _child.Exited += (_, _) => BeginInvoke(Close);
        }
    }

    /// <summary>
    /// Extract the PyApp payload shipped inside this single-file exe to LocalApplicationData.
    /// </summary>
    private static string MaterializePyAppFromEmbeddedResource()
    {
        var asm = Assembly.GetExecutingAssembly();
        var res = asm.GetManifestResourceNames().FirstOrDefault(n =>
            n.EndsWith("AnkiImageUpdaterPyApp.exe", StringComparison.OrdinalIgnoreCase));
        if (res is null)
            throw new InvalidOperationException(
                "Embedded PyApp is missing. Rebuild the launcher with AnkiImageUpdaterPyApp.exe in Embedded/.");

        using var input = asm.GetManifestResourceStream(res)
            ?? throw new InvalidOperationException("Could not open embedded PyApp stream.");
        using var ms = new MemoryStream();
        input.CopyTo(ms);
        var bytes = ms.ToArray();

        var dir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "anki-image-updater",
            "pyapp");
        Directory.CreateDirectory(dir);
        var path = Path.Combine(dir, "AnkiImageUpdaterPyApp.exe");
        var hashPath = path + ".sha256";
        var hashHex = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

        if (!File.Exists(path) || !File.Exists(hashPath) ||
            !string.Equals(File.ReadAllText(hashPath).Trim(), hashHex, StringComparison.Ordinal))
        {
            File.WriteAllBytes(path, bytes);
            File.WriteAllText(hashPath, hashHex);
        }

        return path;
    }

    private static string EscapeWindowsArg(string arg)
    {
        if (string.IsNullOrEmpty(arg))
            return "\"\"";
        if (arg.IndexOfAny(new[] { ' ', '\t', '"' }) < 0)
            return arg;
        return '\"' + arg.Replace("\"", "\\\"") + '\"';
    }

    private static bool ProbeLocalServer()
    {
        try
        {
#pragma warning disable SYSLIB0014 // WebRequest is fine for a tiny localhost probe
            var req = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:8080/");
#pragma warning restore SYSLIB0014
            req.Timeout = 500;
            req.Method = "GET";
            using var resp = (HttpWebResponse)req.GetResponse();
            var code = (int)resp.StatusCode;
            return code is >= 200 and < 500;
        }
        catch
        {
            return false;
        }
    }
}
