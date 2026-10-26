# nextNetwork

A Bash toolkit for relay and egress network tuning on **Debian 13 (trixie), amd64**. It installs XanMod and provides two existing profiles: BBR + fq (`main.sh`, recommended) and BBR + cake (`testing.sh`, experimental).

XanMod supplies BBRv3; the sysctl name is still `bbr`. A stock kernel exposing `bbr` does not by itself prove BBRv3 is available. See the [XanMod installation and package reference](https://xanmod.org/).

## Usage

Run as root. Review the scripts before execution.

```bash
git clone https://github.com/Lemonawa/nextNetwork.git
cd nextNetwork
bash main.sh
# Or use the existing experimental profile:
# bash testing.sh
```

On minimal installations, install `git` and `ca-certificates` first. Alternatively, download the standalone script with `wget` or `curl`, inspect it, and run it with Bash.

- Option `1` installs prerequisites and the appropriate XanMod kernel, then writes `/etc/sysctl.d/99-nextnetwork.conf`. It defers live application until reboot into the new kernel.
- Option `2` checks BBR, the Cloudflare collapse patch and the selected qdisc, writes the same file, and applies **only that file** immediately. It does not reapply unrelated sysctl files.
- Both paths ask `Reboot now? [y/N]`; only `y` or `yes` triggers reboot. EOF leaves the system running.
- An existing project sysctl file is copied to `99-nextnetwork.conf.bak` before replacement. This is a single previous version, not a full system backup.

For trixie, x86-64-v1 uses `linux-xanmod-lts-x64v1`; v2 uses `linux-xanmod-x64v2`; v3/v4 use `linux-xanmod-x64v3`. Bookworm compatibility selects LTS packages at every CPU level because XanMod only publishes LTS for that release. The official CPU probe's nonzero success statuses are validated. Unsupported operating systems and non-amd64 kernel installations are rejected before package changes.

## Tuning rationale and limits

The shipped sysctl key/value mappings are identical to the original project profile. Performance changes without isolated benefit evidence were withdrawn; installer reliability fixes remain. The [Linux IP sysctl reference](https://docs.kernel.org/networking/ip-sysctl.html) describes their semantics.

| Setting | Rationale |
| --- | --- |
| `tcp_rmem = 8192 262144 536870912`, `tcp_wmem = 4096 16384 536870912` | Preserve the original 512 MiB autotuning ceilings for high-BDP paths. A tested 32 MiB alternative constrained single-flow throughput at 1 Gbit/s and 300 ms RTT. These ceilings are not preallocated memory or aggregate memory caps. |
| `tcp_window_scaling = 1` | Preserve scaled windows for high-BDP paths. Receive autotuning keeps its kernel/operator setting, as in the original profile. |
| `tcp_collapse_max_bytes = 6291456` | Preserve XanMod's Cloudflare patch policy: skip expensive collapse on large, full receive queues while keeping it for small queues. Option 2 checks that the patch exists before writing the profile. |
| `tcp_notsent_lowat = 131072` | Retain a 128 KiB threshold for unsent application data. This is separate from bytes already in flight; it can increase application wakeups, so check CPU use for bulk relays. |
| `somaxconn = 4096`, `tcp_max_syn_backlog = 8192` | Permit connection bursts. Application listen backlog and accept throughput still matter. |
| `ip_local_port_range = 10240 65535` | Retain the expanded outgoing ephemeral range. Reserve service ports in this range with `ip_local_reserved_ports` if needed; this project does not overwrite your reservations. |
| `tcp_mtu_probing = 1` | Enable TCP MTU probing when an ICMP black hole is detected. |
| `tcp_syncookies = 1`, `tcp_ecn = 2` | Retain SYN flood fallback and accept classic ECN on incoming connections without requesting it on outbound SYNs. |
| `ip_forward = 1` | Preserve the project's IPv4 routing behavior. Written first because changing it resets IPv4 settings. Check host-specific routing sysctls when enabling forwarding for the first time. |

The original `netdev_max_backlog=16384`, Fast Open, idle slow-start, FIN timeout and keepalive settings are retained. The previous draft removed these together without isolating their benefits, so those edits were withdrawn. Fast Open server use still requires application support; keepalive timers affect sockets enabling SO_KEEPALIVE; `tcp_fin_timeout=15` affects orphaned FIN_WAIT_2 sockets and does not shorten TIME_WAIT. These settings are workload policy, not universal speed improvements.

The legacy `tcp_adv_win_scale=-2` is also retained for exact baseline identity. Linux documents it as obsolete since 6.6; no performance benefit is attributed to it on modern kernels. TCP's RAM-dependent aggregate memory thresholds and explicit socket buffer limits (`net.core.rmem_max`/`wmem_max`) remain kernel/operator managed.

Size buffers from measured bandwidth × RTT, with room for socket accounting and concurrency. For example, 1 Gbit/s × 300 ms is approximately 37.5 MB of payload in flight, before socket metadata. Limits of 32 MiB can already constrain that path. Large ceilings also allow substantial actual allocation when applications pause reading; use the recorded socket memory measurements when assessing host capacity. Low-memory hosts also need concurrent-connection memory checks. This profile does not change UDP/QUIC socket buffer limits.

[fq](https://man7.org/linux/man-pages/man8/tc-fq.8.html) provides per-flow scheduling and respects locally generated TCP pacing. [CAKE](https://man7.org/linux/man-pages/man8/tc-cake.8.html) adds queue management and isolation, with more processing work; **CAKE's default bandwidth is unlimited**. Selecting `default_qdisc=cake` alone does not shape to an ISP bottleneck. The script deliberately does not guess a bandwidth or rewrite NIC qdisc trees.

Changing `net.core.default_qdisc` does not replace qdiscs already attached to live interfaces. Reboot and inspect `tc -s qdisc show`; multiqueue NICs commonly retain `mq` at the root with the selected scheduler on their leaf queues. BBR changes affect new TCP connections. Pure packet forwarding does not use the relay's TCP congestion control; TCP tuning primarily affects connections terminated on the host.

## Validation

```bash
bash -n main.sh testing.sh tests/*.sh
bash tests/xanmod_package_selection_test.sh
bash tests/runtime_test.sh
bash tests/install_test.sh
bash tests/installer_idempotency_test.sh
python3 tests/network_metrics_test.py
python3 tests/confirmation_analysis_test.py
# If installed:
shellcheck main.sh testing.sh tests/*.sh
```

The installer idempotency regression uses real GnuPG with local Debian public keys, temporary keyrings and mocked package/download commands. It reproduces the original unattended second-install failure and checks that both corrected scripts preserve valid keyrings with mode `0644` on repeated installs; it does not install a kernel or modify APT.

An isolated real TCP simulation compares the committed baseline (`HEAD`) with the working scripts on this machine's running kernel:

```bash
unshare -Urn python3 tests/network_simulation.py --repeats 3 --duration 10
```

Requires Python 3, `ip`, `tc`, `ss`, `iperf3`, `ping`, `nsenter`, `ethtool`, and user/network namespace support. No installer is executed. Each run uses fresh endpoint/router namespaces, with netem on the router's two egress interfaces, leaving fq/cake on the endpoints. TSO/GSO/GRO are disabled on all virtual interfaces so loss is applied to individual packets. It tests one and eight TCP connections, both qdiscs, and both profiles:

- Good: 1 Gbit/s, 1 ± 0.1 ms delay per direction, no injected loss.
- Evening peak: 100 Mbit/s, 75 ± 20 ms delay and independent 1% random loss per direction (about 150 ms base RTT and 1.99% round-trip loss).

For a longer check of evening-peak single-connection throughput with the default profile:

```bash
unshare -Urn python3 tests/network_simulation.py --repeats 3 --duration 30 \
    --scenario peak --qdisc fq --streams 1 --output tests/results/peak-long.json
```

The test writes throughput, retransmit counts, concurrent ping results and configuration snapshots to `tests/results/network-simulation.json`. Seeds are paired between baseline and candidate; repeated measurements and alternating profile order reduce noise. Host-global `default_qdisc` and `netdev_max_backlog` are excluded from sysctl writes; fq/cake are attached explicitly. Missing kernel keys are recorded. These virtual-link measurements do not establish physical NIC, production load, burst-loss or real ISP performance. The [first test report](tests/results/README.md) records the earlier 32 MiB draft, which has been superseded. See the [extended test report](tests/results/extended-report.md) for the buffer/collapse factorial tests and subsequent candidate validation.

### Extended validation

The extended harness uses Python TCP senders/readers to exercise receive-queue pressure, rather than relying only on iperf3. The four factorial profiles preserve all original settings except the two buffer maxima and the Cloudflare collapse threshold.

```bash
# Continuous reading: three repeats, 1 Gbit/s and 300 ms RTT.
unshare -Urn python3 tests/extended_network_simulation.py --repeats 3 --duration 20 \
    --scenario high_bdp --mode bulk --output tests/results/high-bdp-factorial.json
# Fast reading for 5 s, then reading at 5% of the high-water rate for 15 s;
# three cycles per run, two independent repeats.
unshare -Urn python3 tests/extended_network_simulation.py --repeats 2 --duration 60 \
    --scenario high_bdp --mode oscillating --output tests/results/collapse-factorial.json
```

Results include actual socket memory, configured limits, TCP collapse/drop counters, local and remote echo latency samples, process CPU time and qdisc statistics. Echo latency does not measure kernel function execution time. Raw test sources are saved alongside the results for reproducibility. The earlier 32 MiB draft is preserved in the historical report; it is not the current default. An additional known-bottleneck experiment found that explicit CAKE shaping traded throughput for substantially lower loaded latency. This is an experimental control, not a bandwidth inferred or configured by the installer.

### Fixed-protocol confirmation

The final phase fixes eight paired blocks, independent randomized A/B order, 80 total runs and eight practical performance gates before collecting data. Bulk goodput excludes the first 10 seconds and final partial bin; latency samples use aligned monotonic timestamps. Exact one-sided sign tests use Bonferroni correction. Failed gates revoke the corresponding gain claim; the experiment does not add samples until it passes.

```bash
# Use a NEW output directory for a new preregistration.
python3 tests/confirmatory_simulation.py prepare tests/results/new-confirmation
unshare -Urn python3 tests/confirmatory_simulation.py run tests/results/new-confirmation
python3 tests/confirmatory_simulation.py analyze tests/results/new-confirmation
```

The protocol pins the original commit and hashes every measured source. The run command refuses modified sources, an invalidated directory or a completed experiment; after interruption it resumes only missing runs. The original baseline commit must be available locally. The [first confirmation attempt](tests/results/confirmation-20261026/INVALIDATED.md) was discarded at the operator’s request after a host power-plan change; none of its measurements are retained or used. A fresh experiment after the operator restored the environment completed all 80 runs under [a separate frozen protocol](tests/results/confirmation-20261026-restored/protocol.json). All eight predefined gates passed (Bonferroni-adjusted p = 0.03125 each); the [confirmation report](tests/results/confirmation-20261026-restored/report.md) includes absolute values, latency/memory tradeoffs and scope. These comparisons support preserving the original network configuration, while the installation fixes address independently reproduced failures.

## License

[MIT](LICENSE)

## Credits

[XanMod Kernel](https://xanmod.org/), [nexstorm/magicTCP](https://github.com/nexstorm/magicTCP), [Cloudflare's TCP tuning discussion](https://blog.cloudflare.com/optimizing-tcp-for-high-throughput-and-low-latency).

[Linux network tuning discussion by Is Yang](https://www.isisy.com/1159.html).
