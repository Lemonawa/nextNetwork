#!/usr/bin/env python3
"""Verify exact tests and thresholds before collecting confirmation data."""
import unittest
import tempfile
from pathlib import Path
from confirmatory_simulation import assignments, sign_pvalue, metrics, decide, prepare, verify_protocol, analyze


class ConfirmationAnalysisTest(unittest.TestCase):
    def test_exact_sign_test_and_family_threshold(self):
        self.assertEqual(sign_pvalue(8, 8), 1 / 256)
        self.assertEqual(sign_pvalue(7, 8), 9 / 256)
        self.assertLess(sign_pvalue(8, 8) * 8, .05)
        self.assertGreater(sign_pvalue(7, 8) * 8, .05)

    def test_assignment_identity_ignores_comments_not_values(self):
        self.assertEqual(assignments('# comment\na = 1 2\n'), {'a': ['1', '2']})
        self.assertNotEqual(assignments('a = 1'), assignments('a = 2'))

    def test_window_discards_startup_and_partial_final_bin(self):
        row = {'duration': 30, 'data': {
            'receiver': {'started_monotonic': 100., 'bytes_per_second': [1]*10 + [125000000]*19 + [1], 'wall_mbps': 10},
            'remote_probe': {'started_monotonic': 99., 'samples': [
                {'elapsed': 10, 'ms': 9999},  # receiver time 9, startup
                {'elapsed': 11, 'ms': 300},
                {'elapsed': 20, 'ms': 302},
                {'elapsed': 30, 'ms': 9999},  # receiver time 29, excluded
            ]},
            'counter_deltas': {'receiver': {'TcpExt:TCPRcvCollapsed': 123}},
            'socket_samples': [{'receiver': {'allocated_receive': 1048576}}],
        }}
        result = metrics(row)
        self.assertEqual(result['steady_mbps'], 1000)
        self.assertLess(result['remote_p99_ms'], 303)
        self.assertEqual(result['remote_samples'], 2)
        self.assertEqual(result['collapsed_plus_one'], 124)

    def test_invalidated_experiment_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / 'INVALIDATED.md').write_text('Discarded measurements')
            for action in (prepare, verify_protocol, analyze):
                with self.subTest(action=action.__name__), self.assertRaises(ValueError):
                    action(directory)

    def test_incomplete_experiment_cannot_be_decided(self):
        with self.assertRaises(ValueError):
            decide({}, [])


if __name__ == '__main__':
    unittest.main()
