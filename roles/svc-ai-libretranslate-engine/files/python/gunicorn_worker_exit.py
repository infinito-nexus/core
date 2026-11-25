import os
import sys


def worker_exit(server, worker):
    """
    Args:
        server: the gunicorn arbiter.
        worker: the worker that leaves; the hook ends its process with the
            code of the SystemExit gunicorn is raising.
    """
    # Exception: the arbiter also calls this hook for a worker pid that is already gone.
    if os.getpid() != worker.pid:
        return
    sys.stdout.flush()
    sys.stderr.flush()
    code = getattr(sys.exc_info()[1], "code", 1)
    # Exception: a LibreTranslate worker recycled by --max-requests hangs in interpreter shutdown, and the arbiter reaps it only after --timeout (2400 s).
    # upstream: https://github.com/LibreTranslate/LibreTranslate/issues/1042
    # upstream: https://github.com/LibreTranslate/LibreTranslate/pull/1041
    os._exit(code if isinstance(code, int) else 1)
