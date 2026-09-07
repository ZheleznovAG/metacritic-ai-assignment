#!/usr/bin/env sh
set -eu

probe_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
expected_root=$(realpath -m "$HOME/.local/share/metacritic-ai-probe")
if [ "$probe_root" != "$expected_root" ]; then
    printf '%s\n' 'unexpected probe installation path' >&2
    exit 1
fi
case "$probe_root" in
    *[!A-Za-z0-9_./-]*) printf '%s\n' 'probe path contains unsupported characters' >&2; exit 1 ;;
esac

begin_marker='# BEGIN metacritic-ai-probe SPK-06'
end_marker='# END metacritic-ai-probe SPK-06'
if crontab -l 2>/dev/null | grep -Fq "$begin_marker"; then
    printf '%s\n' 'probe cron block already exists' >&2
    exit 1
fi

chmod 700 "$probe_root"
chmod 700 "$probe_root"/*.sh "$probe_root"/*.py
/usr/bin/python3 "$probe_root/probe_tick.py" manual

original_cron=$(mktemp "$probe_root/.crontab.original.XXXXXX")
new_cron=$(mktemp "$probe_root/.crontab.new.XXXXXX")
cleanup() {
    rm -f -- "$original_cron" "$new_cron"
}
trap cleanup EXIT HUP INT TERM

if crontab -l > "$original_cron" 2>/dev/null; then
    had_crontab=yes
else
    had_crontab=no
    : > "$original_cron"
fi
cp -- "$original_cron" "$new_cron"
{
    printf '\n%s\n' "$begin_marker"
    printf '0 * * * * /usr/bin/python3 %s/probe_tick.py hourly >> %s/timer.log 2>&1\n' "$probe_root" "$probe_root"
    printf '@reboot %s/start_probe.sh >> %s/server.log 2>&1\n' "$probe_root" "$probe_root"
    printf '%s\n' "$end_marker"
} >> "$new_cron"
crontab "$new_cron"

if ! "$probe_root/start_probe.sh"; then
    if [ "$had_crontab" = yes ]; then
        crontab "$original_cron"
    else
        : | crontab -
    fi
    exit 1
fi
printf '%s\n' 'probe_install=complete'
