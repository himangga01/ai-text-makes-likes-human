param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$target = [IO.Path]::GetFullPath($OutputDirectory)
$parent = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\runtime\test-tmp'))
if (-not $target.StartsWith($parent + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Fixture must stay inside runtime/test-tmp' }
New-Item -ItemType Directory -Force -Path $target | Out-Null
$source = @'
using System;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
public class FakeCli {
  public static int Main(string[] args) {
    Console.InputEncoding = Encoding.UTF8;
    Console.OutputEncoding = new UTF8Encoding(false);
    bool claude = Path.GetFileName(Environment.GetCommandLineArgs()[0]).ToLowerInvariant().Contains("claude");
    if (args.Length > 0 && args[0] == "--version") { Console.WriteLine(claude ? "2.1.261 (Claude Code)" : "codex-cli 0.153.4"); return 0; }
    if (args.Length > 0 && (args[0] == "login" || args[0] == "auth")) {
      Console.WriteLine(claude ? "{\"loggedIn\":true}" : "Logged in using ChatGPT"); return 0;
    }
    string prompt = Console.In.ReadToEnd();
    var match = Regex.Match(prompt, @"BEGIN_SOURCE_([a-f0-9]+)\r?\n(.*?)\r?\nEND_SOURCE_\1", RegexOptions.Singleline);
    if (!match.Success) return 3;
    string text = match.Groups[2].Value;
    string trace = Environment.GetEnvironmentVariable("HUMANIZE_FAKE_TRACE");
    if (!String.IsNullOrEmpty(trace)) File.AppendAllText(trace, (claude ? "claude" : "codex") + "\n");
    if (text.Contains("CANCEL_FIXTURE")) Thread.Sleep(15000);
    if (text.Contains("NUMBER_FIXTURE")) text = text.Replace("12", "13");
    var serializer = new JavaScriptSerializer();
    serializer.MaxJsonLength = Int32.MaxValue;
    var response = new { rewrittenText = text, warnings = new string[0] };
    if (claude) Console.WriteLine(serializer.Serialize(new { is_error = false, subtype = "success", structured_output = response }));
    else {
      int index = Array.IndexOf(args, "--output-last-message");
      if (index < 0 || index + 1 >= args.Length) return 4;
      File.WriteAllText(args[index + 1], serializer.Serialize(response), new UTF8Encoding(false));
    }
    return 0;
  }
}
'@
Add-Type -TypeDefinition $source -ReferencedAssemblies 'System.Web.Extensions' -OutputAssembly (Join-Path $target 'codex.exe') -OutputType ConsoleApplication
Copy-Item -LiteralPath (Join-Path $target 'codex.exe') -Destination (Join-Path $target 'claude.exe')
