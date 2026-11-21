"""Write the sentence lists of the three self-paced reading tasks (pacedreading1, 2 and 3) (re-runnable).

Each item exists in two versions with the same words: a subject-relative clause ("The lawyer who called the
banker left ...") and an object-relative clause ("The lawyer who the banker called left ..."). Each participant
reads every item once, half in each version (which half alternates with the participant number), so every
item is read in both versions across participants. The question is about the main clause and has the same
answer in both versions. Word positions (counting from 0): 'The'=0, embedded verb = 3 (subject) or 5 (object),
main verb = 6 in both.

Change the items below and run  python tools/library/make_reading.py  to rewrite the lists.
"""

from __future__ import annotations

import csv
from pathlib import Path

# head noun, embedded verb, embedded noun, rest of the main clause (starting with its verb), question, answer (y/n)
ITEMS = [
    ("lawyer", "called", "banker", "left the office early.", "Did the lawyer leave early?", "y"),
    ("pilot", "greeted", "mechanic", "boarded the plane at noon.", "Did the mechanic board the plane?", "n"),
    ("teacher", "praised", "student", "smiled at the whole class.", "Did the teacher smile at the class?", "y"),
    ("doctor", "visited", "nurse", "ordered a new test.", "Did the nurse order a new test?", "n"),
    ("singer", "admired", "dancer", "won the first prize.", "Did the singer win a prize?", "y"),
    ("farmer", "helped", "neighbour", "sold the old tractor.", "Did the neighbour sell the tractor?", "n"),
    ("chef", "hired", "waiter", "opened a second restaurant.", "Did the chef open a restaurant?", "y"),
    ("coach", "thanked", "player", "missed the morning bus.", "Did the player miss the bus?", "n"),
    ("author", "met", "editor", "finished the book in May.", "Did the author finish the book?", "y"),
    ("guard", "stopped", "driver", "closed the main gate.", "Did the driver close the gate?", "n"),
    ("artist", "painted", "model", "moved to a small village.", "Did the artist move to a village?", "y"),
    ("clerk", "phoned", "manager", "lost the important letter.", "Did the manager lose the letter?", "n"),
    ("nurse", "trusted", "surgeon", "worked through the night.", "Did the nurse work through the night?", "y"),
    ("student", "interviewed", "professor", "forgot the meeting time.", "Did the professor forget the meeting?", "n"),
    ("baker", "supplied", "grocer", "raised the price of bread.", "Did the baker raise the price?", "y"),
    ("captain", "warned", "sailor", "checked the ropes twice.", "Did the sailor check the ropes?", "n"),
    ("actor", "imitated", "comedian", "told a funny story.", "Did the actor tell a story?", "y"),
    ("tenant", "sued", "landlord", "painted the front door.", "Did the landlord paint the door?", "n"),
    ("scientist", "advised", "engineer", "built a faster engine.", "Did the scientist build an engine?", "y"),
    ("mayor", "criticised", "journalist", "resigned last week.", "Did the journalist resign?", "n"),
]

PRACTICE = [
    ("The children played in the park after school.", "Did the children play in the park?", "y"),
    ("My uncle bought a red car last summer.", "Was the car blue?", "n"),
]

TASKS = ["pacedreading1", "pacedreading2", "pacedreading3"]
ROOT = Path(__file__).resolve().parents[2] / "edge" / "library" / "tasks"
FIELDS = ["item", "practice", "subject_version", "object_version", "question", "answer"]


def main() -> None:
    rows = []
    for i, (n1, v, n2, rest, q, a) in enumerate(ITEMS, 1):
        rows.append({"item": i, "practice": 0,
                     "subject_version": f"The {n1} who {v} the {n2} {rest}",
                     "object_version": f"The {n1} who the {n2} {v} {rest}",
                     "question": q, "answer": a})
    practice = [{"item": 100 + i, "practice": 1, "subject_version": s, "object_version": s, "question": q, "answer": a}
                for i, (s, q, a) in enumerate(PRACTICE, 1)]
    for task in TASKS:
        for name, data in (("sentences.csv", rows), ("practice.csv", practice)):
            with open(ROOT / task / name, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS)
                w.writeheader()
                w.writerows(data)
    print("wrote the sentence lists of", ", ".join(TASKS))


if __name__ == "__main__":
    main()
