# bingliang-public-skills

Public, TUI-neutral building blocks for local coding-agent setups: hook
specifications, their assets, and a curated list of alternative third-party
skill packs.

This repository is consumed by the private superset repo `bingliang-skills`,
which fetches the contents here at install/check time. Nothing in this repo is
TUI-specific: hook intent, params, and assets are described in neutral specs so
any AI CLI (Codex, Claude Code, etc.) can generate its own concrete hook config
from them.

## Layout

- `hooks/<hook-name>/` - a TUI-neutral hook spec (`spec.json`) plus any assets it
  installs, such as sounds and helper scripts.
- `hooks/<hook-name>/sounds.yaml` - optional catalog of bundled sound assets,
  tracked by `id` and relative `path`.
- `tools/bilibili-audio-slicer/` - local web tool for previewing Bilibili audio,
  selecting short waveform slices, and exporting stop-sound clips.
- `alternatives/skills.yaml` - optional external skill packs to consider,
  tracked by name and source. These are listed for awareness and are not
  vendored here.

## Hooks

| Hook | Spec | Assets |
| --- | --- | --- |
| `stop-sound` | `hooks/stop-sound/spec.json` | `hooks/stop-sound/sounds/*.mp3`, `hooks/stop-sound/sounds.yaml`, `hooks/stop-sound/stop-sound.ps1` |

### `stop-sound`

Plays a local notification sound when the agent reaches a stop/completion event.

- **macOS**: plays the selected sound via `afplay`.
- **Windows**: runs `stop-sound.ps1`, which plays the selected sound with the
  .NET `MediaPlayer` and falls back to a system sound if playback fails. The
  script is the source of record; no compiled binary is committed.

#### Adding More Stop Sounds

To add another bundled sound:

1. Add the audio file under `hooks/stop-sound/sounds/`. Keep filenames stable
   and shell-friendly, for example `bell-soft.mp3`.
2. Add an entry to `hooks/stop-sound/sounds.yaml` with its `id` and `path`.
3. To make it the active default, set `params.sound_asset` in
   `hooks/stop-sound/spec.json` to the same relative path, for example:

```json
"params": {
  "sound_asset": "sounds/bell-soft.mp3",
  "sound_catalog": "sounds.yaml"
}
```

#### Sound Catalog

`hooks/stop-sound/sounds.yaml` is a simple list of available notification
sounds. Use one entry per file:

```yaml
- id: bell-soft
  path: sounds/bell-soft.mp3
```

Catalog fields:

- `id` - stable identifier used by humans and future tooling.
- `path` - file path relative to `hooks/stop-sound/`; keep bundled audio under
  `sounds/`. This can also be used as `params.sound_asset`.

## Hook Spec Format

Each `hooks/<name>/spec.json` is a small, TUI-neutral description:

```jsonc
{
  "name": "stop-sound",
  "description": "...",
  "event": "Stop",
  "params": {
    "sound_asset": "sounds/mambo.mp3",
    "sound_catalog": "sounds.yaml"
  },
  "platforms": {
    "darwin": {
      "params": {
        "player_command": "afplay",
        "timeout_seconds": 5
      },
      "action": {
        "type": "command",
        "command_template": "{player_command} \"{asset_path}\""
      }
    },
    "windows": {
      "params": {
        "timeout_seconds": 10
      },
      "install_assets": [
        {
          "source": "stop-sound.ps1",
          "target": "{codex_root}\\stop-sound.ps1"
        }
      ],
      "action": {
        "type": "command",
        "command_template": "powershell -NoProfile -ExecutionPolicy Bypass -File \"{codex_root}\\stop-sound.ps1\" --trigger --sound \"{asset_path}\""
      }
    }
  }
}
```

Template variables (`{codex_root}`, `{asset_path}`, `{player_command}`) are filled
in by the consuming repo's generator when it materializes the concrete hook config
for a specific TUI.

## Consuming This Repo

`bingliang-skills` fetches this repo at install/check time. To point it at a local
checkout instead of cloning from GitHub, set:

```sh
export BINGLIANG_PUBLIC_SKILLS_DIR=/path/to/bingliang-public-skills
```

## Local Tools

### Bilibili Audio Slicer

Run the local slicer when you need to preview a Bilibili video's audio, select a
short range from a waveform, and export an MP3 into `hooks/stop-sound/sounds/`:

```powershell
python tools\bilibili-audio-slicer\server.py
```

Then open `http://127.0.0.1:8765`. The tool requires local `yt-dlp` and
`ffmpeg`. See `tools/bilibili-audio-slicer/README.md` for details.

## Alternatives

Alternative third-party skill packs are tracked in `alternatives/skills.yaml` by
name and source. They are listed for awareness and are not vendored into this
repository.
