#!/usr/bin/env python3
"""Test-only bulk/oscillating TCP readers and independent echo probes."""
import argparse
import json
import resource
import socket
import threading
import time


def probe(target, duration):
    samples, errors = [], 0
    start = time.monotonic()
    sock = None
    try:
        while time.monotonic() - start < duration:
            before = time.monotonic()
            try:
                if sock is None:
                    sock = socket.create_connection((target, 5202), timeout=2)
                    sock.settimeout(2)
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    before = time.monotonic()
                sock.sendall(b'x' * 32)
                remaining = 32
                while remaining:
                    part = sock.recv(remaining)
                    if not part:
                        raise ConnectionError('EOF')
                    remaining -= len(part)
                samples.append({'elapsed': before-start, 'ms': (time.monotonic()-before)*1000})
            except (OSError, ConnectionError):
                errors += 1
                samples.append({'elapsed': before-start, 'ms': (time.monotonic()-before)*1000, 'failed': True})
                if sock is not None:
                    sock.close()
                    sock = None
            time.sleep(max(0, .02-(time.monotonic()-before)))
    finally:
        if sock is not None:
            sock.close()
    return {'samples': samples, 'errors': errors, 'started_monotonic': start}


def echo(stop):
    def client(conn):
        with conn:
            conn.settimeout(.5)
            while not stop.is_set():
                try:
                    data = conn.recv(4096)
                    if not data:
                        return
                    conn.sendall(data)
                except socket.timeout:
                    pass
                except OSError:
                    return
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('0.0.0.0',5202))
        server.listen(32)
        server.settimeout(.2)
        while not stop.is_set():
            try:
                conn,_ = server.accept()
                threading.Thread(target=client,args=(conn,),daemon=True).start()
            except socket.timeout:
                pass


def receiver(a):
    stop = threading.Event()
    echo_thread = threading.Thread(target=echo,args=(stop,),daemon=True)
    echo_thread.start()
    results = [None]*a.streams
    start = None
    def reader(conn,index):
        bins = [0]*(a.duration+1)
        max_fast = 0
        with conn:
            conn.settimeout(.1)
            while True:
                elapsed = time.monotonic()-start
                if elapsed >= a.duration:
                    break
                second = int(elapsed)
                fast = a.mode=='bulk' or elapsed%20 < 5
                if not fast:
                    max_fast = max(max_fast,max(bins[:second] or [0]))
                    quota = max(1,int(max_fast*.05))
                    if bins[second] >= quota:
                        time.sleep(min(.02,second+1-elapsed))
                        continue
                    count = min(1048576,quota-bins[second])
                else:
                    count = 1048576
                try:
                    data = conn.recv(count)
                except socket.timeout:
                    continue
                if not data:
                    break
                after = time.monotonic()-start
                if after < a.duration:
                    bins[int(after)] += len(data)
        results[index] = {'bytes_per_second':bins[:a.duration], 'max_fast_bytes_per_second':max_fast}
    threads=[]
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        server.bind(('0.0.0.0',5201))
        server.listen(max(a.streams,16))
        server.settimeout(15)
        for i in range(a.streams):
            conn,_ = server.accept()
            if start is None:
                start=time.monotonic()
            t=threading.Thread(target=reader,args=(conn,i));t.start();threads.append(t)
        for t in threads:
            t.join()
    stop.set();echo_thread.join(timeout=1)
    bins=[sum(r['bytes_per_second'][i] for r in results) for i in range(a.duration)]
    fast=[i for i in range(a.duration) if a.mode=='bulk' or i%20<5]
    steady=[i for i in fast if i%20>=2] if a.mode=='oscillating' else list(range(2,a.duration))
    return {'mode':a.mode,'started_monotonic':start,'bytes_per_second':bins,'flows':results,
            'wall_mbps':sum(bins)*8/a.duration/1e6,
            'fast_phase_mbps':sum(bins[i] for i in fast)*8/len(fast)/1e6,
            'steady_fast_mbps':sum(bins[i] for i in steady)*8/max(1,len(steady))/1e6}


def sender(a):
    end=time.monotonic()+a.duration+3
    counts=[0]*a.streams
    errors=[]
    def send(index):
        try:
            with socket.create_connection((a.target,5201),timeout=10) as sock:
                sock.settimeout(.5)
                data=b'x'*1048576
                while time.monotonic()<end:
                    try:
                        counts[index]+=sock.send(data)
                    except socket.timeout:
                        continue
        except (BrokenPipeError,ConnectionResetError):
            pass
        except OSError as error:
            errors.append(str(error))
    threads=[threading.Thread(target=send,args=(i,)) for i in range(a.streams)]
    for t in threads:t.start()
    for t in threads:t.join()
    return {'bytes_sent':counts,'errors':errors}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('role',choices=['receiver','sender','probe'])
    p.add_argument('--mode',choices=['bulk','oscillating'],default='bulk')
    p.add_argument('--duration',type=int,default=60)
    p.add_argument('--streams',type=int,default=1)
    p.add_argument('--target',default='10.200.2.1')
    a=p.parse_args()
    result=receiver(a) if a.role=='receiver' else sender(a) if a.role=='sender' else probe(a.target,a.duration)
    usage=resource.getrusage(resource.RUSAGE_SELF)
    result['process_cpu_seconds']={'user':usage.ru_utime,'system':usage.ru_stime}
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
