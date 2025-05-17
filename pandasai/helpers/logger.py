import logging  # Used for level constants in .log() method and for mapping

from loguru import logger

# Mapping from standard Python logging level numbers to Loguru level names
LOGGING_LEVEL_TO_LOGURU_LEVEL = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARNING",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "CRITICAL",
}

# Default Loguru level name to use if an unknown integer level is passed to the .log() method
DEFAULT_LOGURU_LEVEL_NAME_FOR_LOG_METHOD = "INFO"


class Logger:
    """
    Logger class for PandasAI, refactored to use Loguru.
    This class configures the shared Loguru logger for console output
    and optionally for file output ("pandasai.log"). When you create an
    instance of this Logger, it sets up or reconfigures these logging sinks.
    If you create multiple Logger instances, each new instance will update
    the configuration, ensuring the logging settings reflect the
    parameters of the most recently created Logger. This mimics the original
    behavior where logger settings for "pandasai" would be updated upon new
    Logger instantiations.
    """

    # Class variables to store the IDs of the sinks managed by this Logger.
    # This allows the class to remove its specific sinks before re-adding them,
    # preventing duplicate handlers and ensuring the latest configuration applies,
    # without interfering with other potential Loguru sinks in the application.
    _console_sink_id = None
    _file_sink_id = None

    def __init__(self, save_logs: bool = True, verbose: bool = False):
        """
        Initializes and configures the Loguru logger.
        Args:
            save_logs (bool): If True, logs will be saved to "pandasai.log". Defaults to True.
            verbose (bool): If True, the console logging level is set to INFO.
                            Otherwise, it's set to WARNING. Defaults to False.
        """
        self.verbose = verbose
        self.save_logs = save_logs
        self._configured_console_level_name = "INFO" if self.verbose else "WARNING"

        # Attempt to remove previously configured sinks by this class.
        # This ensures that re-instantiating Logger updates the configuration
        # rather than stacking multiple identical handlers.
        if Logger._console_sink_id is not None:
            try:
                logger.remove(Logger._console_sink_id)
            except ValueError:
                # Sink might have been already removed or was never added.
                pass
            Logger._console_sink_id = None

        if Logger._file_sink_id is not None:
            try:
                logger.remove(Logger._file_sink_id)
            except ValueError:
                pass
            Logger._file_sink_id = None

        # Add a console sink. The original logger used sys.stdout.
        # The original format: "%(asctime)s [%(levelname)s] %(message)s"
        # Loguru format: "{time:YYYY-MM-DD HH:mm:ss} [{level}] {message}"
        # Logger._console_sink_id = logger.add(
        #     sys.stdout,
        #     level=self._configured_console_level_name,
        #     format="{time:YYYY-MM-DD HH:mm:ss} [{level}] {message}",
        #     colorize=True,  # Loguru adds nice coloring to console output.
        #     # Set to False if strict adherence to non-colored output is needed.
        # )

        if self.save_logs:
            # The file log level should match the verbosity set for the console,
            # mirroring the original behavior where the file handler respected the logger's level.
            file_sink_level = self._configured_console_level_name
            Logger._file_sink_id = logger.add(
                "pandasai.log",  # Name of the log file, as in the original.
                level=file_sink_level,
                format="{time:YYYY-MM-DD HH:mm:ss} [{level}] {message}",  # Consistent format.
                rotation="10 MB",  # Adds log rotation, a common best practice.
                retention="7 days",  # Keeps logs for a week.
                encoding="utf-8",  # Standard encoding for log files.
                # enqueue=True,  # For asynchronous logging; useful in high-throughput scenarios.
                # Not in the original, but a good Loguru feature to be aware of.
            )
        else:
            # Ensure _file_sink_id is reset if file logging is disabled.
            Logger._file_sink_id = None

    @property
    def _logger(self):
        """
        Provides access to the Loguru logger instance.
        In the original implementation, this property returned an instance of
        `logging.Logger`. In this refactored version, it returns the global
        `loguru.logger` object, which has been configured by this class.
        """
        return logger

    def _get_level(self) -> str:
        """
        Returns the string name of the configured console logging level (e.g., "INFO", "WARNING").
        This reflects the primary verbosity setting determined by the `verbose`
        flag during the Logger's initialization. The original method returned an
        integer (like `logging.INFO`). This version returns Loguru's string representation.
        """
        return self._configured_console_level_name

    def log(self, message: str, level: int = logging.INFO):
        """
        Logs a message with the specified standard Python logging level.
        Args:
            message (str): The message to be logged.
            level (int): The logging level, using standard `logging` module constants
                         (e.g., `logging.INFO`, `logging.WARNING`).
                         Defaults to `logging.INFO`.
        """
        level_name = LOGGING_LEVEL_TO_LOGURU_LEVEL.get(level)
        if level_name:
            # .opt(depth=1) ensures Loguru reports the call site of this `log` method's
            # caller, rather than this method itself, making debugging easier.
            self._logger.opt(depth=1).log(level_name, message)
        else:
            # If an unknown integer level is provided, log it with a default
            # level and include the original numeric level in the message.
            self._logger.opt(depth=1).log(
                DEFAULT_LOGURU_LEVEL_NAME_FOR_LOG_METHOD,
                f"(Original level: {level}) {message}"
            )

    def info(self, message: str):
        """Logs a message with INFO level."""
        self._logger.opt(depth=1).info(message)

    def warning(self, message: str):
        """Logs a message with WARNING level."""
        self._logger.opt(depth=1).warning(message)

    def error(self, message: str):
        """Logs a message with ERROR level."""
        self._logger.opt(depth=1).error(message)

    def debug(self, message: str):
        """
        Logs a message with DEBUG level.
        Note: These messages will only be output if the configured level for a
        sink (e.g., console or file) is set to DEBUG. If `verbose` was False
        (setting console to WARNING), debug messages won't appear on the console.
        """
        self._logger.opt(depth=1).debug(message)
