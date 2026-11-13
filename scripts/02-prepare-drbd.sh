#!/bin/sh
# Validate and initialize the DRBD resource used by the HA counter demo.
set -eu

resource=
configuration=
confirmation=
device=
install_config=false
demote=false
dry_run=false

usage() {
    cat >&2 <<'EOF'
Usage:
  02-prepare-drbd.sh --resource NAME [--config FILE --install-config] validate
  02-prepare-drbd.sh --resource NAME --confirm-resource NAME [--dry-run] create-metadata
  02-prepare-drbd.sh --resource NAME --device /dev/drbdN --confirm-resource NAME [--dry-run] initialize-source
  02-prepare-drbd.sh --resource NAME [--demote] [--dry-run] handoff

`create-metadata` destroys existing metadata on the resource's backing disks.
`initialize-source` force-promotes the resource and formats --device as ext4.
EOF
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

fail() {
    printf '%s\n' "$*" >&2
    exit 1
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --resource)
            [ "$#" -ge 2 ] || fail '--resource needs a value'
            resource=$2
            shift 2
            ;;
        --config)
            [ "$#" -ge 2 ] || fail '--config needs a value'
            configuration=$2
            shift 2
            ;;
        --confirm-resource)
            [ "$#" -ge 2 ] || fail '--confirm-resource needs a value'
            confirmation=$2
            shift 2
            ;;
        --device)
            [ "$#" -ge 2 ] || fail '--device needs a value'
            device=$2
            shift 2
            ;;
        --install-config) install_config=true; shift ;;
        --demote) demote=true; shift ;;
        --dry-run) dry_run=true; shift ;;
        validate|create-metadata|initialize-source|handoff)
            action=$1
            shift
            break
            ;;
        --help|-h) usage; exit 0 ;;
        *) fail "Unknown option or action: $1" ;;
    esac
done

[ "${action:-}" != '' ] || { usage; exit 2; }
[ "$#" -eq 0 ] || fail "Unexpected argument: $1"
[ "$resource" != '' ] || fail '--resource is required'

validate_config() {
    [ "$configuration" != '' ] || fail '--config is required for validate'
    [ -f "$configuration" ] || fail "DRBD configuration does not exist: $configuration"
    if grep -q 'REPLACE_' "$configuration"; then
        fail "DRBD configuration contains a placeholder: $configuration"
    fi
}

require_confirmation() {
    if [ "$confirmation" != "$resource" ]; then
        fail "Refusing destructive action; pass --confirm-resource $resource"
    fi
}

case "$action" in
    validate)
        validate_config
        run sudo drbdadm -c "$configuration" dump "$resource"
        if "$install_config"; then
            run sudo install -m 0644 "$configuration" "/etc/drbd.d/$resource.res"
        fi
        run sudo modprobe drbd
        run sudo drbdadm dump "$resource"
        ;;
    create-metadata)
        require_confirmation
        run sudo drbdadm create-md "$resource"
        run sudo drbdadm up "$resource"
        ;;
    initialize-source)
        require_confirmation
        [ "$device" != '' ] || fail '--device is required for initialize-source'
        case "$device" in /dev/*) ;; *) fail '--device must be an absolute /dev path' ;; esac
        if "$dry_run"; then
            run sudo drbdadm sh-dev "$resource"
        else
            configured_device=$(sudo drbdadm sh-dev "$resource")
            [ "$device" = "$configured_device" ] || fail "--device $device does not match $resource device $configured_device"
        fi
        run sudo drbdadm primary --force "$resource"
        run sudo mkfs.ext4 "$device"
        ;;
    handoff)
        require_confirmation
        if "$demote"; then
            run sudo drbdadm secondary "$resource"
        fi
        run sudo drbdadm down "$resource"
        ;;
esac
