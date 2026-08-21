# Creates the desktop shortcut for the setup script (Qurasdir.bat).
#
# Kept as its own file rather than inlined in the .bat: nesting a
# PowerShell one-liner inside a batch caret-continued line means every
# quote is escaped for cmd AND for PowerShell AND for the shell that
# eventually reads the shortcut's own Arguments -- three layers deep, and
# it broke twice while being written by hand.
#
# The launcher's real name has a non-ASCII letter in it, and this
# machine's system ANSI codepage cannot represent that letter at all.
# Two different things were tried and both broke because of that, not
# because of quoting: the classic WScript.Shell COM object silently folds
# the letter to plain "s" the moment it is assigned to a shortcut property
# (TargetPath as much as Arguments), and a "Ba*.bat" wildcard resolved
# fresh by cmd.exe at launch time *also* came back ANSI-folded when cmd
# was started the way a shortcut starts it (through ShellExecute) rather
# than typed at an interactive prompt. Both routes end up asking some
# Windows API to round-trip a character the system codepage cannot hold.
#
# So the shortcut never names the launcher .bat at all -- it reproduces
# the handful of lines that file runs (cd, UTF-8 console, run ev.py,
# pause) directly in its own Arguments, all plain ASCII. The one thing
# this loses versus calling the real file: if the launcher's own startup
# sequence changes later, the shortcut will not pick that up on its own.
param(
    [Parameter(Mandatory = $true)]
    [string]$AppDir
)

if (-not (Test-Path (Join-Path $AppDir 'ev.py'))) {
    Write-Error "ev.py not found in $AppDir"
    exit 1
}

$lnkPath = Join-Path $env:USERPROFILE 'Desktop\Esas Vesaitler.lnk'
if (Test-Path $lnkPath) {
    exit 0
}

$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($lnkPath)
$sc.TargetPath = $env:ComSpec
$sc.Arguments = '/c cd /d "' + $AppDir + '" && chcp 65001 >nul && set PYTHONIOENCODING=utf-8 && python ev.py & pause'
$sc.WorkingDirectory = $AppDir
$sc.Description = 'Esas Vesaitler ve amortizasiya'
$sc.Save()
