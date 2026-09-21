"""The vendored atom mapper must agree with the real one.

`scripts/denovoswe_external_validation.py` runs on the DGX, which holds the
29 GB DeNovoSWE corpus but does not have `dsm_ae` installed. It therefore falls
back to an inlined copy of the atom mapping. A silent drift between the two
would make the external-validation numbers incomparable with every other figure
in the repo, so pin them together here.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

from dsm_ae.atoms import atom_from_tool as real_atom

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "denovoswe_external_validation.py"


def _load_vendored():
    """Import the script with `dsm_ae` hidden, forcing the fallback branch."""
    spec = importlib.util.spec_from_file_location("_dnv_vendored", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    saved = {k: v for k, v in sys.modules.items() if k.startswith("dsm_ae")}
    for k in list(saved):
        del sys.modules[k]
    sys.modules["dsm_ae"] = None  # make `import dsm_ae.atoms` raise ModuleNotFoundError
    try:
        spec.loader.exec_module(mod)
    finally:
        del sys.modules["dsm_ae"]
        sys.modules.update(saved)
    return mod


# (tool name, arguments) pairs covering every branch the corpus exercises.
CASES = [
    ("str_replace_editor", {"command": "view", "path": "/workspace/a.py"}),
    ("str_replace_editor", {"command": "create", "path": "/workspace/a.py"}),
    ("str_replace_editor", {"command": "str_replace", "path": "/workspace/a.py"}),
    ("file_editor", {"command": "view", "path": "x.py"}),
    ("execute_bash", {"command": "cd /w && pytest -q"}),
    ("execute_bash", {"command": "cd /w && python3 -c \"assert 1\""}),
    ("execute_bash", {"command": "ls -la"}),
    ("execute_bash", {"command": "cat README.md"}),
    ("execute_bash", {"command": "rm -rf build"}),
    ("terminal", {"command": "go test ./..."}),
    ("read_file", {"path": "a.py"}),
    ("edit", {"path": "a.py"}),
    ("grep", {"pattern": "foo"}),
    ("finish", {}),
    ("think", {}),
    ("totally_unknown_tool", {}),
]


@pytest.mark.parametrize("name,args", CASES)
def test_vendored_matches_real(name, args):
    vend = _load_vendored()
    assert vend.atom_from_tool(name, args) == real_atom(name, args), (
        f"vendored mapper disagrees for {name} {args}"
    )


def test_vendored_regexes_match_real():
    from dsm_ae.atoms import _ADHOC_VERIFY_RE as real_adhoc
    from dsm_ae.atoms import _TEST_RE as real_test

    vend = _load_vendored()
    assert vend._TEST_RE.pattern == real_test.pattern
    assert vend._ADHOC_VERIFY_RE.pattern == real_adhoc.pattern


def test_adhoc_verify_catches_the_denovoswe_style():
    """The corpus verifies with `python3 -c "... assert ..."`, not pytest."""
    from dsm_ae.atoms import _ADHOC_VERIFY_RE, _TEST_RE

    cmd = 'cd /workspace/addict && python3 -c "\nfrom addict import Dict\nassert Dict()"'
    assert not _TEST_RE.search(cmd), "formal runner regex should not match this"
    assert _ADHOC_VERIFY_RE.search(cmd), "ad-hoc verification must be detected"
