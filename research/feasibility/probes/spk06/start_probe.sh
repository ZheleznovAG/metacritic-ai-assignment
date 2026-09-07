#!/usr/bin/env sh
set -eu

probe_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
pid_file="$probe_root/server.pid"
log_file="$probe_root/server.log"

if [ -f "$pid_file" ]; then
    pid=$(cat "$pid_file")
    case "$pid" in
        ''|*[!0-9]*) printf '%s\n' 'invalid probe PID file' >&2; exit 1 ;;
    esac
    if kill -0 "$pid" 2>/dev/null; then
        command_line=$(tr '\000' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)
        case "$command_line" in
            *"$probe_root/probe_http.py"*) exit 0 ;;
            *) printf '%s\n' 'refusing to reuse a PID owned by another process' >&2; exit 1 ;;
        esac
    fi
    rm -f -- "$pid_file"
fi

umask 077
nohup /usr/bin/python3 "$probe_root/probe_http.py" --port 18080 >> "$log_file" 2>&1 < /dev/null &
pid=$!
printf '%s\n' "$pid" > "$pid_file"

attempt=0
while [ "$attempt" -lt 20 ]; do
    if /usr/bin/curl --fail --silent --show-error --max-time 2 http://127.0.0.1:18080/health >/dev/null; then
        exit 0
    fi
    attempt=$((attempt + 1))
    sleep 0.1
done

command_line=$(tr '\000' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)
case "$command_line" in
    *"$probe_root/probe_http.py"*) kill "$pid" 2>/dev/null || true ;;
esac
rm -f -- "$pid_file"
printf '%s\n' 'probe HTTP process did not become ready' >&2
exit 1
