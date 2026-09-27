"""The ``keeptabs`` command: one sub-command per function in :data:`keeptabs.tools.TOOLS`."""

import json
import sys

import cw

from keeptabs import tools
from keeptabs.engine import AlreadyRunning
from keeptabs.spec import SpecError

#: What a user can cause, and fix: shown as one line, with no traceback.
USER_ERRORS = (SpecError, AlreadyRunning, KeyError, ValueError, FileNotFoundError)


def _guarded(tool):
    """The tool, returning a failed result where it would raise a user error."""
    import functools

    @functools.wraps(tool)
    def guarded(*args, **kwargs):
        try:
            return tool(*args, **kwargs)
        except USER_ERRORS as error:
            message = (
                error.args[0] if isinstance(error, KeyError) and error.args else error
            )
            return {
                "ok": False,
                "error": type(error).__name__,
                "text": f"keeptabs: {message}",
            }

    return guarded


def _egress(as_json):
    def egress(result, *, out, err):
        failed = isinstance(result, dict) and not result.get("ok", True)
        if (
            not as_json
            and isinstance(result, dict)
            and isinstance(result.get("text"), str)
        ):
            print(result["text"], file=err if failed and "error" in result else out)
        else:
            print(
                json.dumps(result, indent=2, ensure_ascii=False, default=str), file=out
            )
        return 0 if not isinstance(result, dict) or result.get("ok", True) else 1

    return egress


def main(argv=None):
    """Run one ``keeptabs`` command. ``--json`` prints the full result as JSON."""
    for stream in (
        sys.stdout,
        sys.stderr,
    ):  # a cp1252 console must not crash on a title
        getattr(stream, "reconfigure", lambda **_: None)(errors="backslashreplace")
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    commands = {tool.__name__.replace("_", "-"): _guarded(tool) for tool in tools.TOOLS}
    raise SystemExit(
        cw.dispatch(
            commands,
            [a for a in argv if a != "--json"],
            prog="keeptabs",
            convention=cw.MODERN,
            egress=_egress(as_json),
        )
    )


if __name__ == "__main__":
    main()
