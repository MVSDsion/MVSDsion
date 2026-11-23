"""Keep MVSDsion running when a Python error happens inside a Qt signal.

Without a custom ``sys.excepthook`` PySide6 aborts the whole process on any
unhandled exception in a slot (Windows reports 0xc0000409 in Qt6Core.dll and
nothing reaches the log). With this hook the error is written to the log and
to ``logs/crash.log`` and the app keeps running. Native crashes are written to
``logs/crash.log`` by faulthandler.
"""

from __future__ import annotations

import faulthandler
import sys
import threading
import traceback
from datetime import datetime
from typing import TYPE_CHECKING

from ..utils.logging import log_buffer
from ..utils.paths import LOGS_DIR

if TYPE_CHECKING:
    from types import TracebackType

_native_log = None


def _write(text: str) -> None:
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with (LOGS_DIR / 'crash.log').open('a', encoding='utf-8') as handle:
            handle.write(f'\n[{datetime.now():%Y-%m-%d %H:%M:%S}]\n{text}\n')
    except OSError:
        pass


def _report(kind: str, exc_type: type[BaseException], value: BaseException, tb: TracebackType | None) -> None:
    text = ''.join(traceback.format_exception(exc_type, value, tb))
    log_buffer.log('Error', f'{kind}: {exc_type.__name__}: {value}')
    _write(f'{kind}\n{text}')


def install() -> None:
    global _native_log  # noqa: PLW0603
    sys.excepthook = lambda t, v, tb: _report('Unhandled error', t, v, tb)
    threading.excepthook = lambda args: _report(
        f'Unhandled error in thread {args.thread.name if args.thread else "?"}',
        args.exc_type,
        args.exc_value or args.exc_type(),
        args.exc_traceback,
    )
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        _native_log = (LOGS_DIR / 'crash.log').open('a', encoding='utf-8')  # noqa: SIM115
        faulthandler.enable(file=_native_log, all_threads=True)
    except OSError:
        pass
