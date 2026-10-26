#!/usr/bin/env python3
"""Regression checks for metric parsing and isolated profile changes."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from extended_network_simulation import replace_setting, socket_memory
from summarize_extended_simulation import percentile, probe_tail


class NetworkMetricsTest(unittest.TestCase):
    def test_socket_memory_preserves_actual_allocations_and_data_queues(self):
        fixture = '''Recv-Q Send-Q Local Address:Port Peer Address:Port
100 200 10.200.2.1:5201 10.200.1.1:40000
 skmem:(r4096,rb8388608,t1024,tb2097152,f0,w8192,o0,bl64,d0)
32 64 127.0.0.1:5202 127.0.0.1:40001
 skmem:(r1024,rb262144,t0,tb16384,f0,w512,o0,bl0,d0)
'''
        with patch('extended_network_simulation.run', return_value=SimpleNamespace(stdout=fixture)):
            memory = socket_memory()
        self.assertEqual(memory['recv_q'], 100)
        self.assertEqual(memory['send_q'], 200)
        self.assertEqual(memory['allocated_receive'], 5120)
        self.assertEqual(memory['receive_limit'], 8650752)
        self.assertEqual(memory['allocated_send'], 1024)
        self.assertEqual(memory['queued_send'], 8704)
        self.assertEqual(memory['backlog'], 64)

    def test_latency_percentiles_do_not_hide_failed_probes(self):
        self.assertEqual(percentile([1, 2, 3, 4, 5], .95), 4.8)
        self.assertIsNone(percentile([], .99))
        row = {'local_probe': {'samples': [{'ms': 1}, {'ms': 3}, {'ms': 2000, 'failed': True}], 'errors': 1}}
        self.assertEqual(probe_tail(row, 'local_probe', .5), 2)
        self.assertEqual(row['local_probe']['errors'], 1)

    def test_factorial_change_does_not_alter_other_settings(self):
        original = '# profile\nnet.ipv4.ip_forward = 1\nnet.ipv4.tcp_rmem = 8192 262144 536870912\n'
        updated = replace_setting(original, 'net.ipv4.tcp_rmem', '8192 262144 33554432')
        self.assertEqual(updated, original.replace('536870912', '33554432'))
        added = replace_setting(updated, 'net.ipv4.tcp_collapse_max_bytes', 6291456)
        self.assertTrue(added.startswith(updated))
        self.assertEqual(added.count('net.ipv4.tcp_collapse_max_bytes'), 1)


if __name__ == '__main__':
    unittest.main()
