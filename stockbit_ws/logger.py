"""Only explicitly selected metadata belongs in terminal logs."""

import logging
import sys


class SafeLogger:
    def __init__(self, debug=False, output=None):
        self.debug_enabled = bool(debug)
        self.output = output if output is not None else sys.stderr

    def lifecycle(self, message):
        print(message, file=self.output, flush=True)

    def debug(self, message):
        if self.debug_enabled:
            self.lifecycle(f"[debug] {message}")

    def error(self, message):
        self.lifecycle(f"Error: {message}")

    def binary(self, size):
        self.debug(f"← {size} B binary")


def private_transport_logger():
    # websockets DEBUG logs can contain full outgoing authentication frames.
    # An isolated, disabled logger prevents propagation even with root DEBUG.
    logger = logging.Logger("stockbit_ws.private_transport")
    logger.disabled = True
    logger.propagate = False
    logger.addHandler(logging.NullHandler())
    return logger
