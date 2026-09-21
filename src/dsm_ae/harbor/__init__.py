"""Harbor bridge for DSM-AE: pack export *and* trajectory ingestion.

Two directions, both named "Harbor":

**Out** (Task 1 + 1b + 4 + 5) — export DSM-AE indicator packs as Harbor tasks
and import their rewards back: `pack_bridge`, `run_layout`, `runner`,
`import_rewards`, `docker_cleanup`.

**In** (task layer of metric -> behaviour -> task) — ingest *foreign* Harbor /
EvalHub run bundles that carry an **external** outcome oracle (verifier
reward) which is not itself a DSM-AE gate, and score off-policy behaviour
instruments over them: `adapter`, `instruments`.

Bring-your-own-task: anything that emits an ATIF-style trajectory plus a
reward can be read by `load_run` and scored by `score_trajectory`.
"""

from .adapter import HarborTrial, iter_runs, load_run, scoreable_only
from .docker_cleanup import cleanup_docker_for_job
from .import_rewards import import_harbor_run, reward_dir_to_report
from .instruments import INSTRUMENTS, score_trajectory
from .pack_bridge import prepare_workspace, score_workspace, write_reward
from .run_layout import (
    finalize_meta,
    harbor_run_dir,
    init_run,
    persist_logs,
    persist_reward,
    persist_trajectory,
)
from .runner import run_harbor_task

__all__ = [
    "prepare_workspace",
    "score_workspace",
    "write_reward",
    # 1b
    "init_run",
    "persist_reward",
    "persist_trajectory",
    "persist_logs",
    "finalize_meta",
    "harbor_run_dir",
    "cleanup_docker_for_job",
    "run_harbor_task",
    # 5
    "reward_dir_to_report",
    "import_harbor_run",
    # trajectory ingestion (task layer)
    "HarborTrial",
    "load_run",
    "iter_runs",
    "scoreable_only",
    "score_trajectory",
    "INSTRUMENTS",
]
