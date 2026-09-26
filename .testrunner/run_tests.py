"""Tiny test runner for environments without pytest.

Discovers ``test_*`` functions in the ``tests`` package and provides the
fixtures the suite uses: ``tmp_path``, ``capsys`` and any fixture defined in
``tests.conftest`` (e.g. ``live_server``).
"""

from __future__ import annotations

import contextlib
import importlib
import inspect
import io
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Callable, Iterator


class CapSys:
    def __init__(self) -> None:
        self._out = io.StringIO()
        self._err = io.StringIO()
        self._stdout = contextlib.redirect_stdout(self._out)
        self._stderr = contextlib.redirect_stderr(self._err)

    def start(self) -> None:
        self._stdout.__enter__()
        self._stderr.__enter__()

    def stop(self) -> None:
        self._stdout.__exit__(None, None, None)
        self._stderr.__exit__(None, None, None)

    def readouterr(self) -> Any:
        class Result:
            def __init__(self, out: str, err: str) -> None:
                self.out = out
                self.err = err

        out, err = self._out.getvalue(), self._err.getvalue()
        self._out.seek(0)
        self._out.truncate(0)
        self._err.seek(0)
        self._err.truncate(0)
        return Result(out, err)


def _conftest_fixtures() -> dict[str, Callable[..., Any]]:
    module = importlib.import_module("tests.conftest")
    found: dict[str, Callable[..., Any]] = {}
    for name in dir(module):
        target = getattr(module, name)
        label = getattr(target, "__pytest_fixture_name__", None)
        if label:
            found[label] = target
    return found


def _run_one(func: Callable[..., Any], fixtures: dict[str, Callable[..., Any]]) -> None:
    signature = inspect.signature(func)
    kwargs: dict[str, Any] = {}
    finalizers: list[Callable[[], None]] = []
    capsys: CapSys | None = None
    with tempfile.TemporaryDirectory() as tmp:
        for parameter in signature.parameters.values():
            name = parameter.name
            if name == "tmp_path":
                kwargs[name] = Path(tmp)
            elif name == "capsys":
                capsys = CapSys()
                kwargs[name] = capsys
            elif name == "monkeypatch":
                import pytest

                patcher = pytest.MonkeyPatch()
                kwargs[name] = patcher
                finalizers.append(patcher.undo)
            elif name in fixtures:
                provider = fixtures[name]
                gen = provider(**{"tmp_path": Path(tmp)} if "tmp_path" in inspect.signature(provider).parameters else {})
                if isinstance(gen, Iterator) or inspect.isgenerator(gen):
                    kwargs[name] = next(gen)
                    finalizers.append(lambda g=gen: next(g, None))
                else:
                    kwargs[name] = gen
            else:
                raise RuntimeError(f"no fixture for parameter {name!r}")
        if capsys is not None:
            capsys.start()
        try:
            func(**kwargs)
        finally:
            if capsys is not None:
                capsys.stop()
            for finalize in reversed(finalizers):
                with contextlib.suppress(StopIteration, Exception):
                    finalize()


def main() -> int:
    fixtures = _conftest_fixtures()
    passed = 0
    failed: list[tuple[str, BaseException, str]] = []
    modules = [
        "tests.test_api_surface",
        "tests.test_cli_and_scenarios",
        "tests.test_clock_and_config",
        "tests.test_console",
        "tests.test_decisions",
        "tests.test_instrumentation",
        "tests.test_interlocks",
        "tests.test_limits",
        "tests.test_record_stream",
        "tests.test_restart_and_serve",
        "tests.test_sections",
        "tests.test_store_and_audit",
        "tests.test_versioning",
    ]
    for module_name in modules:
        module = importlib.import_module(module_name)
        for name in sorted(dir(module)):
            if not name.startswith("test_"):
                continue
            target = getattr(module, name)
            if not callable(target):
                continue
            label = f"{module_name}::{name}"
            try:
                _run_one(target, fixtures)
            except BaseException as exc:  # noqa: BLE001 - report every failure
                failed.append((label, exc, traceback.format_exc()))
                print(f"FAIL {label}: {exc.__class__.__name__}: {exc}")
            else:
                passed += 1
    print(f"\n{passed} passed, {len(failed)} failed")
    if failed:
        for label, exc, tb in failed:
            print(f"\n{'=' * 70}\n{label}\n{'=' * 70}\n{tb}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
