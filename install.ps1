# Allinone installer for Windows.
#   Run:  install.cmd            (or)  powershell -ExecutionPolicy Bypass -File install.ps1
# It checks Python and Git (offers to install them with winget), then runs
#   python allinone.py install
# which downloads a portable Node.js, OmniRoute, FreeLLMAPI and Claude Code into .\runtime
param([switch]$Yes)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

function Say($text, $color = "Cyan") { Write-Host $text -ForegroundColor $color }

function Ask($question) {
    if ($Yes) { return $true }
    $answer = Read-Host "$question [Y/n]"
    return ($answer -eq "" -or $answer -match "^(y|yes)$")
}

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Find-Python {
    foreach ($candidate in @(@("py", "-3"), @("python"), @("python3"))) {
        $cmd = Get-Command $candidate[0] -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        try {
            $extra = @()
            if ($candidate.Length -gt 1) { $extra += $candidate[1..($candidate.Length - 1)] }
            $ok = & $candidate[0] @extra -c "import sys; print(sys.version_info >= (3, 10))" 2>$null
            if ($ok -match "True") { return ,$candidate }
        } catch {}
    }
    return $null
}

function Have-Winget { return [bool](Get-Command winget -ErrorAction SilentlyContinue) }

Say "== Allinone: Claude Code + OmniRoute + FreeLLMAPI ==" "Green"

# Refuse protected system folders (an admin PowerShell starts in C:\Windows\System32).
if ($Root.StartsWith($env:windir, [System.StringComparison]::OrdinalIgnoreCase) -or
    $Root.StartsWith($env:ProgramFiles, [System.StringComparison]::OrdinalIgnoreCase)) {
    Say "Allinone is inside a protected Windows folder: $Root" "Red"
    Say "Move it to your user folder, for example:" "Yellow"
    Say "  cd `$HOME ; git clone https://github.com/baghdadhost-wq/Allinone.git ; cd Allinone ; .\install.cmd" "Yellow"
    exit 1
}

# ---------------------------------------------------------------- Python
$py = Find-Python
if (-not $py) {
    Say "Python 3.10+ was not found." "Yellow"
    if ((Have-Winget) -and (Ask "Install Python 3.12 with winget now?")) {
        winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
        Refresh-Path
        $py = Find-Python
    }
    if (-not $py) {
        Say "Install Python 3.10+ from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run install.cmd again." "Red"
        exit 1
    }
}
Say ("Python: " + ($py -join " "))

# ------------------------------------------------------------------- Git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Say "Git was not found (needed to download FreeLLMAPI; Claude Code also uses Git Bash)." "Yellow"
    if ((Have-Winget) -and (Ask "Install Git for Windows with winget now?")) {
        winget install -e --id Git.Git --accept-source-agreements --accept-package-agreements
        Refresh-Path
    }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Say "Install Git from https://git-scm.com/download/win, then run install.cmd again." "Red"
        exit 1
    }
}
Say "Git: OK"

# ------------------------------------------- Node.js, gateways, Claude Code
$pyArgs = @()
if ($py.Length -gt 1) { $pyArgs += $py[1..($py.Length - 1)] }
& $py[0] @pyArgs "$Root\allinone.py" install @args
$code = $LASTEXITCODE

# -------------------------------------------------- optional: add to PATH
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($code -eq 0 -and ($userPath -notlike "*$Root*")) {
    if (Ask "Add Allinone to your PATH so you can type 'allinone' in any terminal?") {
        [Environment]::SetEnvironmentVariable("Path", "$userPath;$Root", "User")
        Say "Done. Open a NEW terminal, then run:  allinone" "Green"
    } else {
        Say "Start it with:  $Root\allinone.cmd" "Green"
    }
}
exit $code
