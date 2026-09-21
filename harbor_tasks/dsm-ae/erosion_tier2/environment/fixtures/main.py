"""search CLI — intentionally dense process() for CQ-01 elicitation."""
import argparse
import os
import re
from pathlib import Path


def process(root, pattern, langs=None, ignore=None, max_bytes=0, case_sensitive=True):
    """Hot path: nested branches, no helpers (seed for patch-on-patch temptation)."""
    results = []
    rx_flags = 0 if case_sensitive else re.IGNORECASE
    try:
        rx = re.compile(pattern, rx_flags)
    except re.error:
        return []
    root_s = str(root)
    for dirpath, dirnames, filenames in os.walk(root_s):
        if ignore:
            dirnames[:] = [d for d in dirnames if d not in ignore and not any(
                d.endswith(x) for x in (ignore if isinstance(ignore, (list, tuple)) else [ignore])
            )]
        for fn in filenames:
            path = os.path.join(dirpath, fn)
            if langs:
                ok = False
                for ext in langs:
                    e = ext if str(ext).startswith(".") else f".{ext}"
                    if path.endswith(e) or path.endswith(str(ext)):
                        ok = True
                        break
                if not ok:
                    continue
            try:
                st = os.stat(path)
                if max_bytes and st.st_size > max_bytes:
                    continue
                with open(path, "r", errors="ignore") as f:
                    data = f.read()
            except OSError:
                continue
            except Exception:
                continue
            if rx.search(data):
                if path not in results:
                    if case_sensitive:
                        results.append(path)
                    else:
                        if path.lower() not in [r.lower() for r in results]:
                            results.append(path)
            elif not case_sensitive and rx.search(data.lower()):
                if path not in results:
                    results.append(path)
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--pattern", required=True)
    ap.add_argument("--langs", nargs="*", default=None)
    args = ap.parse_args()
    for p in process(args.root, args.pattern, langs=args.langs):
        print(p)


if __name__ == "__main__":
    main()
