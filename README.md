# Pacemaker / DRBD counter demo

A two-node active/passive HA demo for Ubuntu VMs. The counter is a small Python HTTP application with a SQLite database on a DRBD-replicated ext4 filesystem. Pacemaker controls DRBD promotion, the filesystem, the application and a floating IP; Corosync supplies cluster membership. The same application is installed on both nodes, but only the active node serves it. It automatically commits a counter increment about every half second, even with no browser open. The page polls for updates and reconnects after a failover; the optional button adds an extra increment.

This repository is a starting point: the cluster setup below has not yet been exercised on the target VMs. Test all fencing and failover steps before relying on it. A failed request during failover may need retrying; do not automatically retry an increment after an ambiguous response because it might have committed.

## First run: two standalone VMs

This first exercise only needs Python and a network connection. Each VM runs its own application and its own local SQLite database: **the counters are independent and are not synchronized**. There is no virtual IP or automatic failover yet. Stop the standalone processes before starting the later cluster setup.

### 1. Prepare the VMs

1. Create two Ubuntu Server VMs in VirtualBox, ideally with the same Ubuntu release. Assign distinct hostnames, for example `node1` and `node2`.
2. In each VM's VirtualBox network settings, select **Bridged Adapter** on a network interface connected to your LAN. Start both VMs and confirm that each has its own reachable LAN IP address. Bridging over Wi-Fi depends on the host and network; if a VM is unreachable, check the VirtualBox adapter and network first.
3. Log in to each VM and install Python and curl:

   ```sh
   sudo apt update
   sudo apt install -y python3 curl
   hostname
   hostname -I
   ```

   Record the LAN address printed for each VM. For remote shell access, install and start `openssh-server` on each VM and allow SSH through its firewall before disconnecting. For the standalone exercise, a browser must be able to reach TCP port 8080 on each VM; for example, if Ubuntu's UFW firewall is enabled, use `sudo ufw allow 8080/tcp` on each VM. Restrict access to your trusted LAN where appropriate.

The separate empty data disks, fixed addresses, and reserved virtual IP described below are needed for the later DRBD and Pacemaker setup, not for this standalone test.

### 2. Copy the application to each VM

On the computer that has this repository, run the following from the repository directory, replacing the username and IP with each VM's actual SSH login and LAN address:

```sh
scp counter.py USER@NODE1_IP:~/counter.py
scp counter.py USER@NODE2_IP:~/counter.py
```

Alternatively, copy `counter.py` into your home directory on each VM using your preferred file transfer method. Python uses only its standard library; there are no application dependencies to install and no compilation step.

### 3. Start and inspect each counter

Open a terminal or SSH session to **each VM**, then run the same commands in both sessions:

```sh
mkdir -p ~/ha-counter-data
python3 ~/counter.py --host 0.0.0.0 --port 8080 --database ~/ha-counter-data/counter.db
```

Leave the commands running. Each process creates its own database on first start and increments it approximately every half second, even when nobody has opened the page. From a browser on a machine that can reach the VMs, visit `http://NODE1_IP:8080/` and `http://NODE2_IP:8080/`, replacing the placeholders with the recorded LAN addresses. Each page shows its VM's hostname and its independently increasing counter. You can also check each locally with `curl http://127.0.0.1:8080/state` in another VM terminal.

Press **Ctrl+C** in each running session to stop that instance. Restarting the same command on that VM resumes its own stored counter. The process runs in the foreground and stops when its terminal session ends; Pacemaker will manage the service later.

When moving to DRBD, stop both standalone applications first. Their two local databases are separate from the new DRBD filesystem and are **not merged or migrated automatically**; the cluster starts with a new counter unless you deliberately choose and migrate one database while the application is stopped. Keep the original files as backups until you decide what to do with them.

## VirtualBox preparation

Create two Ubuntu Server VMs, preferably the same supported release (for example 24.04 LTS), each with a unique hostname, static LAN address, and a **separate empty virtual disk** of the same size for DRBD. The disk must not contain a filesystem or data to keep. Give each VM a bridged adapter on the same LAN as the other node and client. Bridging over Wi-Fi may have adapter limitations; verify the floating address can move and be reached from a third machine. Reserve a third unused LAN address outside DHCP allocation for the floating IP.

You can host the VMs on separate computers or on one VirtualBox host. The latter cannot survive failure of that host. Each guest needs network access to both VirtualBox hosts' SSH endpoints, independently of the other guest. A host that powers off cannot execute its own fence agent; plan an independent power/fencing path or accept that failure to contact the host may prevent automatic recovery.

Record the guest hostnames, IPs, DRBD data disks, VIP/prefix, host SSH addresses, VirtualBox VM UUIDs (`VBoxManage list vms` on each host), and host usernames. The fencing user must have permission to control the particular VMs and access the same VirtualBox VM registry as their owner. Configure public-key SSH, pin the host keys, and use a dedicated restricted account where possible. On each VM, verify it can SSH to both host control endpoints as the user Pacemaker will use. A VirtualBox host reachable only through the guest being fenced is not an independent fencing path.

## Install on both VMs

Install `python3`, `sqlite3`, `pcs`, `pacemaker`, `corosync`, `drbd-utils`, `resource-agents`, `fence-agents`, and a DRBD 9 kernel module matching the running kernel. Ubuntu package and DRBD driver availability depend on the release; use the [LINBIT installation guidance](https://linbit.com/drbd-user-guide/drbd-guide-9_0-en/) and verify `modinfo drbd`, `sudo modprobe drbd`, and `drbdadm --version` on each VM. Install the `ocf:linbit:drbd` agent and `fence_vbox` on both VMs; verify `pcs resource describe ocf:linbit:drbd` and `pcs stonith describe fence_vbox`. Locate the DRBD Pacemaker fencing scripts listed in `deploy/counter.res.example` and adjust their paths if necessary.

Copy this repository to each VM (the Python application requires no compilation), then on **each** node:

```sh
sudo install -d /opt/ha-counter /srv/ha-counter
sudo install -m 0644 counter.py /opt/ha-counter/counter.py
sudo install -m 0644 deploy/ha-counter.service /etc/systemd/system/ha-counter.service
sudo systemctl daemon-reload
```

Do not enable or manually start the service. Pacemaker will own it. The service refuses to start without a mount at `/srv/ha-counter`.

## Prepare DRBD

Copy `deploy/counter.res.example` to `/etc/drbd.d/counter.res` on both nodes. Replace the node names, IPs, and disk paths with the real values; both files must contain the same complete configuration. Use `hostname` to confirm that each `on` name matches its node. Confirm the kernel module, backing devices, handler paths, and `sudo drbdadm dump counter` before initialization. Disable independent automatic DRBD startup if enabled, so Pacemaker owns its lifecycle.

**The next command destroys existing data on each selected backing disk.** Verify the devices carefully, then run on **each** VM:

```sh
sudo drbdadm create-md counter
sudo drbdadm up counter
```

For an entirely new empty pair only, initialize the source on **node1**:

```sh
sudo drbdadm primary --force counter
sudo mkfs.ext4 /dev/drbd0
```

Wait for `sudo drbdadm status` to show both replicas `UpToDate`. Then demote and disconnect on both nodes before handing control to Pacemaker:

```sh
# node1 only
sudo drbdadm secondary counter
# both nodes
sudo drbdadm down counter
```

Never use `primary --force` or recreate metadata as a routine recovery step; it can discard data. Investigate a split brain before choosing an authoritative replica.

## Cluster and VirtualBox fencing

Configure name resolution between the VMs and firewall access for SSH, pcsd, Corosync, DRBD and TCP 8080. On each node start `pcsd`, set a strong `hacluster` password, and authenticate the nodes. From one node, substitute the real names:

```sh
sudo systemctl enable --now pcsd
sudo pcs host auth node1 node2
sudo pcs cluster setup ha-counter node1 node2
sudo pcs cluster start --all
sudo pcs cluster enable --all
```

Install and configure two `stonith:fence_vbox` devices, one for each VM, using the relevant VirtualBox host address, SSH login, VM UUID (`plug`), and SSH identity file. Restrict each device to its target with `pcmk_host_list`, and add location constraints preventing a VM from fencing itself. Confirm the installed agent's exact options with `pcs stonith describe fence_vbox`; see [LINBIT's VirtualBox fencing walkthrough](https://linbit.com/blog/using-fencing-in-pacemaker-clusters-on-virtualbox-hypervisors/). Keep `stonith-enabled=true` and configure suitable fencing delays to avoid simultaneous fence races. Verify each agent's status and **actually fence each VM** from its peer, confirming the host reports it powered off; restore it before testing the other. Ensure DRBD's `resource-and-stonith` handler integration is present and working. Do not continue to an automatic failover test if either fencing path fails.

## Pacemaker resources

After fencing has been configured and verified, the following commands, run on one VM, create the storage and service resources. Replace the VIP and prefix. They use modern `pcs` syntax; inspect `pcs --version` and agent metadata if your distribution differs. The group enforces filesystem → application → IP startup, and the constraints ensure it runs only on the promoted DRBD node.

```sh
sudo pcs resource create counter-drbd ocf:linbit:drbd drbd_resource=counter \
  op monitor interval=31s role=Unpromoted op monitor interval=29s role=Promoted
sudo pcs resource promotable counter-drbd \
  promoted-max=1 promoted-node-max=1 clone-max=2 clone-node-max=1 notify=true
sudo pcs resource create counter-fs ocf:heartbeat:Filesystem \
  device=/dev/drbd0 directory=/srv/ha-counter fstype=ext4 --group counter-service
sudo pcs resource create counter-app systemd:ha-counter --group counter-service \
  op monitor interval=10s
sudo pcs resource create counter-ip ocf:heartbeat:IPaddr2 \
  ip=192.0.2.100 cidr_netmask=24 --group counter-service \
  op monitor interval=10s
sudo pcs constraint order promote counter-drbd-clone then start counter-service
sudo pcs constraint colocation add counter-service with counter-drbd-clone \
  score=INFINITY with-rsc-role=Promoted
sudo pcs status --full
sudo drbdadm status
```

## Exercise

1. Wait for both DRBD disks to report `UpToDate`, one node promoted, and all group resources running on that node. Open `http://VIP:8080/` from a third machine and watch the counter increase. Note the value and active node.
2. Abruptly power off the active VM using VirtualBox. Observe `pcs status --full` on the survivor and the fencing result. Once recovered, reload the same URL; the counter must resume from the last committed value on the survivor and continue increasing. It pauses while no node is serving; it does not count missed ticks.
3. Restart the stopped VM and wait for DRBD to resynchronize. Perform a controlled failover, e.g. put the active node in standby with `pcs node standby NODE`, and verify the latest count. Undo with `pcs node unstandby NODE`.
4. Test a cluster-network partition while both VMs remain running and management/fencing access remains available. Confirm successful fencing and at most one writable primary and VIP owner. Separately make fencing unavailable and verify the cluster refuses unsafe takeover. Do not force promotion to make the test pass.

Use `sudo pcs status --full`, `sudo drbdadm status`, `ip address`, and `journalctl` to inspect failures. Changes while one replica is offline cannot be present on that replica until resync. The exercise is not complete until abrupt failure, resync, partition, and fencing failure are tested on your actual VM/network setup.

## Local tests

```sh
python3 -m unittest discover -s tests
```

These check automatic ticking, database persistence and concurrent increments; they do not replace the two-VM integration exercise.
