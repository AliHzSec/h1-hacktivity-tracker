import datetime
import inspect
import logging
import os
import sys

import colorlog

# Add dotenv support
try:
    from dotenv import load_dotenv

    # Try to load .env file from current directory
    load_dotenv()
except ImportError:
    print("Warning: python-dotenv not installed. Cannot load .env file.")
    print("To install: pip install python-dotenv")

# Default log file path if not specified in .env
DEFAULT_LOG_DIR = "/var/log"
DEFAULT_LOG_FILE = f"app_{datetime.datetime.now().strftime('%Y%m%d')}.log"


def GetCallerInfo():
    """
    Get information about the caller (module, function, line)
    Returns a tuple of (module_name, function_name, line_number)
    """
    # Get the current frame and go back 2 frames to find the actual caller
    # (1 frame for this function, 1 frame for the logger method)
    frame = inspect.currentframe()
    if frame:
        try:
            # Go back to the logger method caller
            frame = frame.f_back  # get_caller_info caller
            if frame:
                frame = frame.f_back  # logger method caller
                if frame:
                    # Get module info
                    module = inspect.getmodule(frame)
                    module_name = "unknown"
                    if module:
                        if module.__name__ == "__main__":
                            # For main module, get the file name
                            module_name = os.path.basename(module.__file__).replace(".py", "")
                        else:
                            # For other modules, get the module name
                            module_name = module.__name__.split(".")[-1]

                    # Get function and line info
                    func_name = frame.f_code.co_name
                    line_num = frame.f_lineno

                    return module_name, func_name, line_num
        finally:
            # Always clear frame references to prevent reference cycles
            del frame

    return "unknown", "unknown", 0


def _str_to_bool(value):
    """
    Convert string to boolean value
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "on")
    return False


def _get_log_level(env_var_name, default_level=logging.INFO):
    """
    Get log level from environment variable
    """
    env_value = os.getenv(env_var_name, "").upper()
    if env_value and hasattr(logging, env_value):
        return getattr(logging, env_value)
    return default_level


class ColoredLogger:
    """
    Logger class that provides colored logging functionality with
    automatic module/function name detection and .env configuration
    """

    _initialized = False
    _instance = None

    def __init__(self):
        self.app_name = os.path.basename(sys.argv[0]).replace(".py", "")
        self._logger = None

    def _initialize(self, log_dir=None, log_file=None, log_level=logging.INFO, app_name=None):
        if ColoredLogger._initialized:
            return

        """
        Initialize the logger system with .env configuration
        """

        # Set app name if provided
        if app_name:
            self.app_name = app_name

        # Read configuration from .env file
        # 1. Log file path
        env_log_path = os.getenv("LOG_FILE_PATH")

        # 2. Enable/disable stdout logging
        enable_stdout = _str_to_bool(os.getenv("LOG_STDOUT_ENABLE", "true"))

        # 3. Enable/disable file logging
        enable_file = _str_to_bool(os.getenv("LOG_FILE_ENABLE", "true"))

        # 4. Log level for stdout
        stdout_log_level = _get_log_level("LOG_STDOUT_LEVEL", logging.INFO)

        # 5. Log level for file
        file_log_level = _get_log_level("LOG_FILE_LEVEL", logging.DEBUG)

        # Determine the minimum log level for the root logger
        min_log_level = logging.DEBUG
        if enable_stdout and enable_file:
            min_log_level = min(stdout_log_level, file_log_level)
        elif enable_stdout:
            min_log_level = stdout_log_level
        elif enable_file:
            min_log_level = file_log_level

        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(min_log_level)

        # Remove existing handlers to avoid duplicates
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        # Setup file logging if enabled
        if enable_file:
            if env_log_path:
                # Use the complete path from .env
                log_file_path = env_log_path
                # Create directory if it doesn't exist
                log_dir_path = os.path.dirname(log_file_path)
                os.makedirs(log_dir_path, exist_ok=True)
            else:
                # Use the provided or default path
                log_directory = log_dir or DEFAULT_LOG_DIR
                os.makedirs(log_directory, exist_ok=True)
                log_file_path = os.path.join(log_directory, log_file or DEFAULT_LOG_FILE)

            # Standard log format for file logs
            file_formatter = logging.Formatter(
                "[%(asctime)s] - [%(levelname)s]: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

            # File handler to write logs
            file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
            file_handler.setFormatter(file_formatter)
            file_handler.setLevel(file_log_level)
            root_logger.addHandler(file_handler)

        # Setup stdout logging if enabled
        if enable_stdout:
            # Colored log format for console
            color_formatter = colorlog.ColoredFormatter(
                "[%(cyan)s%(asctime)s%(reset)s] - [%(log_color)s%(levelname)s%(reset)s]: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
                log_colors={
                    "DEBUG": "white",
                    "INFO": "green",
                    "WARNING": "yellow",
                    "ERROR": "red",
                    "CRITICAL": "bold_red",
                },
                secondary_log_colors={},
                style="%",
            )

            # Console output with colors
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(color_formatter)
            console_handler.setLevel(stdout_log_level)
            root_logger.addHandler(console_handler)

        # Create main logger
        self._logger = logging.getLogger(self.app_name)
        self._logger.setLevel(logging.DEBUG)

        ColoredLogger._initialized = True

        # Log configuration information
        if self._logger:
            self._logger.debug(f"Logger initialized with following configuration:")
            self._logger.debug(f"  - Stdout logging: {enable_stdout} (level: {logging.getLevelName(stdout_log_level)})")
            self._logger.debug(
                f"  - File logging: {enable_file} (level: {logging.getLevelName(file_log_level)})"
            )  # if enable_file:  #     if env_log_path:  #         self._logger.debug(f"  - Log file path from .env: {log_file_path}")  #     else:  #         self._logger.debug(f"  - Log file path (default): {log_file_path}")

    # Logger configuration complete

    def setup(self, log_dir=None, log_file=None, log_level=logging.DEBUG, app_name=None):
        """
        Setup the logger with specified directory and file
        Configuration is primarily read from .env file, parameters serve as fallbacks

        Args:
            log_dir (str): Directory to store log files (fallback if LOG_FILE_PATH not set)
            log_file (str): Log file name (fallback if LOG_FILE_PATH not set)
            log_level (int): Logging level (deprecated, use LOG_LEVEL_STDOUT and LOG_LEVEL_FILE in .env)
            app_name (str): Application name (default: automatically derived from module name)

        Returns:
            self: For method chaining
        """
        self._initialize(log_dir, log_file, log_level, app_name)
        return self

    def get(self, name=None):
        """
        Get a logger with the specified name

        Args:
            name (str): Name for the logger (optional)

        Returns:
            A logger instance
        """
        if not ColoredLogger._initialized:
            self._initialize()

        if name:
            return logging.getLogger(f"{self.app_name}.{name}")
        return self._logger or logging.getLogger(self.app_name)

    # Custom logging methods that include caller information
    def debug(self, msg, *args, **kwargs):
        if not ColoredLogger._initialized:
            self._initialize()
        self.get().debug(f"{msg}", *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        if not ColoredLogger._initialized:
            self._initialize()
        self.get().info(f"{msg}", *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        if not ColoredLogger._initialized:
            self._initialize()
        self.get().warning(f"{msg}", *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        if not ColoredLogger._initialized:
            self._initialize()
        self.get().error(f"{msg}", *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        if not ColoredLogger._initialized:
            self._initialize()
        self.get().critical(f"{msg}", *args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        if not ColoredLogger._initialized:
            self._initialize()
        self.get().exception(f"{msg}", *args, **kwargs)


# Create a singleton instance
logger = ColoredLogger()
