#!/usr/bin/env python3
"""Compare committed and working profiles inside disposable Linux namespaces.

Run: unshare -Urn python3 tests/network_simulation.py --repeats 3 --duration 12
Requires iproute2, iperf3, ping, util-linux and unprivileged user namespaces.
No installer, package installation, host sysctl writes or host qdisc changes.
"""
import argparse
from contextlib import contextmanager
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def run(args, pid=None, check=True):
    prefix = ["nsenter", "-t", str(pid), "-n"] if pid else []
    return subprocess.run(prefix + args, text=True, capture_output=True, check=check)


def node():
    proc = subprocess.Popen(["unshare", "-n", "sleep", "infinity"])
    for _ in range(100):
        if proc.poll() is not None:
            raise RuntimeError("Cannot create network namespace")
        if os.readlink(f"/proc/{proc.pid}/ns/net") != os.readlink("/proc/self/ns/net"):
            return proc
        time.sleep(0.01)
    proc.terminate()
    raise RuntimeError("Network namespace creation timed out")


def render(script):
    return run(["bash", "-c", 'source "$1"; render_sysctl_config', "bash", str(script)]).stdout


def settings(text):
    return dict(line.split("=", 1) for line in
                (line.strip() for line in text.splitlines())
                if line and not line.startswith("#") and "=" in line)


def apply_profile(text, pid, skipped):
    for key, value in settings(text).items():
        key, value = key.strip(), value.strip()
        # default_qdisc and netdev_max_backlog are host-global on this kernel.
        # Attach fq/cake explicitly below instead of modifying host settings.
        if key in {"net.core.default_qdisc", "net.core.netdev_max_backlog"}:
            skipped.add(key)
            continue
        if run(["sysctl", "-n", key], pid, check=False).returncode:
            skipped.add(key)
            continue
        run(["sysctl", "-w", f"{key}={value}"], pid)


@contextmanager
def isolated_link(profile, qdisc, scenario, index):
    router = receiver = None
    try:
        router = node()
        receiver = node()
        # Sender stays in the enclosing disposable namespace. A dedicated router
        # applies netem on egress towards each endpoint, approximating receiver
        # ingress impairment without replacing the sender's fq/cake scheduler.
        for local, peer, target in [("nn-s", "nn-rs", router.pid),
                                    ("nn-t", "nn-rt", router.pid)]:
            run(["ip", "link", "add", local, "type", "veth", "peer", "name", peer])
            run(["ip", "link", "set", peer, "netns", str(target)])
        run(["ip", "link", "set", "nn-t", "netns", str(receiver.pid)])
        for dev, addr, pid in [("nn-s", "10.200.1.1/24", None),
                               ("nn-rs", "10.200.1.254/24", router.pid),
                               ("nn-rt", "10.200.2.254/24", router.pid),
                               ("nn-t", "10.200.2.1/24", receiver.pid)]:
            run(["ip", "addr", "add", addr, "dev", dev], pid)
            # Make netem random loss operate on wire-sized packets rather than
            # GSO super-packets. Do this on all veth ends, only in this namespace.
            run(["ethtool", "-K", dev, "tso", "off", "gso", "off", "gro", "off"], pid)
            features = run(["ethtool", "-k", dev], pid).stdout
            for feature in ["tcp-segmentation-offload", "generic-segmentation-offload", "generic-receive-offload"]:
                if f"{feature}: off" not in features:
                    raise RuntimeError(f"{dev}: failed to disable {feature}")
            run(["ip", "link", "set", dev, "up"], pid)
            run(["ip", "link", "set", "lo", "up"], pid)
        run(["ip", "route", "add", "10.200.2.0/24", "via", "10.200.1.254"])
        run(["ip", "route", "add", "default", "via", "10.200.2.254"], receiver.pid)
        run(["sysctl", "-w", "net.ipv4.ip_forward=1"], router.pid)
        skipped = set()
        apply_profile(profile, None, skipped)
        apply_profile(profile, receiver.pid, skipped)
        for dev, pid in [("nn-s", None), ("nn-t", receiver.pid)]:
            run(["tc", "qdisc", "replace", "dev", dev, "root", "cake" if qdisc == "cake-shaped" else qdisc], pid)
        if qdisc == "cake-shaped":
            for dev, pid in [("nn-s", None), ("nn-t", receiver.pid)]:
                run(["tc", "qdisc", "replace", "dev", dev, "root", "cake", "bandwidth", scenario["shaper_rate"]], pid)
        for offset, dev in enumerate(["nn-rs", "nn-rt"]):
            args = ["tc", "qdisc", "replace", "dev", dev, "root", "netem",
                    "limit", str(scenario.get("limit", 65536)), "delay", scenario["delay"], scenario["jitter"],
                    "distribution", "normal", "loss", "random", scenario["loss"],
                    "rate", scenario["rate"], "seed", str(1000 + index * 2 + offset)]
            if scenario["jitter"] == "0ms":
                at = args.index("distribution")
                del args[at:at+2]
            if scenario.get("burst_loss"):
                at = args.index("loss")
                end = args.index("rate")
                args[at:end] = ["loss", "gemodel", "0.2%", "10%", "90%", "0.01%"]
            run(args, router.pid)
        yield router, receiver, skipped
    finally:
        for proc in [router, receiver]:
            if proc and proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)
        run(["ip", "link", "del", "nn-s"], check=False)
        run(["ip", "route", "del", "10.200.2.0/24"], check=False)


def measure(profile, qdisc, scenario, duration, streams, index):
    with isolated_link(profile, qdisc, scenario, index) as (_, receiver, skipped):
        server = ping = None
        try:
            server = subprocess.Popen(["nsenter", "-t", str(receiver.pid), "-n",
                                       "iperf3", "-s", "-1"], stdout=subprocess.DEVNULL,
                                      stderr=subprocess.PIPE)
            for _ in range(100):
                if ":5201" in run(["ss", "-ltn"], receiver.pid).stdout:
                    break
                time.sleep(0.02)
            with tempfile.TemporaryFile(mode="w+") as ping_output:
                ping = subprocess.Popen(["ping", "-n", "-i", "0.1", "-c",
                                         str((duration + 2) * 10), "-W", "2", "10.200.2.1"],
                                        stdout=ping_output, stderr=subprocess.DEVNULL)
                data = json.loads(run(["iperf3", "-c", "10.200.2.1", "-P", str(streams),
                                       "-t", str(duration), "-O", "2", "-J"]).stdout)
                ping.wait(timeout=10)
                ping_output.seek(0)
                ping_text = ping_output.read()
            if "error" in data:
                raise RuntimeError(data["error"])
            rtt = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms", ping_text)
            loss = re.search(r"([\d.]+)% packet loss", ping_text)
            return {"mbps": data["end"]["sum_received"]["bits_per_second"] / 1e6,
                    "retransmits": data["end"]["sum_sent"].get("retransmits"),
                    "ping_rtt_min_avg_max_mdev_ms": list(map(float, rtt.groups())) if rtt else None,
                    "ping_loss_percent": float(loss.group(1)) if loss else None,
                    "skipped_sysctls": sorted(skipped)}
        finally:
            for proc in [ping, server]:
                if proc and proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--duration", type=int, default=12)
    parser.add_argument("--scenario", choices=["good", "peak"])
    parser.add_argument("--qdisc", choices=["fq", "cake"])
    parser.add_argument("--streams", type=int)
    parser.add_argument("--output", type=Path, default=ROOT / "tests/results/network-simulation.json")
    args = parser.parse_args()
    if os.geteuid() != 0 or Path("/proc/self/uid_map").read_text().split()[-1] != "1":
        parser.error("Run inside a disposable user/network namespace: unshare -Urn python3 ...")
    for command in ["ip", "tc", "ss", "iperf3", "ping", "nsenter", "unshare", "ethtool"]:
        if not shutil.which(command):
            parser.error(f"Missing test dependency: {command}")
    if args.repeats < 1 or args.duration < 2 or (args.streams is not None and args.streams < 1):
        parser.error("Use at least one repeat and a duration of two seconds")
    scenarios = {
        "good": {"delay": "1ms", "jitter": "0.1ms", "loss": "0%", "rate": "1gbit"},
        "peak": {"delay": "75ms", "jitter": "20ms", "loss": "1%", "rate": "100mbit"},
    }
    # Each benchmark runs in a fresh child network namespace so deleted profile
    # keys cannot leak from the baseline into the candidate.
    results = {"kernel": os.uname().release, "os_release": Path("/etc/os-release").read_text(),
               "baseline_commit": run(["git", "rev-parse", "HEAD"]).stdout.strip(),
               "started_at_utc": datetime.now(timezone.utc).isoformat(),
               "duration_seconds": args.duration, "omit_seconds": 2,
               "endpoint_offloads": "TSO/GSO/GRO disabled on all veth interfaces",
               "scenarios_per_direction": scenarios, "filters": {"scenario": args.scenario, "qdisc": args.qdisc, "streams": args.streams}, "runs": []}
    with tempfile.TemporaryDirectory() as directory:
        for repeat in range(args.repeats):
            # Alternate order to reduce systematic warmup/load bias.
            variants = [(version, qdisc) for version in ["baseline", "candidate"] for qdisc in ["fq", "cake"]]
            if args.qdisc:
                variants = [v for v in variants if v[1] == args.qdisc]
            if repeat % 2:
                variants.reverse()
            for name, scenario in scenarios.items():
                if args.scenario and name != args.scenario:
                    continue
                for version, qdisc in variants:
                    script = "main.sh" if qdisc == "fq" else "testing.sh"
                    if version == "baseline":
                        path = Path(directory) / script
                        path.write_text(run(["git", "show", f"HEAD:{script}"]).stdout)
                    else:
                        path = ROOT / script
                    profile = render(path)
                    results.setdefault("profile_snapshots", {})[f"{version}/{script}"] = {
                        "script_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "sysctl_profile": profile,
                    }
                    for streams in ([args.streams] if args.streams else [1, 8]):
                        # Forking via unshare ensures fresh kernel defaults on every run.
                        payload = Path(directory) / "payload.json"
                        payload.write_text(json.dumps([profile, qdisc, scenario, args.duration, streams, repeat]))
                        result = json.loads(run(["unshare", "-n", "python3", str(Path(__file__).resolve()),
                                                 "--worker", str(payload)]).stdout)
                        row = dict(scenario=name, version=version, qdisc=qdisc, streams=streams,
                                   repeat=repeat + 1, **result)
                        results["runs"].append(row)
                        args.output.parent.mkdir(parents=True, exist_ok=True)
                        args.output.write_text(json.dumps(results, indent=2) + "\n")
                        print(json.dumps(row), flush=True)


if __name__ == "__main__":
    import sys
    # Guard workers too: a payload must never be usable on the host network.
    if os.geteuid() != 0 or Path("/proc/self/uid_map").read_text().split()[-1] != "1":
        sys.exit("Run in a disposable user/network namespace: unshare -Urn python3 ...")
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        print(json.dumps(measure(*json.loads(Path(sys.argv[2]).read_text()))))
    else:
        main()
