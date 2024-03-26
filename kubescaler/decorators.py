# Copyright 2023-2024 Lawrence Livermore National Security, LLC and other
# HPCIC DevTools Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (MIT)

import signal
import time
from functools import partial, update_wrapper


class timed:
    """
    Time the runtime of a function, add to times
    """

    def __init__(self, func):
        update_wrapper(self, func)
        self.func = func

    def __get__(self, obj, objtype):
        return partial(self.__call__, obj)

    def __call__(self, cls, *args, **kwargs):
        name = self.func.__name__

        if name not in [
            "create_cluster",
            "delete_cluster",
            "create_cluster_nodes",
            "delete_nodegroup",
        ]:
            name = f"{name}-size-{cls.node_count}"
        start = time.time()
        res = self.func(cls, *args, **kwargs)
        end = time.time()
        cls.times[name] = round(end - start, 3)
        return res


def timed_function(func):
    """
    Time a function
    """

    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        end = time.time()
        total_time = end - start
        return {"result": result, "time_seconds": total_time}

    return wrapper


# https://stackoverflow.com/questions/2281850/timeout-function-if-it-takes-too-long-to-finish
class TimeoutException(Exception):
    pass


class timeout:
    """
    Usage: with timeout:
    """

    def __init__(self, seconds=60, error_message="Timeout"):
        self.seconds = seconds
        self.error_message = error_message

    def handle_timeout(self, signum, frame):
        raise TimeoutException(self.error_message)

    def __enter__(self):
        signal.signal(signal.SIGALRM, self.handle_timeout)
        signal.alarm(self.seconds)

    def __exit__(self, type, value, traceback):
        signal.alarm(0)


class retry:
    """
    Retry a function that is part of a class
    """

    def __init__(self, func, attempts=5, timeout=2):
        update_wrapper(self, func)
        self.func = func
        self.attempts = attempts
        self.timeout = timeout

    def __get__(self, obj, objtype):
        return partial(self.__call__, obj)

    def __call__(self, cls, *args, **kwargs):
        attempt = 0
        attempts = self.attempts
        timeout = self.timeout
        while attempt < attempts:
            try:
                return self.func(cls, *args, **kwargs)
            except Exception as e:
                sleep = timeout + 3**attempt
                print(f"Retrying in {sleep} seconds - error: {e}")
                time.sleep(sleep)
                attempt += 1
        return self.func(cls, *args, **kwargs)
