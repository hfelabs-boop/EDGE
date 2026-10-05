# Surveys and questionnaires

The **survey** component builds professional questionnaire pages from structured questions: no
HTML needed. It has the question types you know from survey platforms (single and multiple choice,
Likert items and tables, sliders, rank order, constant sum, text with validation …), display logic,
randomization, piped text, page breaks and a progress bar. It also comes with a **library of
validated questionnaires** (PHQ-9, GAD-7, Big Five, SWLS, SUS, NASA-TLX …) that score themselves.
Every answer and every score becomes a column in the data, described in the data dictionary.

Surveys run inside the experiment, so they sit naturally next to tasks, eye tracking or EEG: a mood
rating after each block, a workload questionnaire after the task, consent and demographics before it.

![The survey editor](survey_editor.png)

## In the builder

1. Click **Survey / questionnaire** on the left. A survey fills the whole screen, so if the screen
   already has something on it, EDGE gives the survey its own screen right after it.
2. In Properties, **✎ Edit questions** opens the survey editor:
   * **left:** title, instructions and the questions in order (drag, or ↑, to reorder; ⧉ duplicates;
     × deletes). Page breaks show where pages start.
   * **middle:** the selected question: its text, data name, answer options or scale, *required*,
     shuffling, "other, please specify", limits, validation and **display logic** ("only if
     `gender` is `Woman`").
   * **right:** the real participant page, live. Click through it, answer it, press Submit to see
     exactly what would be saved.
3. **+ Question** adds any question type; **+ From library** adds a validated questionnaire.
4. **▶ Try it** shows the survey in place as participants will see it, and **▶ Test run** fills it in with
   a virtual participant so the data (and scores) appear in the Test results.

The design wizard (**New → answer a few questions**, last page) can add questionnaires for you:
consent and demographics before the task, the others after it.

## Question types

| type | what participants see | saved as |
|---|---|---|
| `text_block` | text or HTML (instructions, a section heading, an image) | nothing |
| `single` | radio buttons, one answer; `layout: horizontal`; `other_option` adds a text box | the option's value (`<id>_other` for the typed text) |
| `dropdown` | a drop-down list | the option's value |
| `multiple` | checkboxes; `min_choices`, `max_choices`, `exclusive: [None of these]` | `a; b` plus one 0/1 column per option (`<id>_<option>`) |
| `likert` | one statement on a scale (`scale: agree5` …) | the value (e.g. 1-5) |
| `matrix` | several statements (`items`) on the same scale, as a table; items can be `reverse: true` | one column per item |
| `semantic` | bipolar items (`left`/`right` words) on an N-point scale | one column per item |
| `scale` | numbers 1..N (`points`) with end `labels` | the number |
| `nps` | 0-10 recommend scale | the number |
| `slider` | a visual analogue scale (`min`, `max`, `step`, end `labels`); must be moved to count as answered | the number |
| `text` | one line; `validate: email \| number \| integer`, `pattern` (regular expression), `max_length` | the text |
| `essay` | a text area; `rows`, `min_length`, `max_length` (with a live character count) | the text |
| `number` | a number; `min`, `max`, `step` | the number |
| `date` | a date picker | `YYYY-MM-DD` |
| `rank` | put options in order by dragging or with ↑/↓ | `a > b > c` plus the rank of each option (`<id>_<option>`) |
| `constant_sum` | share a `total` (default 100) across options; must add up | one column per option |
| `page_break` | starts a new page | `pageN_time` per page |

Options can be plain text (saved as written) or `{value: 1, label: Strongly disagree}` (the value is
saved). In the editor, write `1 = Strongly disagree` on a line to keep a number code.

**Answer scales** (`scale:` on single, likert and matrix): `agree5`, `agree7`, `agree4` and `agree6`
(no middle point), `frequency5`, `satisfaction5`, `likelihood5`, `importance5`, `quality5`, `extent5`,
`accuracy5`, `confidence5`, `difficulty5`, `yesno`, `yesnounsure`, `truefalse`. All are listed in the
[questionnaire reference](reference/questionnaires.md#answer-scales).

## In the experiment file

```yaml
routines:
  questions:
    components:
      - id: about
        type: survey
        end_routine: true
        title: A few questions about you
        intro: There are no right or wrong answers.
        questions:
          - {instrument: demographics}
          - type: page_break
          - {id: sleep, type: number, text: "How many hours did you sleep last night?", min: 0, max: 24, required: true}
          - id: caffeine
            type: single
            text: Did you have caffeine today?
            options: [Yes, No]
            layout: horizontal
          - id: cups
            type: slider
            text: How many cups?
            min: 0
            max: 10
            labels: [none, ten or more]
            show_if: {caffeine: "Yes"}
          - id: mood
            type: matrix
            scale: agree5
            text: Right now I feel …
            items:
              - {id: mood_calm, text: calm}
              - {id: mood_tense, text: tense, reverse: true}
          - {instrument: phq9}
        scores:
          mood_score: {items: [mood_calm, mood_tense], method: mean, description: "Calm mood (1-5)"}
```

Data from this page: `about.age`, `about.gender` … `about.sleep`, `about.caffeine`, `about.cups`
(empty when caffeine was "No"), `about.mood_calm`, `about.mood_tense`, `about.phq9_1` … `about.phq9_9`,
`about.phq9_total`, `about.phq9_total_band`, `about.phq9_item9_flag`, `about.mood_score`,
`about.page1_time`, `about.page2_time` and `about.rt` (seconds until Submit).

### Survey properties

| property | default | what it does |
|---|---|---|
| `questions` | | the questions in order (required) |
| `title`, `intro` | | heading and instructions on the first page (HTML allowed) |
| `progress_bar` | `true` | a progress bar across pages |
| `allow_back` | `true` | a Back button (answers are kept when going back and forth) |
| `next_label`, `back_label`, `submit_label` | Next / Back / Submit | button texts |
| `labels` | | translate the messages, e.g. `{required: "Bitte beantworten Sie diese Frage."}` |
| `scores` | | your own scores (below) |
| `css` | | extra CSS for the page |
| `display`, `fullscreen` | auto / true | as for HTML pages: a pywebview window if installed, otherwise the browser |

### Display logic

`show_if` shows a question only when earlier answers match. Hidden questions aren't required and
are saved as empty.

| condition | meaning |
|---|---|
| `{gender: Woman}` | the answer is Woman |
| `{country: [UK, Ireland]}` | one of these |
| `{age: {">=": 18}}` | comparisons: `=`, `!=`, `>`, `>=`, `<`, `<=` |
| `{hobbies: {contains: Music}}` | a checkbox question includes Music |
| `{email: {answered: true}}` | was answered at all |
| `{consent: yes, age: {">=": 18}}` | all of these |
| `{any: [{a: 1}, {b: 1}]}` | at least one of these |

For whole screens or blocks (e.g. *skip the study if consent is declined*), use a workflow with a route
like `if: "$consent_form.consent == 'yes'"`; see the *online questionnaire* example.

### Piped text and trial values

`{{answer.<id>}}` in a question shows an earlier answer (the option's label), updated live:
*"How many minutes per week do you spend on {{answer.exercise_types}}?"*. `{{column}}` shows a
trial-list value or variable, so the same survey can rate each stimulus inside a loop:
*"How pleasant was {{picture}}?"*.

### Randomization

`randomize: true` shuffles the options of a choice, rank or constant-sum question, or the statements
of a matrix. "Other" and exclusive options stay at the end. The order each participant saw is saved
as `<id>_order`, and it is reproducible from the session's seed.

### Scores

Library questionnaires score themselves. Define your own with `scores`:

| key | meaning |
|---|---|
| `items` | the item or question ids to combine |
| `method` | `sum` (all items needed), `mean` (with `min_answered`), `flag` (1 if any item ≥ `threshold`), `correct` (count of questions answered with their `correct` value) |
| `reverse` | ids to reverse-score (also `reverse: true` on matrix items); uses the scale's own minimum and maximum |
| `multiply`, `add` | rescale (e.g. WHO-5 × 4, SUS × 2.5) |
| `missing_as` | count unanswered items as this value instead of leaving the score empty |
| `bands` | `[[max, label], …]`: adds `<score>_band` with the label of the first band the score falls in |
| `description` | shown in the data dictionary |

### Attention and knowledge checks

Give a question a `correct` answer and count them with a `correct` score. The library's
`attention_checks` block has two instructed-response items and `attention_passed` (0-2). Decide your
exclusion rule before collecting data (pre-register it).

## The questionnaire library

All of these are free to use for research. The [questionnaire reference](reference/questionnaires.md)
lists every item, answer, score and citation.

| | |
|---|---|
| **Study logistics** | `consent` (with a workflow route for "I do not agree"), `demographics`, `attention_checks`, `debrief` (funnel debriefing) |
| **Mental health** | `phq9` (depression), `gad7` (anxiety), `k6` (distress), `pss10` (perceived stress) |
| **Well-being and self** | `who5`, `swls` (life satisfaction), `rses` (Rosenberg self-esteem) |
| **Personality** | `tipi` and `mini_ipip` (Big Five), `ehi_sf` (handedness) |
| **Task experience** | `nasa_tlx` (workload), `kss` (sleepiness), `affect_grid` (valence and arousal, SAM-style), `sus` (usability), `nps` |
| **Health behaviour** | `audit_c` (alcohol) |

Copyrighted or commercially sold instruments (BDI-II, STAI, PANAS, NEO-PI, MMPI …) are not included;
you can build them yourself with a licence. **Check wording and licence against the original before
you collect data**, and use validated translations for other languages.

The PHQ-9 asks about thoughts of self-harm (item 9). The data flags a positive answer as
`phq9_item9_flag`; have a safety protocol approved by your ethics committee before using it.

### Customizing a library questionnaire

In the editor, **Customize (copy the items here)** replaces the library entry with its questions and
keeps its scores, so you can change the wording, drop an item or add your own. Edited wording is no
longer the validated version: report what you changed.

## With Claude (MCP)

> *"Add consent and demographics before the task, and PHQ-9 and GAD-7 after it, with an attention check
> between them."*

The MCP server has `survey_library` (question types, scales, questionnaires) and `add_survey` (a
questionnaire screen at the start, the end, or after a given screen). See [MCP](MCP.md).

## Tips

* One survey per screen. Use page breaks rather than many screens, so participants can go back.
* Prefer `matrix` for questionnaires with a shared scale: one column per item, faster to answer.
* Keep `required` for items your analysis needs; forced responses on sensitive questions should offer
  "Prefer not to say".
* For responses in time-critical tasks use components (key press, rating scale) instead: surveys are
  HTML pages, accurate to the browser's timing, not to the screen refresh.
