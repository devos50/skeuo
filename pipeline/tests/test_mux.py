import unittest
import threading

from skeuo.usb.mux import MuxConnection, MuxError, TCP_HEADER


class MuxFlowTests(unittest.TestCase):
    def test_send_uses_small_advertised_window(self):
        class Peer:
            def __init__(self):
                self.payload = bytearray()

            def _send(self, protocol, packet):
                sport, dport, seq, ack, off, flags, win, _, _ = TCP_HEADER.unpack_from(packet)
                data = packet[TCP_HEADER.size:]
                if not data:
                    return
                self.payload.extend(data)
                # Acknowledge each segment, retaining a window below MAX_SEGMENT.
                connection._input(0x10, 0, seq + len(data), 3, b'')

        peer = Peer()
        connection = MuxConnection(peer, 1, 12345)
        # This peer delivers ACKs inline instead of through the USB reader thread.
        connection._tx_lock = threading.RLock()
        connection.state = 'connected'
        connection.tx_win = 3 << 8
        payload = bytes(range(256)) * 100
        connection.send(payload, timeout=0.01)
        self.assertEqual(peer.payload, payload)
        self.assertEqual(connection._in_flight(), 0)

    def test_retries_unacknowledged_data_and_ignores_old_ack(self):
        class Peer:
            def __init__(self):
                self.calls = 0
                self.payload = bytearray()

            def _send(self, protocol, packet):
                seq = TCP_HEADER.unpack_from(packet)[2]
                data = packet[TCP_HEADER.size:]
                if not data:
                    return
                self.calls += 1
                if seq == len(self.payload):
                    self.payload.extend(data)
                # Lose the first acknowledgement, then acknowledge a retry.
                if self.calls > 1:
                    connection._input(0x10, 0, len(self.payload), 1, b'')

        peer = Peer()
        connection = MuxConnection(peer, 1, 12345)
        # This peer delivers ACKs inline instead of through the USB reader thread.
        connection._tx_lock = threading.RLock()
        connection.state = 'connected'
        connection.tx_win = 256
        connection.send(b'a' * 512, timeout=2)
        self.assertEqual(peer.payload, b'a' * 512)
        self.assertEqual(peer.calls, 3)
        connection._input(0x10, 0, 256, 1, b'')
        self.assertEqual(connection.tx_acked, 512)
        self.assertEqual(connection._unacked, b'')

    def test_zero_window_fails_instead_of_hanging(self):
        connection = MuxConnection(None, 1, 12345)
        connection.state = 'connected'
        with self.assertRaises(MuxError):
            connection.send(b'x', timeout=0.001)
