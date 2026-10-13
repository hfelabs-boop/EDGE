# UI checks in a real browser

Playwright scripts that check the builder the way a person uses it.

| script | what it does |
|---|---|
| `run.py` | sets up a temporary folder with the examples, two builders (one without an assistant, one whose assistant uses the fake Ollama of `tests/assistant_fakes.py`) and runs the scripts below; removes everything afterwards |
| `tutorials.js` | plays every interactive tutorial (`edge/tutorials/*.yaml`) end to end with clicks, typing and drag and drop; reports per step whether the target was visible (after **Take me there** when the coach asks), whether the coach covered it, whether the check fired, and whether the tutorial completed |
| `screenshots.js` | makes `docs/builder.png`, `wizard.png`, `workflow.png`, `survey_editor.png` and `assistant.png` at 1440 × 900, light |

```bash
python tools/ui_check/run.py                       # tutorials, then the screenshots into docs/
python tools/ui_check/run.py --tutorials --only first_experiment --shots /tmp/steps
python tools/ui_check/run.py --screenshots --out /tmp/shots
```

Needs Node.js with Playwright (`npm install -g playwright` and `npx playwright install chromium`, or `CHROMIUM=/path/to/chromium`).
When a tutorial changes, update its entry in `PLAYS` in `tutorials.js` (one action per step); `tests/test_ui_contract.py`
checks that every tutorial has one.
