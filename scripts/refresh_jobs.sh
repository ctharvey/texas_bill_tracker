#!/bin/sh
# Start the server jobs the deployer asked for (marker files in /var/lib/texas-bill-atlas/refresh), one at a time.
# Runs as root from texas-bill-refresh.service. The installed copy (/usr/local/lib/texas-bill-atlas/) is what runs,
# never the repository's, and only the fixed job names below are honoured: never the review unit.
set -u
dir=${TBA_REFRESH_DIR:-/var/lib/texas-bill-atlas/refresh}  # Override for tests only.
[ -d "$dir" ] && [ ! -L "$dir" ] || exit 0
status=0
for job in members data agent og; do
    [ -e "$dir/$job" ] || [ -L "$dir/$job" ] || continue
    rm -f "$dir/$job"  # Before starting: a marker written during the run triggers one more run afterwards.
    unit="texas-bill-$job.service"
    # A run already in progress took its code before this push; wait for it, then run again with the new code.
    case "$(systemctl show -p ActiveState --value "$unit")" in
        activating|active|reloading) echo "$unit already running; waiting for it first"; systemctl start "$unit" ;;
    esac
    echo "Starting $unit"
    if ! systemctl start "$unit"; then
        echo "$unit failed"
        status=1
    fi
done
exit $status
