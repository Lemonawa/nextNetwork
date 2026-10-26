#!/usr/bin/env python3
"""Frozen-protocol, adjacent randomized pairs for network confirmation.

Prepare protocol before running; no optional stopping or adding samples is used.
All mutations occur in disposable user/network namespaces via the existing lab.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys
import tempfile

from extended_network_simulation import ROOT, SCENARIOS, replace_setting
from network_simulation import render, run

REFERENCE = '5dfb9ede9ec0727984f97076a9685cb293f5097a'
HARNESS = ROOT / 'tests/extended_network_simulation.py'
MEASURED_SOURCES = ['tests/confirmatory_simulation.py', 'tests/extended_network_simulation.py',
                    'tests/network_simulation.py', 'tests/tcp_workload.py', 'main.sh', 'testing.sh']


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def assignments(text):
    return {key.strip(): value.split() for key, value in
            (line.split('=', 1) for line in text.splitlines()
             if line.strip() and not line.lstrip().startswith('#') and '=' in line)}


def baseline_profile(filename):
    source = run(['git', 'show', f'{REFERENCE}:{filename}']).stdout
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / filename
        path.write_text(source)
        return render(path)


def reject_invalidated(directory):
    if (directory / 'INVALIDATED.md').exists():
        raise ValueError('Experiment invalidated; use a new directory and collect fresh data')


def prepare(directory):
    reject_invalidated(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if (directory / 'protocol.json').exists():
        raise ValueError('Protocol already exists; refusing to replace preregistration')
    original = baseline_profile('main.sh')
    for filename in ['main.sh', 'testing.sh']:
        if assignments(render(ROOT / filename)) != assignments(baseline_profile(filename)):
            raise ValueError(f'{filename}: network configuration differs from original')
    profiles = {}
    for size, enabled in [(32, True), (512, True), (512, False)]:
        text = replace_setting(original, 'net.ipv4.tcp_rmem', f'8192 262144 {size*1048576}')
        text = replace_setting(text, 'net.ipv4.tcp_wmem', f'4096 16384 {size*1048576}')
        profiles[f'{size}-{"on" if enabled else "off"}'] = replace_setting(
            text, 'net.ipv4.tcp_collapse_max_bytes', 6291456 if enabled else 0)
    groups = [
        dict(name=f'buffer-{q}', mode='bulk', duration=30, a='32-on', b='512-on', qa=q, qb=q)
        for q in ['fq', 'cake']
    ] + [
        dict(name=f'collapse-{q}', mode='oscillating', duration=40,
             a='512-off', b='512-on', qa=q, qb=q) for q in ['fq', 'cake']
    ] + [dict(name='shaping-cake', mode='bulk', duration=30,
              a='512-on', b='512-on', qa='cake', qb='cake-shaped')]
    randomizer = random.Random(202610261923)
    schedule = []
    for block in range(1, 9):
        order = groups.copy()
        randomizer.shuffle(order)
        for group in order:
            arms = ['a', 'b']
            if randomizer.getrandbits(1):
                arms.reverse()
            schedule.append(dict(block=block, group=group, order=arms,
                                 network_seed_index=10000 + block * 101 + groups.index(group)))
    sources = {name: (ROOT / name).read_text() for name in MEASURED_SOURCES}
    protocol = {
        'schema': 1, 'prepared_at_utc': datetime.now(timezone.utc).isoformat(),
        'baseline_commit': REFERENCE, 'kernel': os.uname().release,
        'os_release': Path('/etc/os-release').read_text(),
        'source_sha256': {name: digest(text.encode()) for name, text in sources.items()},
        'profiles': profiles, 'scenario': dict(SCENARIOS['high_bdp']), 'streams': 1,
        'repeats': 8, 'schedule': schedule,
        'primary_claims': [
            {'name': f'buffer-{q}-throughput', 'comparison': f'buffer-{q}',
             'metric': 'steady_mbps', 'direction': 'greater', 'threshold': 1.30}
            for q in ['fq', 'cake']
        ] + [
            {'name': f'collapse-{q}-segments', 'comparison': f'collapse-{q}',
             'metric': 'collapsed_plus_one', 'direction': 'less', 'threshold': .05}
            for q in ['fq', 'cake']
        ] + [
            {'name': f'collapse-{q}-throughput', 'comparison': f'collapse-{q}',
             'metric': 'wall_mbps', 'direction': 'greater', 'threshold': .95}
            for q in ['fq', 'cake']
        ] + [
            {'name': 'shaping-cake-latency', 'comparison': 'shaping-cake',
             'metric': 'remote_p99_ms', 'direction': 'less', 'threshold': .60},
            {'name': 'shaping-cake-throughput', 'comparison': 'shaping-cake',
             'metric': 'steady_mbps', 'direction': 'greater', 'threshold': .85},
        ],
        'analysis': {
            'family_alpha': .05, 'multiple_comparisons': 'Bonferroni, 8 primary claims',
            'test': 'Exact one-sided paired sign test against the practical ratio threshold',
            'confidence_bound': 'Minimum ratio for greater claims; maximum ratio for less claims',
            'bound_confidence': 1 - 2**-8,
            'simultaneous_coverage_lower_bound': 1 - 8 * 2**-8,
            'bulk_window': 'receiver seconds [10,duration-1); discard first 10 s and final bin',
            'probe_window': 'same receiver-time window; align process monotonic timestamps',
            'collapse_window': 'entire 40 s, two 5 s fast / 15 s slow cycles',
            'collapse_validity': 'A must trigger at least 1000 collapsed segments; otherwise pair fails gate',
            'probe_failure_policy': 'Any failed remote probe inside measurement window fails latency gate',
            'stopping': 'Exactly eight blocks. No replacement of valid unfavorable runs; no post-hoc sample increase.',
            'failure_policy': 'A run failure stops the experiment; resume only missing runs, retain existing results.',
            'claim_scope': 'This frozen synthetic workload and local kernel, not all Internet paths',
        },
    }
    (directory / 'sources.json').write_text(json.dumps(sources, indent=2) + '\n')
    data = canonical(protocol)
    (directory / 'protocol.json').write_bytes(data + b'\n')
    (directory / 'protocol.sha256').write_text(digest(data) + '\n')
    print(f'Frozen protocol {digest(data)}: 80 runs, eight primary claims')


def verify_protocol(directory):
    reject_invalidated(directory)
    protocol = json.loads((directory / 'protocol.json').read_text())
    expected = (directory / 'protocol.sha256').read_text().strip()
    if digest(canonical(protocol)) != expected:
        raise ValueError('Protocol checksum changed')
    for name, expected_source in protocol['source_sha256'].items():
        if digest((ROOT / name).read_bytes()) != expected_source:
            raise ValueError(f'Measured source changed after preregistration: {name}')
    return protocol, expected


def execute(directory):
    if os.geteuid() != 0 or Path('/proc/self/uid_map').read_text().split()[-1] != '1':
        raise ValueError('Run with unshare -Urn')
    protocol, checksum = verify_protocol(directory)
    output = directory / 'runs.json'
    if (directory / 'runs.json.gz').exists():
        raise ValueError('Experiment already complete; refusing to add samples')
    result = json.loads(output.read_text()) if output.exists() else {'protocol_sha256': checksum, 'runs': []}
    if result['protocol_sha256'] != checksum:
        raise ValueError('Results belong to a different protocol')
    completed = {(row['block'], row['comparison'], row['arm']) for row in result['runs']}
    for item in protocol['schedule']:
        group = item['group']
        for arm in item['order']:
            identity = (item['block'], group['name'], arm)
            if identity in completed:
                continue
            verify_protocol(directory)
            scenario = protocol['scenario'].copy()
            qdisc = group['q' + arm]
            if qdisc == 'cake-shaped':
                scenario['shaper_rate'] = '900mbit'
            payload = [protocol['profiles'][group[arm]], qdisc, scenario, group['mode'],
                       group['duration'], protocol['streams'], item['network_seed_index']]
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.json') as temp:
                json.dump(payload, temp)
                temp.flush()
                measured = json.loads(run(['unshare', '-n', sys.executable, str(HARNESS),
                                          '--worker', temp.name]).stdout)
            row = dict(block=item['block'], comparison=group['name'], arm=arm,
                       profile=group[arm], qdisc=qdisc, duration=group['duration'], data=measured)
            result['runs'].append(row)
            temporary = output.with_suffix('.tmp')
            temporary.write_text(json.dumps(result, separators=(',', ':')) + '\n')
            temporary.replace(output)
            print(json.dumps({'completed': len(result['runs']), 'of': 80, 'block': item['block'],
                              'comparison': group['name'], 'arm': arm,
                              'metrics': metrics(row)}), flush=True)


def quantile(values, probability):
    values = sorted(values)
    if not values:
        raise ValueError('Empty measurement window')
    position = (len(values) - 1) * probability
    lo = int(position)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (position - lo)


def metrics(row):
    data = row['data']
    duration = row['duration']
    bins = data['receiver']['bytes_per_second']
    steady = statistics.mean(bins[10:duration-1]) * 8 / 1e6
    receiver_start = data['receiver']['started_monotonic']
    probe = data['remote_probe']
    in_window = [sample for sample in probe['samples']
                 if 10 <= probe['started_monotonic'] + sample['elapsed'] - receiver_start < duration - 1]
    collapsed = data['counter_deltas']['receiver'].get('TcpExt:TCPRcvCollapsed', 0)
    return {'steady_mbps': steady, 'wall_mbps': data['receiver']['wall_mbps'],
            'remote_p99_ms': quantile([sample['ms'] for sample in in_window], .99),
            'remote_failed': sum(bool(sample.get('failed')) for sample in in_window),
            'remote_samples': len(in_window), 'collapsed_plus_one': collapsed + 1,
            'receive_peak_mib': max(sample['receiver']['allocated_receive'] for sample in data['socket_samples']) / 1048576}


def sign_pvalue(successes, count):
    return sum(math.comb(count, k) for k in range(successes, count + 1)) / 2**count


def decide(protocol, rows):
    grouped = {(row['comparison'], row['block'], row['arm']): row for row in rows}
    if len(grouped) != 80 or len(rows) != 80:
        raise ValueError('Decision requires exactly 80 distinct completed runs')
    decisions = []
    family = len(protocol['primary_claims'])
    for claim in protocol['primary_claims']:
        ratios, validity = [], []
        for block in range(1, 9):
            a = metrics(grouped[(claim['comparison'], block, 'a')])
            b = metrics(grouped[(claim['comparison'], block, 'b')])
            ratios.append(b[claim['metric']] / a[claim['metric']])
            valid = True
            if claim['comparison'].startswith('collapse'):
                valid = a['collapsed_plus_one'] > 1000
            if claim['metric'] == 'remote_p99_ms':
                valid = valid and a['remote_failed'] == 0 and b['remote_failed'] == 0
            validity.append(valid)
        successes = sum(valid and (ratio > claim['threshold'] if claim['direction'] == 'greater'
                                  else ratio < claim['threshold']) for ratio, valid in zip(ratios, validity))
        pvalue = sign_pvalue(successes, len(ratios))
        bound = min(ratios) if claim['direction'] == 'greater' else max(ratios)
        decisions.append(dict(**claim, ratios=ratios, median_ratio=statistics.median(ratios),
                              confidence_bound=bound, confidence=protocol['analysis']['bound_confidence'],
                              valid_pairs=sum(validity), successes=successes, pvalue=pvalue,
                              adjusted_pvalue=min(1., pvalue * family),
                              passed=all(validity) and pvalue * family <= protocol['analysis']['family_alpha']))
    return decisions


def analyze(directory):
    reject_invalidated(directory)
    protocol = json.loads((directory / 'protocol.json').read_text())
    checksum = digest(canonical(protocol))
    raw = directory / 'runs.json'
    result = json.loads(raw.read_text()) if raw.exists() else json.loads(gzip.decompress((directory / 'runs.json.gz').read_bytes()))
    if result['protocol_sha256'] != checksum:
        raise ValueError('Result checksum does not match protocol')
    decisions = decide(protocol, result['runs'])
    (directory / 'decision.json').write_text(json.dumps({'protocol_sha256': checksum, 'decisions': decisions}, indent=2) + '\n')
    lines = ['# 预设门槛确认实验', '', f'协议 SHA256：`{checksum}`。固定 8 个独立块、80 次运行、8 项主检验。', '',
             '每项使用配对比值与单侧精确符号检验，按 8 项比较做 Bonferroni 校正。通过要求为校正后 p ≤ 0.05，且所有有效性条件满足。', '',
             '下界/上界为 8 个配对比值的最小/最大值；单项为保守的 99.609375% 单侧总体中位数界。8 项界同时覆盖率的下界为 96.875%。这些概率界依赖独立块假设；适用范围是本协议和本机。', '',
             '| 命题 | B/A 门槛 | 配对比值中位数 | 单侧界 | 有效/通过门槛对数 | 校正 p | 判定 |',
             '| --- | ---: | ---: | ---: | ---: | ---: | --- |']
    for d in decisions:
        operator = '>' if d['direction'] == 'greater' else '<'
        lines.append(f"| {d['name']} | {operator} {d['threshold']:.2f} | {d['median_ratio']:.6f} | {d['confidence_bound']:.6f} | {d['valid_pairs']}/8；{d['successes']}/8 | {d['adjusted_pvalue']:.6f} | {'通过' if d['passed'] else '不通过，撤销该收益声明'} |")
    lines += ['', '## 边界与代码处理', '',
              '已撤回此前没有单项证据的网络参数删改，最终 main.sh/testing.sh 的 sysctl 键值与原提交完全一致。安装、临时文件、密钥重复导入、系统检查和生效流程的修复继续保留；无新增网络功能。', '',
              '大缓冲和 collapse 实验验证的是原项目设计相对缩小缓冲或关闭策略的效果，不能包装为修正版比原版提速。整形实验仅针对已知 1 Gbit/s 瓶颈，900 Mbit/s 限速未加入产品脚本。', '',
              '测试不包含内核安装引导、物理 NIC、低 RAM、所有 ISP 或 UDP/QUIC。collapse 计数不是函数调用数，也没有直接测量内核函数执行时间。', '',
              '完整协议见 [protocol.json](protocol.json)，源代码快照见 [sources.json](sources.json)，原始运行见 [runs.json.gz](runs.json.gz)，逐项判定见 [decision.json](decision.json)。', '']
    (directory / 'report.md').write_text('\n'.join(lines))
    if raw.exists():
        original = raw.read_bytes()
        compressed = gzip.compress(original, compresslevel=9, mtime=0)
        if gzip.decompress(compressed) != original:
            raise ValueError('Compression verification failed')
        (directory / 'runs.json.gz').write_bytes(compressed)
        raw.unlink()
    print(json.dumps({d['name']: d['passed'] for d in decisions}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run', 'analyze'])
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    {'prepare': prepare, 'run': execute, 'analyze': analyze}[args.action](args.directory.resolve())


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        sys.stderr.write(error.stderr or str(error))
        raise SystemExit(error.returncode)
