import pytest

from edge.backends.headless import HeadlessBackend
from edge.engine import Runner
from edge.model import Experiment
from edge.runtime import Session


def make_exp(d, tmp_path=None):
    return Experiment.from_dict(d, base_dir=tmp_path)


def run_headless(exp_dict, tmp_path, script=None, vp=None, simulate=False, **backend_kw):
    """Run an experiment on the headless backend. ``script(backend)`` can schedule input up front."""
    exp = Experiment.from_dict(exp_dict, base_dir=tmp_path)
    be = HeadlessBackend(size=tuple(exp.settings["window"]["size"]), **backend_kw)
    if script:
        script(be)
    session = Session(exp, be, data_dir=tmp_path / "data", virtual_participant=vp, simulate_devices=simulate,
                      log=lambda *a: None)
    runner = Runner(session)
    summary = runner.run()
    return summary, session, be


@pytest.fixture
def run(tmp_path):
    def _run(d, **kw):
        return run_headless(d, tmp_path, **kw)
    return _run
