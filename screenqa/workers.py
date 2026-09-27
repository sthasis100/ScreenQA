"""
workers.py - runs slow jobs in the background so the window never freezes (Step 9).

Why this is needed:
  Qt draws the window and reacts to clicks on ONE thread, the "main thread".
  If slow work (OCR, AI requests) ran there, the window would freeze and
  Windows would show "Not responding". So slow work goes to a pool of
  background threads instead.

The one big rule:
  Background code must NEVER touch widgets (buttons, text boxes...) directly.
  It reports back with signals, and Qt delivers each signal safely on the
  main thread, where it is fine to update the window.

Job IDs:
  Every job carries a number. If you capture twice quickly, the first OCR job
  may finish AFTER the second one started. The window compares the number
  with the newest job and ignores results that are out of date.
"""

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

log = logging.getLogger(__name__)


class WorkerSignals(QObject):
    """The signals a Worker sends back. (QRunnable itself cannot have signals.)"""

    succeeded = Signal(int, object)  # (job id, the function's return value)
    failed = Signal(int, object)  # (job id, the exception that was raised)


class Worker(QRunnable):
    """Runs one function call on a background thread."""

    def __init__(self, job_id: int, function: Callable, *args, **kwargs) -> None:
        super().__init__()
        self.job_id = job_id
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    def run(self) -> None:
        """Qt calls this ON THE BACKGROUND THREAD."""
        try:
            result = self.function(*self.args, **self.kwargs)
        except Exception as error:  # report every failure instead of dying silently
            log.warning("Background job %d (%s) failed: %s", self.job_id, self.function.__name__, error)
            self._report(self.signals.failed, error)
        else:  # "else" runs only when there was no exception
            self._report(self.signals.succeeded, result)

    def _report(self, signal, value) -> None:
        try:
            signal.emit(self.job_id, value)
        except RuntimeError:
            # ScreenQA was closed while this job was still running, so the
            # window it should report to no longer exists. Nothing to do.
            log.info("Background job %d finished after ScreenQA closed; result discarded", self.job_id)


def run_in_background(
    job_id: int,
    function: Callable,
    *args,
    on_success: Callable,
    on_failure: Callable,
    **kwargs,
) -> None:
    """Run function(*args, **kwargs) in the background.

    on_success(job_id, result) or on_failure(job_id, error) is called on the
    main thread afterwards. Pass METHODS of a window (not lambdas) so Qt knows
    which thread they belong to.
    """
    worker = Worker(job_id, function, *args, **kwargs)
    worker.signals.succeeded.connect(on_success)
    worker.signals.failed.connect(on_failure)
    QThreadPool.globalInstance().start(worker)  # a free background thread picks it up
