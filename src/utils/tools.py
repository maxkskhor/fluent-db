import functools
import time

from loguru import logger


def log_time(func):
    """
    A decorator that logs the execution time of a function.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        run_time = time.perf_counter() - start_time
        logger.info(f"Function '{func.__name__}' executed in {run_time:.4f} seconds")
        return result

    return wrapper
