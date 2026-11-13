# HA setup scripts design

## Intent

Convert the repeatable Ubuntu 26.04 preparation, DRBD initialization, and
Pacemaker-resource commands in the README into executable shell scripts while
keeping environment-specific networking and VirtualBox fencing configuration
visible and manual.

## Goals

- Provide one script for Ubuntu package and prerequisite verification.
- Provide one guarded script for DRBD configuration validation and lifecycle
  actions.
- Provide one script for Pacemaker storage, service, and virtual-IP resources.
- Require explicit flags for destructive DRBD actions.
- Make scripts practical to test without privileged commands or real hardware.

## Non-goals

- Creating VirtualBox VMs, networking, SSH keys, firewall rules, or fencing
  devices automatically.
- Inferring backing disks, node addresses, credentials, or a virtual IP.
- Bypassing DRBD split-brain recovery or fencing verification.

## Approaches considered

1. One monolithic interactive script: convenient initially, but it would mix
   safe package setup with irreversible storage actions and host-specific
   fencing details.
2. Shell snippets only in the README: no input validation or reusable safety
   boundary.
3. Three focused scripts: selected. Package preparation is rerunnable; DRBD
   uses named, explicitly confirmed actions; Pacemaker takes required values
   as command-line arguments.

## Interfaces

- `scripts/01-prepare-ubuntu.sh [--dry-run]` verifies Ubuntu 26.04 amd64,
  enables `universe`, installs the documented packages, and validates required
  binaries and agents.
- `scripts/02-prepare-drbd.sh --resource NAME [--config FILE --install-config]
  validate` validates a resource configuration and refuses example placeholders.
  Its `create-metadata`, `initialize-source`, and `handoff` actions require
  `--confirm-resource NAME`; the first two are destructive.
- `scripts/03-configure-pacemaker.sh --resource NAME --device PATH --mount-dir
  PATH --vip IPV4 --prefix CIDR configure-resources` creates the promoted DRBD
  clone, filesystem, application, virtual IP, and their constraints.

## Constraints

- Target Ubuntu Server 26.04 LTS amd64 only.
- Use POSIX-compatible shell features available in Ubuntu's `/bin/sh`.
- Do not embed secrets, SSH identities, host addresses, disks, node names, or
  virtual IP defaults.
- Never run `drbdadm create-md` or `mkfs.ext4` without a matching explicit
  confirmation value.
- Preserve README safety warnings and identify what remains manual.
