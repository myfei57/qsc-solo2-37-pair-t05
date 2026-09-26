"""Minimal stand-in for the pytest surface used by this repository's tests.

Only implements what the local test-suite imports: ``raises``, ``fixture``
and the ``CaptureFixture`` annotation. The companion ``run_tests.py`` module
discovers and executes the test functions.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any, Callable, Generic, TypeVar

E = TypeVar("E", bound=BaseException)


class RaisesContext(Generic[E]):
    def __init__(self, expected: type[E]) -> None:
        self.expected = expected
        self.value: E | None = None

    def __enter__(self) -> "RaisesContext[E]":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if exc_type is None:
            raise AssertionError(f"expected {self.expected.__name__} to be raised")
        if not issubclass(exc_type, self.expected):
            return False
        self.value = exc  # type: ignore[assignment]
        return True


def raises(expected: type[E]) -> RaisesContext[E]:
    return RaisesContext(expected)


def fixture(func: Callable[..., Any] | None = None, *, name: str | None = None, **_: Any) -> Any:
    def decorate(target: Callable[..., Any]) -> Callable[..., Any]:
        target.__pytest_fixture_name__ = name or target.__name__  # type: ignore[attr-defined]
        return target

    if func is not None:
        return decorate(func)
    return decorate


class CaptureFixture:
    """Annotation placeholder; the real capture is provided by the runner."""

    def __class_getitem__(cls, item: Any) -> "type[CaptureFixture]":
        return cls


class _Mark:
    def __getattr__(self, name: str) -> Callable[..., Any]:
        def decorator(*args: Any, **kwargs: Any) -> Any:
            if args and callable(args[0]) and len(args) == 1 and not kwargs:
                return args[0]
            return lambda target: target

        return decorator


mark = _Mark()


class Approx:
    def __init__(self, expected: float, rel: float = 1e-6, abs: float = 1e-12) -> None:
        self.expected = expected
        self.rel = rel
        self.abs = abs

    def __eq__(self, other: object) -> bool:
        try:
            return abs(float(other) - self.expected) <= max(self.rel * abs(self.expected), self.abs)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False

    def __repr__(self) -> str:
        return f"approx({self.expected!r})"


def approx(expected: float, rel: float = 1e-6, abs: float = 1e-12) -> Approx:
    return Approx(expected, rel=rel, abs=abs)


class MonkeyPatch:
    def __init__(self) -> None:
        self._undo: list[Callable[[], None]] = []

    def setattr(self, target: Any, name: str | Any = None, value: Any = None) -> None:
        if isinstance(target, str):
            module_name, attr = target.rsplit(".", 1)
            import importlib

            holder: Any = importlib.import_module(module_name)
            name, value = attr, name
        else:
            holder = target
        original = getattr(holder, name)
        self._undo.append(lambda: setattr(holder, name, original))
        setattr(holder, name, value)

    def undo(self) -> None:
        for revert in reversed(self._undo):
            revert()
        self._undo.clear()
