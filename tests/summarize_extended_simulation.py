#!/usr/bin/env python3
"""Summarize repeated network experiments without treating samples as repeats."""
import argparse
from collections import defaultdict
import json
import gzip
from pathlib import Path
import statistics


def percentile(values, probability):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def probe_tail(row, name, probability=.99):
    return percentile([sample['ms'] for sample in row[name]['samples'] if not sample.get('failed')], probability)


def tails_text(rows, name):
    p95 = [probe_tail(row, name, .95) for row in rows]
    p99 = [probe_tail(row, name, .99) for row in rows]
    p95 = [value for value in p95 if value is not None]
    p99 = [value for value in p99 if value is not None]
    if not p95 or not p99:
        return '无有效样本'
    return f'{statistics.median(p95):.2f} / {statistics.median(p99):.2f} ({min(p99):.2f}–{max(p99):.2f})'


def peak_receive(row):
    return max(sample['receiver']['allocated_receive'] for sample in row['socket_samples']) / 1048576


def median_text(values, digits=2):
    values = [value for value in values if value is not None]
    if not values:
        return '无有效样本'
    return f'{statistics.median(values):.{digits}f} ({min(values):.{digits}f}–{max(values):.{digits}f})'


def findings(datasets):
    lines = ['## 结论与代码处理', '']
    bulk = datasets.get('high-bdp-factorial', {}).get('runs', [])
    if bulk:
        lines += ['32 MiB 不适合作为本项目的通用上限。下表保持 collapse 阈值开启，只改变缓冲上限；单位 Mbit/s，排除起始 2 秒后的应用消费速度中位数。', '',
                  '| 队列 | 32 MiB | 512 MiB |', '| --- | ---: | ---: |']
        for qdisc in ['fq', 'cake']:
            values = [statistics.median(r['receiver']['steady_fast_mbps'] for r in bulk
                                       if r['qdisc'] == qdisc and r['profile'] == profile)
                      for profile in ['32-on', '512-on']]
            lines.append(f'| {qdisc} | {values[0]:.2f} | {values[1]:.2f} |')
        lines += ['', '因此已恢复原项目的 512 MiB 上限。它不是预分配内存；连续快速读取时，实测接收内存分配很小。它也不是所有部署的最佳上限，本测试没有覆盖更高速链路或低 RAM 主机。', '']
    oscillating = datasets.get('collapse-factorial', {}).get('runs', [])
    if oscillating:
        off = [r['counter_deltas']['receiver'].get('TcpExt:TCPRcvCollapsed', 0)
               for r in oscillating if r['profile'] == '512-off']
        on = [r['counter_deltas']['receiver'].get('TcpExt:TCPRcvCollapsed', 0)
              for r in oscillating if r['profile'] == '512-on']
        if off and on:
            lines += [f'512 MiB 间歇读取时，关闭自定义阈值策略的单次运行出现 {min(off):,}–{max(off):,} 个被 collapse 的 TCP 段；开启策略的计数为 {on}。已保留原项目的 6 MiB 阈值，配置前会检查补丁是否存在。', '',
                      '大缓冲在慢读取下确实会消耗大量内存。请查看采样峰值；不能把“上限未预分配”解释为“不会占用内存”。本机探测没有稳定复现原文量级的请求延迟尖峰，也没有直接跟踪 collapse 函数耗时，不能宣称复制了原文的毫秒收益或证明 6 MiB 为本机最佳阈值。', '']
    control = datasets.get('cake-repeatability-control', {})
    if control.get('runs'):
        identical = control['profiles']['original'] == control['profiles']['512-on']
        tails = [probe_tail(r, 'remote_probe') for r in control['runs']]
        tails = [value for value in tails if value is not None]
        lines += [f'重复性控制中，两份配置内容完全相同：{identical}。远端 P99 仍分布在 {min(tails):.2f}–{max(tails):.2f} ms。随机丢包、发包时序及调度带来的差异足以影响尾部指标，不能将小样本差异全部归因于参数。', '']
    if datasets.get('cake-peak-long', {}).get('runs'):
        lines += ['cake 的完整三轮晚高峰结果和额外整形对照均列在下文。默认 cake 未证明普遍优于 fq；仍保留 fq 默认、cake 实验。实验中的 90 Mbit/s 整形没有加入产品脚本，且不能修复外部随机或突发丢包。', '']
    shaped = datasets.get('high-bdp-shaping-control', {}).get('runs', [])
    if shaped:
        lines += ['已知 1 Gbit/s 瓶颈的额外整形对照如下。各组均使用原配置和 512 MiB 上限；单位分别为 Mbit/s 和 ms。', '',
                  '| 队列 | 排除起始 2 秒后消费速度中位数 | 远端 P99 中位数 |', '| --- | ---: | ---: |']
        for qdisc in ['fq', 'cake', 'cake-shaped']:
            rows = [row for row in shaped if row['qdisc'] == qdisc]
            speed = statistics.median(row['receiver']['steady_fast_mbps'] for row in rows)
            tail = statistics.median(probe_tail(row, 'remote_probe') for row in rows)
            lines.append(f'| {qdisc} | {speed:.2f} | {tail:.2f} |')
        lines += ['', '这里 cake-shaped 明确设置了 900 Mbit/s。它将排队延迟拉回接近 300 ms 的基础 RTT，同时损失部分吞吐；不能把这种取舍归功于仅设置 default_qdisc=cake。整形只验证了这个已知瓶颈的受控链路，没有加入产品脚本，也不能推导为对任意晚高峰线路有效。', '']
    lines += ['本轮没有证明修正版相对原项目存在稳定、普适的网络性能提升。明确收益是纠正了早期 32 MiB 草稿的回退、保留并验证 Cloudflare 设计、增加补丁依赖检查和可复现验证；原有安装可靠性修复继续保留。测试通过也不等同于验证了目标服务器的安装、引导和物理网卡。', '']
    return lines


def summarize(paths):
    sections = []
    count = 0
    datasets = {}
    for path in paths:
        if not path.exists():
            continue
        text = gzip.decompress(path.read_bytes()).decode() if path.suffix == '.gz' else path.read_text()
        data = json.loads(text)
        datasets[path.name.removesuffix('.gz').removesuffix('.json')] = data
        count += len(data['runs'])
        groups = defaultdict(list)
        for row in data['runs']:
            groups[(row['scenario'], row['mode'], row['streams'], row['qdisc'], row['profile'])].append(row)
        sections.extend([
            f"## {path.name.removesuffix('.gz').removesuffix('.json')}", '',
            f"内核：`{data['kernel']}`。每次测量 {data['runs'][0]['duration']} 秒；原始数据：[{path.name}]({path.name})。", '',
            '括号为各次独立运行的最小值–最大值；表中为各运行指标的中位数，未把单次运行内采样当成独立重复。', '',
            '| 场景/读取模式/流数 | 队列 | 配置 | 次数 | 应用平均消费 (Mbit/s) | 快速阶段消费 (Mbit/s) | 接收实际内存峰值 (MiB) |',
            '| --- | --- | --- | ---: | ---: | ---: | ---: |',
        ])
        for (scenario, mode, streams, qdisc, profile), rows in sorted(groups.items()):
            sections.append(f"| {scenario}/{mode}/{streams} | {qdisc} | {profile} | {len(rows)} | "
                f"{median_text([r['receiver']['wall_mbps'] for r in rows])} | "
                f"{median_text([r['receiver']['steady_fast_mbps'] for r in rows])} | "
                f"{median_text([peak_receive(r) for r in rows])} |")
        sections.extend(['',
            '| 场景/模式/流数 | 队列 | 配置 | 本机 P95/P99 (ms) | 远端 P95/P99 (ms) | 失败探测次数（各次） | 被 collapse 的段数（各次） | 接收队列丢包（各次） |',
            '| --- | --- | --- | ---: | ---: | --- | --- | --- |',
        ])
        for (scenario, mode, streams, qdisc, profile), rows in sorted(groups.items()):
            failures = [r['local_probe']['errors'] + r['remote_probe']['errors'] for r in rows]
            collapsed = [r['counter_deltas']['receiver'].get('TcpExt:TCPRcvCollapsed', 0) for r in rows]
            drops = [r['counter_deltas']['receiver'].get('TcpExt:TCPRcvQDrop', 0) for r in rows]
            sections.append(f"| {scenario}/{mode}/{streams} | {qdisc} | {profile} | "
                f"{tails_text(rows, 'local_probe')} | "
                f"{tails_text(rows, 'remote_probe')} | {failures} | {collapsed} | {drops} |")
        sections.append('')
    introduction = [
        '# 扩展网络模拟测试', '',
        f'本报告包含 {count} 次独立测量。原始配置、实际生效参数、逐秒读取量、socket 内存采样、探测延迟、TCP 计数及 qdisc 统计均随结果保存。测试时源代码另存于 [harness-sources.json](harness-sources.json)。', '',
        '## 方法', '',
        '间歇读取方法参考 [Cloudflare 原文](https://blog.cloudflare.com/optimizing-tcp-for-high-throughput-and-low-latency/)，阈值语义核对了 [Cloudflare 补丁](https://github.com/cloudflare/linux/blob/master/patches/0014-add-a-sysctl-to-enable-disable-tcp_collapse-logic.patch)。', '',
        '- 在 Debian trixie / 本地 XanMod 内核的临时用户与网络命名空间中运行；不安装内核，不修改主机网络。每次运行重新创建端点与中间路由器。',
        '- `32-off`、`32-on`、`512-off`、`512-on` 构成因子对照：其余参数均取原配置，只改变接收/发送缓冲上限（MiB）和 collapse 策略。`on` 为阈值 6291456；`off` 为 0，恢复原生 Linux collapse 行为，并非禁止所有 collapse。',
        '- `original` 为原提交完整配置，`candidate` 为该结果文件生成时的工作区配置；不同阶段的具体内容以各 JSON 的 profiles 为准，不能将早期 32 MiB 草稿和修正版混为一谈。',
        '- `high_bdp`：每方向 1 Gbit/s、150 ms 延迟，无注入丢包，基础 RTT 约 300 ms，BDP 约 37.5 MB，尚未计入 socket 元数据。',
        '- `peak`：每方向 100 Mbit/s、75 ± 20 ms 延迟、独立 1% 随机丢包。',
        '- `burst`：同样的限速和延迟，采用 Gilbert–Elliott 丢包模型：进入坏状态概率 0.2%，离开坏状态概率 10%，坏状态丢包率 90%，好状态丢包率 0.01%。稳态理论平均丢包率约为每方向 1.77%；平均约十个包的坏状态不等同于固定时长断网。它与 peak 的平均丢包率不同，不能把跨场景差异仅归因于突发性。',
        '- `bulk` 为连续读取；`oscillating` 每 20 秒循环：5 秒尽快读取，15 秒按此前每秒读取高水位的 5% 读取，其余时间暂停。60 秒运行覆盖三次循环。',
        '- `fq` 与 `cake` 均未配置整形带宽；`cake-shaped` 仅作为实验对照，在 100 Mbit/s 路径上设置 90 Mbit/s，在 1 Gbit/s 路径上设置 900 Mbit/s。产品脚本没有新增整形功能。',
        '- 所有虚拟网卡关闭 TSO/GSO/GRO，使 netem 按独立包施加丢包；netem 队列上限为 65536 包，避免高 BDP 延迟管道被过小队列截断。',
        '- 每约 200 ms 采样 ss 的实际接收分配 r、接收上限 rb、队列及发送内存。内存包含少量探测 socket；采样峰值不是连续观测的精确最大值。缓冲上限也不是实际分配内存的绝对硬限额。',
        '- 每约 20 ms 发起本机或远端 TCP echo 探测；远端采样间隔至少为往返延迟。本机探测不经过受限链路。P99 按每次运行独立计算，再跨运行汇总；失败次数单列，不能忽略超时去宣称低尾延迟。',
        '- 本机/远端 echo 延迟均不是内核 collapse 函数耗时。TCPRcvCollapsed 计数表示被 collapse 的段数，不表示调用次数；没有使用内核函数跟踪，无法复现原文的函数耗时分布。',
        '- 对间歇读取，快速阶段消费可能包含此前积压数据，不能当作链路瞬时吞吐。bulk 的快速阶段消费排除起始 2 秒；间歇读取则排除每个快速阶段的前 2 秒。原始逐秒数据保留。',
        '- 测试顺序每轮确定性打乱，种子按轮改变；相同种子不意味着新旧配置逐包受到完全相同的损失。',
        '- 结果针对这个内核、机器和合成负载。未验证物理 NIC、真实 ISP 突发拥塞、低 RAM 主机、纯转发和 UDP/QUIC。进程 CPU 时间不包括归属到其他上下文的 softirq，不能当作完整网络 CPU 成本。', '',
    ]
    return '\n'.join(introduction[:4] + findings(datasets) + introduction[4:] + sections)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(summarize(args.inputs))
    print(f'Updated {args.output}')


if __name__ == '__main__':
    main()
