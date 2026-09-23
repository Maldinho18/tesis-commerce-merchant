from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


def bootstrap_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "railway_bootstrap.py"
    spec = spec_from_file_location("railway_bootstrap", script)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bootstrap_uses_only_the_single_preparation_episode() -> None:
    single_p0_run = bootstrap_module()._single_p0_run
    episode = ("run-one", "synthetic-actor")
    assert single_p0_run([]) is None
    assert single_p0_run([episode]) == episode
    with pytest.raises(RuntimeError, match="more than one P0"):
        single_p0_run([episode, ("run-two", "other-actor")])
