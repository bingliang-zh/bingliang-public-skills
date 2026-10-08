#!/usr/bin/env bash
# CLI-neutral Linux stop notification. Requires Bash and GNU coreutils timeout.
# Audio failures must never block the agent or write non-JSON text to stdout.
set -u

trigger=false
sound=""
while (( $# )); do
    case "$1" in
        --trigger) trigger=true; shift ;;
        --sound)
            if (( $# < 2 )); then
                printf 'stop-sound: --sound requires a path\n' >&2
                exit 0
            fi
            sound=$2
            shift 2
            ;;
        *) shift ;;
    esac
done
$trigger || exit 0

if [[ -z "$sound" ]]; then
    script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
    sound="$script_dir/sounds/mambo.mp3"
fi
if [[ ! -f "$sound" ]]; then
    printf 'stop-sound: sound asset not found: %s\n' "$sound" >&2
    exit 0
fi
# Use an absolute path so filenames beginning with "-" cannot become options.
[[ "$sound" = /* ]] || sound="$PWD/$sound"
if ! command -v timeout >/dev/null 2>&1; then
    printf 'stop-sound: GNU coreutils timeout is required\n' >&2
    exit 0
fi

# One shared budget across all backends (plus a one-second forced-kill grace).
deadline=$((SECONDS + 8))
for player in pw-play ffplay mpv mpg123 gst-play-1.0; do
    command -v "$player" >/dev/null 2>&1 || continue
    remaining=$((deadline - SECONDS))
    (( remaining > 0 )) || break
    case "$player" in
        pw-play) args=("$sound") ;;
        ffplay) args=(-nodisp -autoexit -loglevel error "$sound") ;;
        mpv) args=(--no-config --no-video --really-quiet "$sound") ;;
        mpg123) args=(-q "$sound") ;;
        gst-play-1.0) args=(--no-interactive "$sound") ;;
    esac
    # Disconnect hook stdin; ffplay/mpv must not read the event payload.
    timeout --kill-after=1s "${remaining}s" "$player" "${args[@]}" \
        </dev/null >/dev/null 2>&1 && exit 0
done
printf 'stop-sound: no player succeeded (tried pw-play, ffplay, mpv, mpg123, gst-play-1.0); check audio session/codecs or install ffmpeg\n' >&2
exit 0
