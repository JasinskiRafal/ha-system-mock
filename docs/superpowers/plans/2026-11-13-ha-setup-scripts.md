# HA Setup Scripts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide guarded, testable shell scripts for the Ubuntu, DRBD, and Pacemaker steps documented in the README.

**Architecture:** Three independent POSIX shell entry points accept explicit
arguments and use `--dry-run` where it can safely expose commands. A Python
unittest module invokes them through a temporary fake command directory so the
argument validation and command sequence are tested without root privileges or
cluster software.

**Tech Stack:** POSIX shell, Python standard-library unittest.

**Spec:** `docs/superpowers/specs/2026-11-13-ha-setup-scripts-design.md`

## Global Constraints

- Target Ubuntu Server 26.04 LTS amd64 only.
- Do not embed site-specific topology, credentials, disks, or addresses.
- DRBD metadata creation and formatting require `--confirm-resource NAME`.
- Fencing and VM/network setup remain manual.

## Review Focus

- Unsupported operating-system or architecture: package script must stop before package management.
- Example configuration placeholders: DRBD validation must reject them.
- Missing or mismatched confirmation: destructive DRBD actions must not execute.
- Malformed required Pacemaker inputs: resource creation must not start.
- Re-running resource setup: the script must use idempotent PCS create calls only when the caller explicitly chooses configuration.

---

### Task 1: Ubuntu preparation script

**Files:**
- Create: `scripts/01-prepare-ubuntu.sh`
- Create: `tests/test_setup_scripts.py`

**Interfaces:**
- Produces: `scripts/01-prepare-ubuntu.sh [--dry-run]`, exiting nonzero for an unsupported OS or architecture.

- [x] **Step 1: Write failing tests for `--dry-run` and unsupported platform rejection**
- [x] **Step 2: Run `python3 -m unittest tests.test_setup_scripts` and verify failure because the script is absent**
- [x] **Step 3: Implement platform checks, package install command, and binary/agent checks**
- [x] **Step 4: Run the focused tests and verify they pass**

### Task 2: Guarded DRBD script

**Files:**
- Create: `scripts/02-prepare-drbd.sh`
- Modify: `tests/test_setup_scripts.py`

**Interfaces:**
- Consumes: `--resource NAME`, `--confirm-resource NAME`, and a named action.
- Produces: `validate`, `create-metadata`, `initialize-source`, and `handoff` actions.

- [x] **Step 1: Write failing tests for placeholder rejection and confirmation enforcement**
- [x] **Step 2: Run focused tests and verify failure because the script is absent**
- [x] **Step 3: Implement validation and the guarded lifecycle actions**
- [x] **Step 4: Run focused tests and verify they pass**

### Task 3: Pacemaker resources and documentation

**Files:**
- Create: `scripts/03-configure-pacemaker.sh`
- Modify: `tests/test_setup_scripts.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: resource, device, mount directory, virtual IP, and CIDR prefix.
- Produces: the PCS resources and ordering/colocation constraints from the README.

- [x] **Step 1: Write failing tests for missing input and the dry-run command sequence**
- [x] **Step 2: Run focused tests and verify failure because the script is absent**
- [x] **Step 3: Implement guarded PCS resource creation and update README usage**
- [x] **Step 4: Run focused tests, full tests, shell syntax checks, and `git diff --check`**
