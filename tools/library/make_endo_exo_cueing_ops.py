"""Make the stimuli of endo_exo_cueing_ops, the operational adaptation of endogenous vs exogenous cueing
(edge/library/tasks/endo_exo_cueing_ops/).

    python tools/library/make_endo_exo_cueing_ops.py

The same pictures as cueing_ops (see make_cueing_ops.py); copies the classic task's three trial lists unchanged
(blocks.csv, endogenous.csv, exogenous.csv).
"""

from __future__ import annotations

from make_cueing_ops import make

if __name__ == "__main__":
    make("endo_exo_cueing_ops", "endo_exo_cueing",
         {"blocks.csv": "blocks.csv", "endogenous.csv": "endogenous.csv", "exogenous.csv": "exogenous.csv"})
