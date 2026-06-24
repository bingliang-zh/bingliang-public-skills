# bingliang-public-skills

Public, TUI-neutral building blocks for local coding-agent setups: hook
specifications, their assets, and a curated list of alternative third-party
skill packs.

This repository is consumed by the private superset repo `bingliang-skills`,
which fetches the contents here at install/check time. Nothing in this repo is
TUI-specific — hook *intent*, params, and assets are described in neutral specs
so any AI CLI (Codex, Claude Code, etc.) can generate its own concrete hook
config from them.

## Layout

- `hooks/<hook-name>/` — a TUI-neutral hook spec (`spec.json`) plus any assets it
  installs (sounds, helper scripts).
- `alternatives/skills.yaml` — optional external skill packs to consider,
  tracked by name and source. These are listed for awareness and are **not**
  vendored here.

## Hooks

| Hook | Spec | Assets |
| --- | --- | --- |
| `stop-sound` | `hooks/stop-sound/spec.json` | `hooks/stop-sound/mambo.mp3`, `hooks/stop-sound/stop-sound.ps1` |

### `stop-sound`

Plays a local notification sound when the agent reaches a stop/completion event.

- **macOS**: plays `mambo.mp3` via `afplay`.
- **Windows**: runs `stop-sound.ps1`, which plays `mambo.mp3` with the .NET
  `MediaPlayer` (falling back to a system sound if playback fails). The script is
  the source of record — no compiled binary is committed.

## Hook spec format

Each `hooks/<name>/spec.json` is a small, TUI-neutral description:

```jsonc
{
  "name": "stop-sound",
  "description": "…",
  "event": "Stop",                 // the agent lifecycle event to hook
  "params": { "sound_asset": "mambo.mp3" },
  "platforms": {                   // per-OS params, install_assets, and action
    "darwin":  { "params": {…}, "action": { "type": "command", "command_template": "…" } },
    "windows": {
      "params": { "timeout_seconds": 10 },
      "install_assets": [          // files copied next to the generated config
        { "source": "stop-sound.ps1", "target": "{codex_root}\\stop-sound.ps1" },
        { "source": "mambo.mp3",      "target": "{codex_root}\\mambo.mp3" }
      ],
      "action": { "type": "command", "command_template": "…{codex_root}\\stop-sound.ps1 --trigger" }
    }
  }
}
```

Template variables (`{codex_root}`, `{asset_path}`, `{player_command}`) are filled
in by the consuming repo's generator when it materializes the concrete hook config
for a specific TUI.

## Consuming this repo

`bingliang-skills` fetches this repo at install/check time. To point it at a local
checkout instead of cloning from GitHub (for offline work or local development),
set:

```sh
export BINGLIANG_PUBLIC_SKILLS_DIR=/path/to/bingliang-public-skills
```

## Alternatives

Alternative third-party skill packs are tracked in `alternatives/skills.yaml` by
name and source. They are listed for awareness and are not vendored into this
repository.
