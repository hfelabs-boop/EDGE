"""Make the stimuli of sart2_ops, the operational adaptation of the SART with feedback (edge/library/tasks/sart2_ops/).

    python tools/library/make_sart2_ops.py

The same pictures and the same kind of trial list as sart_ops (see make_sart_ops.py): copies the defence-kit files
into sart2_ops/stimuli/ and the classic sart2 trial list unchanged as sart2_ops.csv.
"""

from __future__ import annotations

from make_sart_ops import make

if __name__ == "__main__":
    make("sart2_ops", "sart2")
