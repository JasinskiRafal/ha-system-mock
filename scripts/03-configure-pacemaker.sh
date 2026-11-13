#!/bin/sh
# Create the Pacemaker resources for the HA counter demo after fencing works.
set -eu

resource=
device=
mount_dir=
vip=
prefix=
dry_run=false

usage() {
    cat >&2 <<'EOF'
Usage:
  03-configure-pacemaker.sh --resource NAME --device /dev/drbdN \
    --mount-dir /path --vip IPV4 --prefix CIDR [--dry-run] configure-resources

Run only after the cluster and both fencing paths are configured and verified.
The script intentionally refuses to overwrite existing PCS resources.
EOF
}

fail() {
    printf '%s\n' "$*" >&2
    exit 1
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

valid_ipv4() {
    case "$1" in *[!0-9.]*|.*|*.) return 1 ;; esac
    old_ifs=$IFS
    IFS=.
    set -- $1
    IFS=$old_ifs
    [ "$#" -eq 4 ] || return 1
    for octet in "$@"; do
        [ "$octet" != '' ] || return 1
        [ "$octet" -le 255 ] || return 1
    done
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --resource|--device|--mount-dir|--vip|--prefix)
            [ "$#" -ge 2 ] || fail "$1 needs a value"
            case "$1" in
                --resource) resource=$2 ;;
                --device) device=$2 ;;
                --mount-dir) mount_dir=$2 ;;
                --vip) vip=$2 ;;
                --prefix) prefix=$2 ;;
            esac
            shift 2
            ;;
        --dry-run) dry_run=true; shift ;;
        configure-resources)
            action=$1
            shift
            break
            ;;
        --help|-h) usage; exit 0 ;;
        *) fail "Unknown option or action: $1" ;;
    esac
done

[ "${action:-}" = configure-resources ] || { usage; exit 2; }
[ "$#" -eq 0 ] || fail "Unexpected argument: $1"
[ "$resource" != '' ] || fail '--resource is required'
[ "$device" != '' ] || fail '--device is required'
[ "$mount_dir" != '' ] || fail '--mount-dir is required'
[ "$vip" != '' ] || fail '--vip is required'
[ "$prefix" != '' ] || fail '--prefix is required'

case "$resource" in *[!A-Za-z0-9_-]*) fail '--resource may contain only letters, digits, underscores, and hyphens' ;; esac
case "$device" in /dev/*) ;; *) fail '--device must be an absolute /dev path' ;; esac
case "$mount_dir" in /srv/ha-counter) ;; *) fail '--mount-dir must be /srv/ha-counter for deploy/ha-counter.service' ;; esac
case "$prefix" in *[!0-9]*) fail '--prefix must be an integer from 0 to 32' ;; esac
[ "$prefix" -le 32 ] || fail '--prefix must be an integer from 0 to 32'
valid_ipv4 "$vip" || fail '--vip must be a valid IPv4 address'

drbd_resource="$resource-drbd"
service_group="$resource-service"

run sudo pcs resource create "$drbd_resource" ocf:linbit:drbd "drbd_resource=$resource" \
    op monitor interval=31s role=Unpromoted op monitor interval=29s role=Promoted
run sudo pcs resource promotable "$drbd_resource" \
    promoted-max=1 promoted-node-max=1 clone-max=2 clone-node-max=1 notify=true
run sudo pcs resource create "$resource-fs" ocf:heartbeat:Filesystem \
    "device=$device" "directory=$mount_dir" fstype=ext4 --group "$service_group"
run sudo pcs resource create "$resource-app" systemd:ha-counter --group "$service_group" \
    op monitor interval=10s
run sudo pcs resource create "$resource-ip" ocf:heartbeat:IPaddr2 \
    "ip=$vip" "cidr_netmask=$prefix" --group "$service_group" op monitor interval=10s
run sudo pcs constraint order promote "$drbd_resource-clone" then start "$service_group"
run sudo pcs constraint colocation add "$service_group" with "$drbd_resource-clone" \
    score=INFINITY with-rsc-role=Promoted
run sudo pcs status --full
run sudo drbdadm status
