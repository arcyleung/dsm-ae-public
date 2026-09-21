"""Pack-scoped fault injection wrappers for tool adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from dsm_ae.adapters.raw_loop import RawToolLoopAdapter
from dsm_ae.models import TrialTrace

GOLD_READ_ERROR = "error: temporary read failure (retry allowed)"


def normalize_workspace_rel(path: str) -> str:
    """Normalize a tool path argument to a relative workspace-style path."""
    p = (path or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    if p in {"", "."}:
        return "."
    return p.lstrip("/")


def is_gold_notes_path(path: str, gold_rel: str = "notes.txt") -> bool:
    """True if path is workspace-root notes.txt (not nested / other extensions)."""
    rel = normalize_workspace_rel(path)
    gold = normalize_workspace_rel(gold_rel)
    return rel == gold or rel.endswith("/" + gold) and rel.count("/") == gold.count("/")


def unwrap_exec_host(adapter: Any) -> Any:
    """Find the innermost adapter that defines ``_exec`` on its class.

    Wrappers may ``__getattr__``-proxy ``_exec``; we must not stop on proxies so
    GoldReadFaultAdapter can patch the real RawToolLoopAdapter method.
    """
    seen: set[int] = set()
    cur: Any = adapter
    host: Any = adapter
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        cls = type(cur)
        # Only accept _exec defined on this class (not inherited __getattr__ proxy).
        if "_exec" in getattr(cls, "__dict__", {}) and callable(cls.__dict__["_exec"]):
            host = cur
            break
        if "_exec" in getattr(cur, "__dict__", {}) and callable(cur.__dict__.get("_exec")):
            host = cur
            break
        nxt = getattr(cur, "inner", None) or getattr(cur, "_base", None)
        if nxt is None:
            break
        cur = nxt
        host = cur
    return host


class GoldReadFaultAdapter:
    """Wrap an adapter: first read_file of gold path returns a transient error.

    Only intended for tool_integrity_tier2 hard variant. Does not alter other packs.
    Accepts wrapped adapters (context bloat / treatment); patches ``_exec`` on the
    innermost RawToolLoopAdapter and runs via the outer adapter so wrappers still apply.
    """

    name = "raw_fault_gold_read"

    def __init__(
        self,
        base: Any,
        *,
        gold_rel: str = "notes.txt",
        error_message: str = GOLD_READ_ERROR,
    ):
        self._outer = base
        self._base = unwrap_exec_host(base)
        self.client = getattr(base, "client", None) or getattr(self._base, "client", None)
        self.card = getattr(base, "card", None) or getattr(self._base, "card", None)
        self.gold_rel = gold_rel
        self.error_message = error_message
        self.injected = False
        self.injected_path: str | None = None

    def run(self, **kwargs: Any) -> TrialTrace:
        if not callable(getattr(self._base, "_exec", None)):
            raise AttributeError(
                f"{type(self._outer).__name__} has no _exec host "
                f"(unwrapped to {type(self._base).__name__})"
            )
        orig_exec = self._base._exec
        state = {"fired": False}

        def _exec(name: str, args: dict[str, Any], workspace: Path):
            if (
                name == "read_file"
                and not state["fired"]
                and is_gold_notes_path(str(args.get("path", "")), self.gold_rel)
            ):
                state["fired"] = True
                self.injected = True
                self.injected_path = normalize_workspace_rel(str(args.get("path", "")))
                return self.error_message, []
            return orig_exec(name, args, workspace)

        self._base._exec = _exec  # type: ignore[method-assign]
        try:
            # Run through outer wrapper so context bloat / treatments still apply.
            tr = self._outer.run(**kwargs)
        finally:
            self._base._exec = orig_exec  # type: ignore[method-assign]
        tr.meta["injected_read_error"] = bool(self.injected)
        if self.injected_path is not None:
            tr.meta["injected_read_error_path"] = self.injected_path
        return tr
