"""Behavioral tests for the executable HA setup scripts."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PREPARE = ROOT / "scripts" / "01-prepare-ubuntu.sh"
DRBD = ROOT / "scripts" / "02-prepare-drbd.sh"
PACEMAKER = ROOT / "scripts" / "03-configure-pacemaker.sh"


def fake_sudo_environment(directory: Path, drbd_device: str = "/dev/drbd0") -> tuple[dict[str, str], Path]:
    command_directory = directory / "commands"
    command_directory.mkdir()
    command_log = directory / "command.log"
    sudo = command_directory / "sudo"
    sudo.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$COMMAND_LOG\"\n"
        "if [ \"$1\" = drbdadm ] && [ \"$2\" = sh-dev ]; then\n"
        "  printf '%s\\n' \"$FAKE_DRBD_DEVICE\"\n"
        "fi\n",
        encoding="utf-8",
    )
    sudo.chmod(0o755)
    environment = os.environ | {
        "PATH": f"{command_directory}:{os.environ['PATH']}",
        "COMMAND_LOG": str(command_log),
        "FAKE_DRBD_DEVICE": drbd_device,
    }
    return environment, command_log


class UbuntuPreparationScriptTests(unittest.TestCase):
    def run_script(self, os_release: str, *args: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            release_file = Path(temporary_directory) / "os-release"
            release_file.write_text(os_release, encoding="utf-8")
            environment = os.environ | {"OS_RELEASE_FILE": str(release_file)}
            return subprocess.run(
                [str(PREPARE), *args],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

    def test_dry_run_prints_ubuntu_2604_installation(self) -> None:
        result = self.run_script('ID=ubuntu\nVERSION_ID="26.04"\n', "--dry-run")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("sudo apt install -y software-properties-common", result.stdout)
        self.assertIn("resource-agents-base resource-agents-extra fence-agents-vbox", result.stdout)
        self.assertIn("sudo modprobe drbd", result.stdout)

    def test_rejects_an_unsupported_operating_system_before_running_apt(self) -> None:
        result = self.run_script('ID=debian\nVERSION_ID="13"\n', "--dry-run")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Ubuntu Server 26.04", result.stderr)


class DrbdPreparationScriptTests(unittest.TestCase):
    def run_script(
        self, *args: str, environment: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(DRBD), *args],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_validate_rejects_example_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            configuration = Path(temporary_directory) / "counter.res"
            configuration.write_text("disk /dev/REPLACE_NODE1_DATA_DISK;\n", encoding="utf-8")

            result = self.run_script(
                "--resource", "counter", "--config", str(configuration), "validate"
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("placeholder", result.stderr)

    def test_create_metadata_requires_a_matching_confirmation(self) -> None:
        result = self.run_script("--resource", "counter", "create-metadata")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--confirm-resource counter", result.stderr)

    def test_create_metadata_rejects_a_confirmation_for_another_resource(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment, command_log = fake_sudo_environment(Path(temporary_directory))
            result = self.run_script(
                "--resource", "counter", "--confirm-resource", "other", "create-metadata",
                environment=environment,
            )
            commands = command_log.read_text(encoding="utf-8") if command_log.exists() else ""

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--confirm-resource counter", result.stderr)
        self.assertEqual(commands, "")

    def test_confirmed_metadata_creation_prints_both_drbd_commands_in_dry_run(self) -> None:
        result = self.run_script(
            "--resource", "counter", "--confirm-resource", "counter", "--dry-run", "create-metadata"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("sudo drbdadm create-md counter", result.stdout)
        self.assertIn("sudo drbdadm up counter", result.stdout)

    def test_validate_parses_the_supplied_candidate_configuration_before_installing_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            configuration = temporary_path / "counter.res"
            configuration.write_text("resource counter { }\n", encoding="utf-8")
            environment, command_log = fake_sudo_environment(temporary_path)

            result = self.run_script(
                "--resource", "counter", "--config", str(configuration), "validate", environment=environment
            )

            commands = command_log.read_text(encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"drbdadm -c {configuration} dump counter", commands)

    def test_initialize_source_rejects_a_device_other_than_the_resource_device(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment, command_log = fake_sudo_environment(Path(temporary_directory), "/dev/drbd0")
            result = self.run_script(
                "--resource", "counter", "--device", "/dev/sdb1",
                "--confirm-resource", "counter", "initialize-source", environment=environment
            )
            commands = command_log.read_text(encoding="utf-8")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match", result.stderr)
        self.assertNotIn("primary", commands)
        self.assertNotIn("mkfs.ext4", commands)

    def test_handoff_requires_a_matching_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment, command_log = fake_sudo_environment(Path(temporary_directory))
            result = self.run_script("--resource", "counter", "handoff", environment=environment)
            commands = command_log.read_text(encoding="utf-8") if command_log.exists() else ""

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--confirm-resource counter", result.stderr)
        self.assertEqual(commands, "")


class PacemakerConfigurationScriptTests(unittest.TestCase):
    def run_script(
        self, *args: str, environment: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(PACEMAKER), *args],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_refuses_missing_required_inputs(self) -> None:
        result = self.run_script("configure-resources")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--resource is required", result.stderr)

    def test_dry_run_prints_the_counter_resource_sequence(self) -> None:
        result = self.run_script(
            "--resource", "counter",
            "--device", "/dev/drbd0",
            "--mount-dir", "/srv/ha-counter",
            "--vip", "192.0.2.100",
            "--prefix", "24",
            "--dry-run",
            "configure-resources",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("sudo pcs resource create counter-drbd ocf:linbit:drbd drbd_resource=counter", result.stdout)
        self.assertIn("sudo pcs resource create counter-fs ocf:heartbeat:Filesystem", result.stdout)
        self.assertIn("sudo pcs constraint colocation add counter-service", result.stdout)

    def test_malformed_vip_is_rejected_before_pcs_is_called(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment, command_log = fake_sudo_environment(Path(temporary_directory))
            result = self.run_script(
                "--resource", "counter", "--device", "/dev/drbd0",
                "--mount-dir", "/srv/ha-counter", "--vip", "not-an-ip",
                "--prefix", "24", "configure-resources", environment=environment,
            )
            commands = command_log.read_text(encoding="utf-8") if command_log.exists() else ""

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("IPv4", result.stderr)
        self.assertEqual(commands, "")

    def test_refuses_a_mount_path_other_than_the_service_mount(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment, command_log = fake_sudo_environment(Path(temporary_directory))
            result = self.run_script(
                "--resource", "counter", "--device", "/dev/drbd0",
                "--mount-dir", "/srv/other", "--vip", "192.0.2.100",
                "--prefix", "24", "configure-resources", environment=environment,
            )
            commands = command_log.read_text(encoding="utf-8") if command_log.exists() else ""

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("/srv/ha-counter", result.stderr)
        self.assertEqual(commands, "")


if __name__ == "__main__":
    unittest.main()
