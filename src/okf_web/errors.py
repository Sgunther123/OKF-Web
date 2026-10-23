"""One family for every error the toolchain raises on purpose, and the
exit code each kind earns (review 2026-10-21, A-U1).

Fifteen exception classes used to sit on five stdlib bases, and
``okf-web``'s ``main`` mapped them from a hand-kept tuple while single
commands mapped a few more; the same class could exit 1 in one command
and 2 in another, and one was never mapped at all. Every class now
inherits one of two markers, and ``main`` has one ``except``:

* :class:`Refusal` — the command **refused to act** (exit 2): input it
  will not accept — a missing bundle, a held lock, an unsafe
  destination, an unfit question set, a stale concept approved without
  a date, a host the fetch boundary will not touch.
* :class:`Failure` — the command **acted and the outcome failed**
  (exit 1): nothing to publish, a signing tool that errored.

The stdlib bases stay (a ``BundleNotFound`` is still a
``FileNotFoundError``), so library callers catching those keep
working; the markers add the one base and the one code.
"""

from __future__ import annotations

__all__ = ["OkfWebError", "Refusal", "Failure", "EXIT_REFUSAL", "EXIT_FAILURE",
           "exit_code"]

EXIT_FAILURE = 1
EXIT_REFUSAL = 2


class OkfWebError(Exception):
    """Base of every error okf-web raises on purpose."""


class Refusal(OkfWebError):
    """The command refused to act: exit 2."""


class Failure(OkfWebError):
    """The command acted and the outcome failed: exit 1."""


def exit_code(exc: BaseException) -> int:
    """The CLI exit code for an :class:`OkfWebError`. A class that is
    both (``UnsafeDist`` is a refused ``PublishError``) is a refusal:
    the more specific verdict wins."""
    if isinstance(exc, Refusal):
        return EXIT_REFUSAL
    if isinstance(exc, Failure):
        return EXIT_FAILURE
    raise TypeError(f"{type(exc).__name__} is not an okf-web error")
