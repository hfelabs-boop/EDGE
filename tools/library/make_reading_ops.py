"""Make the stimuli and sentence lists of the three operational self-paced reading tasks
(edge/library/tasks/pacedreading1_ops, pacedreading2_ops, pacedreading3_ops).

    python tools/library/make_reading_ops.py

The same design as make_reading.py (the classic tasks): each item exists in two versions with the same words, a
subject-relative clause ("The patrol that relieved the convoy reached ...") and an object-relative clause ("The
patrol that the convoy relieved reached ..."). Each participant reads every item once, half in each version (which
half alternates with the participant number). The question is about the main clause and has the same answer in both
versions. Word positions (counting from 0): 'The'=0, embedded verb = 3 (subject) or 5 (object), main verb = 6 in
both, exactly as in the classic lists. The sentences are short fictional situation reports and orders: generic
vehicles, stations and teams, made-up checkpoints; no real units, places or operations.

Also copies the defence-kit pictures the tasks show into each task's stimuli/ folder.
"""

from __future__ import annotations

import csv

from kit_copy import TASKS, copy_from_kit

# head noun, embedded verb, embedded noun, rest of the main clause (starting with its verb), question, answer (y/n)
ITEMS = [
    ("patrol", "relieved", "convoy", "reached checkpoint BRAVO at dawn.", "Did the patrol reach the checkpoint?", "y"),
    ("tanker", "refuelled", "escort", "returned to base before noon.", "Did the escort return to base?", "n"),
    ("drone", "followed", "truck", "lost the signal near the bridge.", "Did the drone lose the signal?", "y"),
    ("tug", "towed", "barge", "entered the harbour after midnight.", "Did the barge enter the harbour?", "n"),
    ("helicopter", "guided", "ambulance", "landed in the field at sunset.", "Did the helicopter land in the field?", "y"),
    ("aircraft", "tracked", "drone", "reported a fault at 0400.", "Did the drone report a fault?", "n"),
    ("team", "contacted", "outpost", "requested more water and fuel.", "Did the team request water and fuel?", "y"),
    ("vehicle", "overtook", "column", "stopped at the river crossing.", "Did the column stop at the crossing?", "n"),
    ("station", "warned", "ship", "changed its watch plan twice.", "Did the station change its watch plan?", "y"),
    ("fighter", "escorted", "transport", "turned north over the coast.", "Did the transport turn north?", "n"),
    ("squad", "supported", "platoon", "crossed the ridge without delay.", "Did the squad cross the ridge?", "y"),
    ("crew", "called", "tower", "cancelled the second flight.", "Did the tower cancel the flight?", "n"),
    ("tower", "alerted", "station", "sent a weather report to all units.", "Did the tower send a weather report?", "y"),
    ("ship", "signalled", "ferry", "anchored outside the port.", "Did the ferry anchor outside the port?", "n"),
    ("operator", "briefed", "pilot", "updated the route at once.", "Did the operator update the route?", "y"),
    ("truck", "passed", "tractor", "blocked the road for an hour.", "Did the tractor block the road?", "n"),
    ("escort", "shadowed", "tanker", "switched off its lights at dusk.", "Did the escort switch off its lights?", "y"),
    ("team", "met", "convoy", "set up camp near the well.", "Did the convoy set up camp?", "n"),
    ("pilot", "called", "controller", "asked for a new heading.", "Did the pilot ask for a new heading?", "y"),
    ("tug", "pushed", "ferry", "left the dock at six.", "Did the ferry leave the dock?", "n"),
]

PRACTICE = [
    ("The station sent a weather report to all patrols.", "Was a weather report sent?", "y"),
    ("The convoy left the depot at first light.", "Did the convoy leave at night?", "n"),
]

TASK_IDS = ["pacedreading1_ops", "pacedreading2_ops", "pacedreading3_ops"]
FIELDS = ["item", "practice", "subject_version", "object_version", "question", "answer"]
KIT_FILES = ["backgrounds/map_grid_1280x720.jpg", "terrain/terrain_06_desert_dusk.jpg"]


def main() -> None:
    rows = []
    for i, (n1, v, n2, rest, q, a) in enumerate(ITEMS, 1):
        subj = f"The {n1} that {v} the {n2} {rest}"
        obj = f"The {n1} that the {n2} {v} {rest}"
        words_s, words_o = subj.split(), obj.split()
        assert words_s[3] == v and words_o[5] == v and words_s[6] == words_o[6] == rest.split()[0], subj
        rows.append({"item": i, "practice": 0, "subject_version": subj, "object_version": obj, "question": q, "answer": a})
    practice = [{"item": 100 + i, "practice": 1, "subject_version": s, "object_version": s, "question": q, "answer": a}
                for i, (s, q, a) in enumerate(PRACTICE, 1)]
    for task in TASK_IDS:
        copy_from_kit(task, KIT_FILES)
        for name, data in (("sentences.csv", rows), ("practice.csv", practice)):
            with open(TASKS / task / name, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
                w.writeheader()
                w.writerows(data)
    print("wrote the sentence lists and kit pictures of", ", ".join(TASK_IDS))


if __name__ == "__main__":
    main()
