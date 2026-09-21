"""Docker cleanup for Harbor jobs.

Always removes containers (and optionally nets/vols) labeled with dsm-ae.harbor.job={job_id}.

- Idempotent
- Safe if docker CLI missing (record error, never raise unless asked)
- Used in finally blocks
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


LABEL_PREFIX = "dsm-ae.harbor"


def _docker(*args: str, **kwargs: Any) -> subprocess.CompletedProcess:
    """Internal: run docker CLI; overridable in tests via monkeypatch."""
    # capture both out/err always
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        timeout=kwargs.pop("timeout", 60),
    )


def cleanup_docker_for_job(
    job_id: str, *, label_prefix: str = LABEL_PREFIX, remove_volumes: bool = True, remove_networks: bool = False
) -> dict[str, Any]:
    """Remove all containers (and labeled volumes/nets) for the job.

    Labels used: {label_prefix}.job={job_id}

    Returns info dict with counts, errors if any.
    Never crashes the caller on docker absence or permission; records in returned dict.
    Safe to call multiple times (idempotent; second run finds nothing).
    """
    job_id = str(job_id)
    info: dict[str, Any] = {
        "job_id": job_id,
        "label": f"{label_prefix}.job={job_id}",
        "containers_removed": 0,
        "volumes_removed": 0,
        "networks_removed": 0,
        "errors": [],
        "docker_available": True,
    }

    label_filter = f"label={label_prefix}.job={job_id}"

    try:
        # 1. stop + rm containers (force)
        # list container ids
        res = _docker("ps", "-aq", "--filter", label_filter)
        if res.returncode != 0:
            if "docker" in (res.stderr or "").lower() or res.returncode == 127:
                info["docker_available"] = False
                info["errors"].append("docker cli not available or not running")
                return info
            info["errors"].append(f"ps: {res.stderr.strip()[:200]}")
        cids = [c.strip() for c in (res.stdout or "").splitlines() if c.strip()]
        if cids:
            # stop first (best effort)
            _docker("stop", "-t", "2", *cids, timeout=30)
            # rm -f
            rm_res = _docker("rm", "-f", *cids)
            if rm_res.returncode == 0:
                info["containers_removed"] = len(cids)
            else:
                info["errors"].append(f"rm containers: {rm_res.stderr.strip()[:200]}")
                # count anyway if some succeeded? for idempotency we can re-list or trust len
                info["containers_removed"] = len(cids)  # best effort; docker rm -f on gone is ok

        # 2. volumes if labeled (docker volume prune is global; instead list+rm specific)
        if remove_volumes:
            vres = _docker("volume", "ls", "-q", "--filter", label_filter)
            if vres.returncode == 0:
                vids = [v.strip() for v in (vres.stdout or "").splitlines() if v.strip()]
                if vids:
                    vr = _docker("volume", "rm", "-f", *vids)
                    if vr.returncode == 0:
                        info["volumes_removed"] = len(vids)
                    else:
                        info["errors"].append(f"volume rm: {vr.stderr.strip()[:200]}")

        # 3. networks (optional, as networks often not per-job labeled by default)
        if remove_networks:
            nres = _docker("network", "ls", "-q", "--filter", label_filter)
            if nres.returncode == 0:
                nids = [n.strip() for n in (nres.stdout or "").splitlines() if n.strip()]
                for nid in nids:
                    nr = _docker("network", "rm", nid)
                    if nr.returncode == 0:
                        info["networks_removed"] += 1
                    else:
                        info["errors"].append(f"network rm {nid}: {nr.stderr.strip()[:100]}")

    except FileNotFoundError as e:
        info["docker_available"] = False
        info["errors"].append(f"docker not found: {e}")
    except subprocess.TimeoutExpired as e:
        info["errors"].append(f"timeout: {e}")
    except Exception as e:
        info["errors"].append(f"unexpected: {type(e).__name__}: {e}")

    # summarize
    info["removed"] = (
        info["containers_removed"] + info["volumes_removed"] + info["networks_removed"]
    )
    if info["errors"]:
        info["had_errors"] = True
    return info
