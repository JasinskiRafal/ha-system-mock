#!/bin/sh
# Prepare one Ubuntu Server 26.04 amd64 node for the HA counter demo.
set -eu

dry_run=false
os_release_file=${OS_RELEASE_FILE:-/etc/os-release}

usage() {
    printf '%s\n' "Usage: $0 [--dry-run]" >&2
}

run() {
    if "$dry_run"; then
        printf '+ '
        printf '%s ' "$@"
        printf '\n'
    else
        "$@"
    fi
}

case ${1:-} in
    '') ;;
    --dry-run) dry_run=true ;;
    --help|-h) usage; exit 0 ;;
    *) usage; exit 2 ;;
esac

if [ ! -r "$os_release_file" ]; then
    printf 'Cannot read operating-system metadata: %s\n' "$os_release_file" >&2
    exit 1
fi

# shellcheck disable=SC1090
. "$os_release_file"
if [ "${ID:-}" != ubuntu ] || [ "${VERSION_ID:-}" != 26.04 ]; then
    printf 'This script requires Ubuntu Server 26.04 LTS (amd64).\n' >&2
    exit 1
fi

if [ "$(dpkg --print-architecture)" != amd64 ]; then
    printf 'This script requires the amd64 architecture.\n' >&2
    exit 1
fi

run sudo apt update
run sudo apt install -y software-properties-common
run sudo add-apt-repository -y universe
run sudo apt update
run sudo apt install -y linux-generic python3 sqlite3 curl openssh-server \
    pcs pacemaker corosync drbd-utils resource-agents-base \
    resource-agents-extra fence-agents-vbox

printf '%s\n' 'If linux-generic installed a new kernel, reboot before running without --dry-run.'
run sudo modprobe drbd
run modinfo drbd
run drbdadm --version
run test -x /usr/lib/ocf/resource.d/linbit/drbd
run test -x /usr/lib/ocf/resource.d/heartbeat/Filesystem
run test -x /usr/lib/ocf/resource.d/heartbeat/IPaddr2
run test -x /usr/sbin/fence_vbox
run test -x /usr/lib/drbd/crm-fence-peer.9.sh
run test -x /usr/lib/drbd/crm-unfence-peer.9.sh
run pcs resource describe ocf:linbit:drbd
run pcs stonith describe fence_vbox
