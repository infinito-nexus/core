import importlib.util
import io
import socket
import struct
import tempfile
import threading
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

_spec = importlib.util.spec_from_file_location(
    "seed_relay",
    str(Path(PROJECT_ROOT) / "roles/svc-db-mariadb/files/python/seed_relay.py"),
)
seed_relay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed_relay)

SECRET = b"replication-secret"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _start_receiver(port: int, sink: io.BytesIO) -> threading.Thread:
    receiver = threading.Thread(
        target=seed_relay.receive, args=(port, sink, SECRET, "127.0.0.1")
    )
    receiver.start()
    return receiver


class TestSeedRelay(unittest.TestCase):
    def test_round_trip(self):
        port = _free_port()
        payload = bytes(range(256)) * 9000
        sink = io.BytesIO()
        receiver = _start_receiver(port, sink)
        sent = seed_relay.send(
            "127.0.0.1", port, io.BytesIO(payload), SECRET, delay=0.05
        )
        receiver.join(timeout=10)
        self.assertEqual(sent, len(payload))
        self.assertEqual(sink.getvalue(), payload)

    def test_wrong_secret_is_rejected_and_receiver_keeps_listening(self):
        port = _free_port()
        sink = io.BytesIO()
        receiver = _start_receiver(port, sink)
        with self.assertRaises(seed_relay.ReceiverRejectedError):
            seed_relay.send(
                "127.0.0.1", port, io.BytesIO(b"forged"), b"wrong", delay=0.05
            )
        self.assertTrue(receiver.is_alive())
        seed_relay.send("127.0.0.1", port, io.BytesIO(b"genuine"), SECRET, delay=0.05)
        receiver.join(timeout=10)
        self.assertFalse(receiver.is_alive())
        self.assertEqual(sink.getvalue(), b"genuine")

    def test_peer_sending_without_handshake_is_rejected(self):
        port = _free_port()
        sink = io.BytesIO()
        receiver = _start_receiver(port, sink)
        conn = None
        for _ in range(100):
            try:
                conn = socket.create_connection(("127.0.0.1", port), timeout=1)
                break
            except OSError:
                threading.Event().wait(0.05)
        self.assertIsNotNone(conn)
        with conn:
            conn.sendall(b"x" * 64)
        seed_relay.send("127.0.0.1", port, io.BytesIO(b"ok"), SECRET, delay=0.05)
        receiver.join(timeout=10)
        self.assertEqual(sink.getvalue(), b"ok")

    def test_a_receiver_without_the_secret_gets_nothing(self):
        port = _free_port()
        got = bytearray()

        def impostor():
            with socket.create_server(("127.0.0.1", port)) as server:
                conn, _ = server.accept()
                with conn:
                    conn.sendall(b"n" * seed_relay.NONCE_BYTES)
                    seed_relay.read_exact(conn, seed_relay.DIGEST_BYTES)
                    seed_relay.read_exact(conn, seed_relay.NONCE_BYTES)
                    conn.sendall(b"f" * seed_relay.DIGEST_BYTES)
                    conn.settimeout(2)
                    try:
                        while chunk := conn.recv(4096):
                            got.extend(chunk)
                    except OSError:
                        pass

        thread = threading.Thread(target=impostor, daemon=True)
        thread.start()
        with self.assertRaises(seed_relay.ReceiverRejectedError):
            seed_relay.send(
                "127.0.0.1", port, io.BytesIO(b"backup"), SECRET, delay=0.05
            )
        thread.join(timeout=5)
        self.assertEqual(bytes(got), b"")

    def test_a_receiver_that_resets_after_the_answer_is_a_rejection(self):
        port = _free_port()

        def resetting_receiver():
            with socket.create_server(("127.0.0.1", port)) as server:
                conn, _ = server.accept()
                conn.sendall(b"n" * seed_relay.NONCE_BYTES)
                seed_relay.read_exact(conn, seed_relay.DIGEST_BYTES)
                conn.setsockopt(
                    socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
                )
                conn.close()

        thread = threading.Thread(target=resetting_receiver, daemon=True)
        thread.start()
        with self.assertRaises(seed_relay.ReceiverRejectedError):
            seed_relay.send(
                "127.0.0.1", port, io.BytesIO(b"backup"), SECRET, delay=0.05
            )
        thread.join(timeout=5)

    def test_send_gives_up(self):
        with self.assertRaises(ConnectionError):
            seed_relay.send(
                "127.0.0.1", _free_port(), io.BytesIO(b"x"), SECRET, attempts=2, delay=0
            )

    def test_empty_secret_file_is_refused(self):
        with tempfile.NamedTemporaryFile() as handle, self.assertRaises(ValueError):
            seed_relay.read_secret(handle.name)

    def test_a_receiver_without_a_sender_gives_up_after_its_timeout(self):
        with self.assertRaises(TimeoutError):
            seed_relay.receive(
                _free_port(), io.BytesIO(), SECRET, "127.0.0.1", accept_timeout=0.2
            )

    def test_usage(self):
        self.assertEqual(seed_relay.main(["bogus"]), 64)
        self.assertEqual(seed_relay.main(["recv", "4444"]), 64)


if __name__ == "__main__":
    unittest.main()
