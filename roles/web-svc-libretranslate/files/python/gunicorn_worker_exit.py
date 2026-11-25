import os
import sys


def worker_exit(server, worker):
    """
    Args:
        server: the gunicorn arbiter.
        worker: the worker that leaves; the hook ends its process with the
            code of the SystemExit gunicorn is raising.
    """
    if os.getpid() != worker.pid:
        return
    sys.stdout.flush()
    sys.stderr.flush()
    pending = sys.exc_info()[1]
    if isinstance(pending, SystemExit) and isinstance(pending.code, int):
        os._exit(pending.code)
    os._exit(1)
