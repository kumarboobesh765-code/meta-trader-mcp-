# Census of visible windows in THIS session (run interactively via task).
# Writes process + window title to C:\FTTest\logs\windows.txt so we can see
# which dialog MetaTrader 5 is stuck behind.
$sig = @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public class WinEnum {
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lp);
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lp);
  [DllImport("user32.dll")] public static extern int GetWindowTextW(IntPtr hWnd, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
}
'@
Add-Type -TypeDefinition $sig
$sb = New-Object System.Text.StringBuilder 512
$rows = @()
$cb = {
  param($h, $l)
  if ([WinEnum]::IsWindowVisible($h)) {
    $null = $sb.Clear()
    $null = [WinEnum]::GetWindowTextW($h, $sb, 512)
    if ($sb.Length -gt 0) {
      $pid2 = 0
      $null = [WinEnum]::GetWindowThreadProcessId($h, [ref]$pid2)
      $rows.Add("PID $pid2 :: $($sb.ToString())")
    }
  }
  return $true
}
[WinEnum]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null
"window census $(Get-Date -Format 'HH:mm:ss')" | Set-Content C:\FTTest\logs\windows.txt
$rows | Add-Content C:\FTTest\logs\windows.txt
