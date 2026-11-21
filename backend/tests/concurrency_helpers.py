"""Exécution simultanée de callables avec une vraie connexion PostgreSQL par thread."""
import threading
from concurrent.futures import ThreadPoolExecutor

from django.db import connections


def run_concurrently(callables, *, barrier_timeout=15, result_timeout=90):
    """Lance tous les callables en même temps (barrière) ; retourne [("ok", valeur) | ("err", exception)]."""
    barrier = threading.Barrier(len(callables))

    def wrap(fn):
        def runner():
            try:
                barrier.wait(timeout=barrier_timeout)
                try:
                    return ("ok", fn())
                except BaseException as exc:  # noqa: BLE001 - on veut tout observer
                    return ("err", exc)
            finally:
                connections.close_all()  # ferme la connexion du thread

        return runner

    with ThreadPoolExecutor(max_workers=len(callables)) as pool:
        futures = [pool.submit(wrap(fn)) for fn in callables]
        return [f.result(timeout=result_timeout) for f in futures]


def split(results):
    oks = [value for kind, value in results if kind == "ok"]
    errs = [value for kind, value in results if kind == "err"]
    return oks, errs
