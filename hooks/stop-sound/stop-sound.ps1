<#
.SYNOPSIS
    Windows notification sound for the "stop-sound" hook.

.DESCRIPTION
    Invoked as:
      powershell -ExecutionPolicy Bypass -File stop-sound.ps1 --trigger --sound path\to\sound.mp3

    Plays the requested MP3 using the .NET
    WPF MediaPlayer, blocking until the clip finishes. If media playback is
    unavailable for any reason, it falls back to the system beep so the user
    still gets an audible signal.

    This script is the source of record for the stop-sound notifier on
    Windows. It is CLI-neutral and works for any AI CLI that runs the
    stop-sound hook; it replaces a previously shipped prebuilt binary, so
    the repository no longer needs to track a compiled executable.
#>

[CmdletBinding()]
param(
    # Only act when the documented trigger flag is present; ignore any other
    # arguments so the hook can pass extra context without side effects.
    # (Named $Arguments, not $Args, to avoid shadowing the automatic variable.)
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Arguments
)

$ErrorActionPreference = 'Stop'

if (-not ($Arguments -contains '--trigger')) {
    exit 0
}

function Get-ArgumentValue {
    param(
        [Parameter(Mandatory = $true)]
        [string[]] $InputArguments,

        [Parameter(Mandatory = $true)]
        [string] $Name
    )

    for ($index = 0; $index -lt $InputArguments.Count; $index++) {
        if ($InputArguments[$index] -eq $Name -and ($index + 1) -lt $InputArguments.Count) {
            return $InputArguments[$index + 1]
        }
    }

    return $null
}

$requestedSoundPath = Get-ArgumentValue -InputArguments $Arguments -Name '--sound'
if ([string]::IsNullOrWhiteSpace($requestedSoundPath)) {
    # Backward-compatible fallback for older generated hook commands.
    $requestedSoundPath = Join-Path -Path $PSScriptRoot -ChildPath 'sounds\mambo.mp3'
}

$soundPath = $requestedSoundPath

function Invoke-Fallback {
    # Built-in system sound; works even without the audio file or an MP3 codec.
    [System.Media.SystemSounds]::Asterisk.Play()
    Start-Sleep -Milliseconds 500
}

try {
    $soundPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($requestedSoundPath)

    if (-not (Test-Path -LiteralPath $soundPath)) {
        throw "sound asset not found: $soundPath"
    }

    Add-Type -AssemblyName PresentationCore

    $player = New-Object System.Windows.Media.MediaPlayer
    $player.Open([Uri]$soundPath)

    # Wait briefly for the media to open so NaturalDuration is populated.
    $deadline = 50  # 50 * 100ms = 5s
    while (-not $player.NaturalDuration.HasTimeSpan -and $deadline -gt 0) {
        Start-Sleep -Milliseconds 100
        $deadline--
    }

    $player.Play()

    if ($player.NaturalDuration.HasTimeSpan) {
        # Pad slightly so the tail of the clip is not clipped.
        $waitMs = [int]$player.NaturalDuration.TimeSpan.TotalMilliseconds + 250
    } else {
        # Conservative fallback wait so the process does not linger.
        $waitMs = 3000
    }

    Start-Sleep -Milliseconds $waitMs
    $player.Close()
    exit 0
}
catch {
    [Console]::Error.WriteLine("stop-sound: media playback failed: $($_.Exception.Message)")
    Invoke-Fallback
    exit 0
}
