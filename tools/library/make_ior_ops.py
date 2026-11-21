"""Make the stimuli of ior_ops, the operational adaptation of inhibition of return (edge/library/tasks/ior_ops/).

    python tools/library/make_ior_ops.py

The same pictures as cueing_ops (see make_cueing_ops.py) without the reticle; copies the classic task's trial list
unchanged.
"""

from __future__ import annotations

from make_cueing_ops import KIT_FILES, make

if __name__ == "__main__":
    # no reticle: the centre box marks the place to look at
    make("ior_ops", "ior", {"ior.csv": "ior_ops.csv"}, [f for f in KIT_FILES if not f.startswith("reticles/")])
