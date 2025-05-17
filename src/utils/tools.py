import functools
import time


def log_time(func):
    """
    A decorator that logs the execution time of a function.
    """

    @functools.wraps(func)  # Preserves function metadata
    def wrapper(*args, **kwargs):
        # Record the start time
        start_time = time.perf_counter()
        # Call the original function
        result = func(*args, **kwargs)
        # Record the end time
        end_time = time.perf_counter()
        # Calculate the runtime
        run_time = end_time - start_time
        # Log the runtime
        print(f"Function '{func.__name__}' executed in {run_time:.4f} seconds")
        return result

    return wrapper
