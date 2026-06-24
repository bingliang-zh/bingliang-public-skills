# Bilibili Audio Slicer

Local web tool for clipping short notification sounds from a Bilibili video URL.

The browser provides preview, playback, waveform selection, and clip export.
The local Python server downloads audio with `yt-dlp`, exports clips with
`ffmpeg`, writes MP3 files to `hooks/stop-sound/sounds/`, and can update
`hooks/stop-sound/sounds.yaml`.

Use this only for audio you own, have permission to reuse, or are keeping for
local/private use. Do not use it to bypass paid access, DRM, or platform limits.

## Requirements

- Python 3.9+
- `yt-dlp`
- `ffmpeg`

The server checks `C:\Tools` first, then falls back to `PATH`.

Check that both commands are available:

```powershell
yt-dlp --version
ffmpeg -version
```

## Start

From this repository:

```powershell
python tools\bilibili-audio-slicer\server.py
```

Then open:

```text
http://127.0.0.1:8765
```

If port `8765` is busy:

```powershell
$env:PORT = "8766"
python tools\bilibili-audio-slicer\server.py
```

## Workflow

1. Paste a Bilibili video URL.
2. Fill `Cookies` only when the video requires your login. Use a browser name
   such as `chrome`, `edge`, or `firefox`, or a Netscape-format cookies file path
   such as `C:\Tools\cookies.txt`, or paste the full Netscape-format cookies.txt
   content directly into the field.
3. If Chrome cookie reading fails, close Chrome and retry, use another browser
   name, or provide a cookies file path.
4. Click `Load Audio`.
5. Drag on the waveform to select a slice, or edit `Start` and `End` manually.
   Use `Zoom`, `Position`, or the mouse wheel over the waveform to inspect a
   smaller time range.
6. Fill `ID`. The MP3 filename is generated from `ID`.
7. Click `Export Clip`.

Export writes:

- `hooks/stop-sound/sounds/<filename>.mp3`
- an updated entry in `hooks/stop-sound/sounds.yaml`, when enabled

Temporary downloads are stored under `tools/bilibili-audio-slicer/.work/` and are
ignored by git.

## Troubleshooting

If Bilibili returns `HTTP Error 412: Precondition Failed`, retry with the full
video URL and provide cookies in the `Cookies` field. Use `edge`, `firefox`, or a
`cookies.txt` path when Chrome cookie reading is blocked by the running browser.
