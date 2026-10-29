using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;
[assembly: AssemblyTitle("LoadoutRoom")]
[assembly: AssemblyProduct("LoadoutRoom")]
[assembly: AssemblyDescription("VALORANT desktop roster, win rates and loadouts")]
[assembly: AssemblyVersion("1.0.22.0")]
[assembly: AssemblyFileVersion("1.0.22.0")]

internal static class Program {
    internal static bool IsNewerRelease(string target, string current) {
        if (String.Equals(Path.GetDirectoryName(target), Path.GetDirectoryName(current), StringComparison.OrdinalIgnoreCase)) return false;
        Version targetVersion;
        string folder = new DirectoryInfo(Path.GetDirectoryName(target)).Name;
        if (!Version.TryParse(folder.Split('-')[0], out targetVersion)) return false;
        Version build = Assembly.GetExecutingAssembly().GetName().Version;
        return targetVersion > new Version(build.Major, build.Minor, build.Build);
    }
    [STAThread]
    static int Main(string[] args) {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        bool test = args.Length > 0 && args[0] == "--self-test";
        bool demo = args.Length > 0 && args[0] == "--demo";
        try {
            // Follow only app-owned side-by-side releases, keeping old shortcuts useful.
            if (!test && !demo) {
                string updateRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "LoadoutRoom");
                string pointer = Path.Combine(updateRoot, "active-release.txt");
                try { if (File.Exists(pointer)) {
                    string target = Path.GetFullPath(File.ReadAllText(pointer).Trim());
                    string releaseRoot = Path.GetFullPath(Path.Combine(updateRoot, "releases")) + Path.DirectorySeparatorChar;
                    string current = Path.GetFullPath(Assembly.GetExecutingAssembly().Location);
                    if (target.StartsWith(releaseRoot, StringComparison.OrdinalIgnoreCase) &&
                        (String.Equals(Path.GetFileName(target), "LoadoutRoom1.0.exe", StringComparison.OrdinalIgnoreCase) ||
                         String.Equals(Path.GetFileName(target), "LoadoutRoom.exe", StringComparison.OrdinalIgnoreCase)) &&
                        IsNewerRelease(target, current) && File.Exists(target) &&
                        File.Exists(Path.Combine(Path.GetDirectoryName(target), "runtime", "pythonw.exe"))) {
                        ProcessStartInfo forward = new ProcessStartInfo(target);
                        forward.UseShellExecute = false;
                        forward.WorkingDirectory = Path.GetDirectoryName(target);
                        Process.Start(forward);
                        return 0;
                    }
                }
                } catch (Exception) { /* A stale pointer must not prevent the original app opening. */ }
            }
            string runtime = Path.Combine(root, "runtime");
            string exe = Path.Combine(runtime, test ? "python.exe" : "pythonw.exe");
            string script = Path.Combine(root, "app", "desktop.py");
            if (!File.Exists(exe) || !File.Exists(script))
                throw new FileNotFoundException("Extract the entire ZIP before opening LoadoutRoom.");
            ProcessStartInfo info = new ProcessStartInfo(exe);
            info.Arguments = "-B \"" + script + "\"" + (test ? " --self-test" : demo ? " --demo" : "");
            info.WorkingDirectory = Path.Combine(root, "app");
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.RedirectStandardOutput = test;
            info.RedirectStandardError = test;
            info.EnvironmentVariables.Remove("PYTHONPATH");
            info.EnvironmentVariables.Remove("PYTHONHOME");
            info.EnvironmentVariables["TCL_LIBRARY"] = Path.Combine(runtime, "tcl", "tcl8.6");
            info.EnvironmentVariables["TK_LIBRARY"] = Path.Combine(runtime, "tcl", "tk8.6");
            using (Process process = Process.Start(info)) {
                string output = "", errors = "";
                if (test) {
                    output = process.StandardOutput.ReadToEnd();
                    errors = process.StandardError.ReadToEnd();
                }
                process.WaitForExit();
                if (test)
                    File.WriteAllText(Path.Combine(root, "desktop-self-test.txt"), output + errors);
                else if (process.ExitCode != 0)
                    MessageBox.Show("The interface closed unexpectedly. Extract the whole ZIP to a fresh folder and try again.",
                                    "LoadoutRoom", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return process.ExitCode;
            }
        } catch (Exception error) {
            if (test) File.WriteAllText(Path.Combine(root, "desktop-self-test.txt"), error.ToString());
            else MessageBox.Show(error.Message, "LoadoutRoom", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
