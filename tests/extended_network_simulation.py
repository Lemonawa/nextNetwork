#!/usr/bin/env python3
"""Factorial buffer/collapse tests, confined to disposable user/network namespaces."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import tempfile
import time
from network_simulation import isolated_link,render,run

ROOT=Path(__file__).resolve().parents[1]
WORKLOAD=ROOT/'tests/tcp_workload.py'
SCENARIOS={
 'good':dict(delay='1ms',jitter='0.1ms',loss='0%',rate='1gbit'),
 'peak':dict(delay='75ms',jitter='20ms',loss='1%',rate='100mbit'),
 'high_bdp':dict(delay='150ms',jitter='0ms',loss='0%',rate='1gbit'),
 'burst':dict(delay='75ms',jitter='20ms',loss='0%',rate='100mbit',burst_loss=True),
}


def counters(pid=None):
    result={}
    for path in ['/proc/net/netstat','/proc/net/snmp']:
        lines=run(['cat',path],pid).stdout.splitlines()
        for i in range(0,len(lines),2):
            names,values=lines[i].split(),lines[i+1].split()
            result.update({names[0]+k:int(v) for k,v in zip(names[1:],values[1:])})
    return result


def delta(before,after):
    return {k:after[k]-v for k,v in before.items() if after[k]!=v}


def socket_memory(pid=None):
    text=run(['ss','-tmn','state','established'],pid).stdout
    totals=dict(recv_q=0,send_q=0,allocated_receive=0,receive_limit=0,
                allocated_send=0,send_limit=0,queued_send=0,backlog=0)
    for line in text.splitlines():
        fields=line.split()
        if len(fields)>=4 and fields[0].isdigit() and fields[1].isdigit() and ':5201' in line:
            totals['recv_q']+=int(fields[0]);totals['send_q']+=int(fields[1])
    for match in re.finditer(r'skmem:\(([^)]+)\)',text):
        fields=dict(re.findall(r'([a-z]+)(\d+)',match.group(1)))
        for key,field in [('allocated_receive','r'),('receive_limit','rb'),('allocated_send','t'),
                          ('send_limit','tb'),('queued_send','w'),('backlog','bl')]:
            totals[key]+=int(fields.get(field,0))
    return totals


def worker(payload):
    profile,qdisc,scenario,mode,duration,streams,seed=payload
    processes=[]
    with isolated_link(profile,qdisc,scenario,seed) as (router,receiver,skipped):
        if 'net.ipv4.tcp_collapse_max_bytes' in skipped:
            raise RuntimeError('Cloudflare patch is unavailable; cannot test its effect')
        before={'sender':counters(),'receiver':counters(receiver.pid)}
        with tempfile.TemporaryDirectory() as directory:
            def launch(name,role,target=None,pid=None):
                out=open(Path(directory)/(name+'.json'),'w+')
                err=open(Path(directory)/(name+'.err'),'w+')
                args=(['nsenter','-t',str(pid),'-n'] if pid else [])+[
                    sys.executable,str(WORKLOAD),role,'--mode',mode,'--duration',str(duration),'--streams',str(streams)]
                if target:args+=['--target',target]
                proc=subprocess.Popen(args,stdout=out,stderr=err)
                processes.append((name,proc,out,err));return proc
            try:
                recv=launch('receiver','receiver',pid=receiver.pid)
                for _ in range(200):
                    listening=run(['ss','-ltn'],receiver.pid).stdout
                    if ':5201' in listening and ':5202' in listening:break
                    if recv.poll() is not None:raise RuntimeError('Receiver failed to start')
                    time.sleep(.02)
                else:raise RuntimeError('Receiver startup timed out')
                launch('local_probe','probe','127.0.0.1',receiver.pid)
                launch('remote_probe','probe','10.200.2.1')
                launch('sender','sender')
                samples=[];start=time.monotonic()
                while recv.poll() is None:
                    if time.monotonic()-start>duration+20:raise RuntimeError('Workload timed out')
                    samples.append({'elapsed':time.monotonic()-start,'receiver':socket_memory(receiver.pid),'sender':socket_memory()})
                    time.sleep(.2)
                for _,proc,_,_ in processes:proc.wait(timeout=12)
                data={}
                for name,proc,out,err in processes:
                    out.seek(0);err.seek(0)
                    if proc.returncode:raise RuntimeError(f'{name}: {err.read()}')
                    data[name]=json.load(out)
                if data['sender']['errors']:raise RuntimeError(str(data['sender']['errors']))
                data['socket_samples']=samples
                data['counter_deltas']={'sender':delta(before['sender'],counters()),
                                        'receiver':delta(before['receiver'],counters(receiver.pid))}
                data['qdisc_stats']={name:json.loads(run(['tc','-j','-s','qdisc','show'],pid).stdout)
                    for name,pid in [('sender',None),('router',router.pid),('receiver',receiver.pid)]}
                data['effective_settings']={name:run(['sysctl','net.ipv4.tcp_rmem','net.ipv4.tcp_wmem',
                    'net.ipv4.tcp_collapse_max_bytes','net.ipv4.tcp_congestion_control'],pid).stdout
                    for name,pid in [('sender',None),('receiver',receiver.pid)]}
                data['skipped_sysctls']=sorted(skipped)
                return data
            finally:
                for _,proc,out,err in processes:
                    if proc.poll() is None:proc.terminate();proc.wait(timeout=5)
                    out.close();err.close()


def replace_setting(profile,key,value):
    lines=profile.splitlines();found=False
    for i,line in enumerate(lines):
        if line.split('=')[0].strip()==key:
            lines[i]=f'{key} = {value}';found=True
    if not found:lines.append(f'{key} = {value}')
    return '\n'.join(lines)+'\n'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--duration',type=int,default=20)
    p.add_argument('--scenario',nargs='+',choices=SCENARIOS,default=['high_bdp'])
    p.add_argument('--mode',nargs='+',choices=['bulk','oscillating'],default=['bulk','oscillating'])
    p.add_argument('--qdisc',nargs='+',choices=['fq','cake','cake-shaped'],default=['fq','cake'])
    p.add_argument('--profiles',nargs='+',default=['32-off','32-on','512-off','512-on'])
    p.add_argument('--streams',type=int,default=1)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.repeats<1 or a.duration<4 or a.streams<1:p.error('Invalid repeats, duration or streams')
    source=run(['git','show','HEAD:main.sh']).stdout
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'baseline.sh';path.write_text(source);baseline=render(path)
    profiles={'original':baseline,'candidate':render(ROOT/'main.sh')}
    for size in [32,512]:
        for enabled in [False,True]:
            profile=replace_setting(baseline,'net.ipv4.tcp_rmem',f'8192 262144 {size*1048576}')
            profile=replace_setting(profile,'net.ipv4.tcp_wmem',f'4096 16384 {size*1048576}')
            profiles[f'{size}-{"on" if enabled else "off"}']=replace_setting(profile,'net.ipv4.tcp_collapse_max_bytes',6291456 if enabled else 0)
    for name in a.profiles:
        if name not in profiles:p.error(f'Unknown profile: {name}')
    results={'kernel':os.uname().release,'os_release':Path('/etc/os-release').read_text(),
        'baseline_commit':run(['git','rev-parse','HEAD']).stdout.strip(),
        'started_at_utc':datetime.now(timezone.utc).isoformat(),
        'harness_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'workload_sha256':hashlib.sha256(WORKLOAD.read_bytes()).hexdigest(),
        'profiles':{n:profiles[n] for n in a.profiles},'scenarios':SCENARIOS,
        'notes':['TSO/GSO/GRO disabled on all veth ends','Socket samples include small probe sockets',
                 'Echo latency is not kernel function latency','Process CPU excludes unattributed softirq work'],'runs':[]}
    schedule=[(n,q,s,m) for s in a.scenario for m in a.mode for n in a.profiles for q in a.qdisc]
    for repeat in range(a.repeats):
        order=schedule.copy();random.Random(931+repeat).shuffle(order)
        for name,q,scenario,mode in order:
            settings=SCENARIOS[scenario].copy()
            if q=='cake-shaped':settings['shaper_rate']='90mbit' if settings['rate']=='100mbit' else '900mbit'
            payload=[profiles[name],q,settings,mode,a.duration,a.streams,repeat]
            with tempfile.NamedTemporaryFile(mode='w+',suffix='.json') as temp:
                json.dump(payload,temp);temp.flush()
                data=json.loads(run(['unshare','-n',sys.executable,str(Path(__file__).resolve()),'--worker',temp.name]).stdout)
            row=dict(profile=name,qdisc=q,scenario=scenario,mode=mode,duration=a.duration,streams=a.streams,repeat=repeat+1,**data)
            results['runs'].append(row);a.output.parent.mkdir(parents=True,exist_ok=True)
            temporary=a.output.with_suffix('.tmp');temporary.write_text(json.dumps(results,indent=2)+'\n');temporary.replace(a.output)
            peak=max(s['receiver']['allocated_receive'] for s in data['socket_samples'])/1048576
            collapsed=data['counter_deltas']['receiver'].get('TcpExt:TCPRcvCollapsed',0)
            print(json.dumps(dict(profile=name,qdisc=q,scenario=scenario,mode=mode,repeat=repeat+1,
                steady_fast_mbps=data['receiver']['steady_fast_mbps'],receive_peak_mib=peak,collapsed=collapsed)),flush=True)


if __name__=='__main__':
    if os.geteuid()!=0 or Path('/proc/self/uid_map').read_text().split()[-1]!='1':
        sys.exit('Run in isolation: unshare -Urn python3 ...')
    if len(sys.argv)==3 and sys.argv[1]=='--worker':print(json.dumps(worker(json.loads(Path(sys.argv[2]).read_text()))))
    else:
        try:main()
        except subprocess.CalledProcessError as error:
            sys.stderr.write(error.stderr or str(error))
            raise SystemExit(error.returncode)
