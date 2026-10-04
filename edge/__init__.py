"""EDGE — experiment builder and runtime for behavioral, eye-tracking, physiology and EEG research."""

__version__ = "0.1.0"

from .model import Experiment  # noqa: E402


def run(path_or_experiment, **kw):
    """Load (if needed) and run an experiment. See :func:`edge.engine.run_experiment`."""
    from .engine import run_experiment

    exp = path_or_experiment if isinstance(path_or_experiment, Experiment) else Experiment.load(path_or_experiment)
    return run_experiment(exp, **kw)


__all__ = ["Experiment", "run", "__version__"]
