#!/usr/bin/env sh
set -eu

probe_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
pid_file="$probe_root/server.pid"

if [ ! -f "$pid_file" ]; then
    exit 0
fi

pid=$(cat "$pid_file")
case "$pid" in
    ''|*[!0-9]*) printf '%s\n' 'invalid probe PID file' >&2; exit 1 ;;
esac
command_line=$(tr '\000' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)
case "$command_line" in
    *"$probe_root/probe_http.py"*)
        kill "$pid"
        attempt=0
        while kill -0 "$pid" 2>/dev/null && [ "$attempt" -lt 50 ]; do
            attempt=$((attempt + 1))
            sleep 0.1
        done
        ;;
    *)
        printf '%s\n' 'refusing to stop a PID owned by another process' >&2
        exit 1
        ;;
esac

rm -f -- "$pid_file"
