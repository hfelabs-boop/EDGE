# Tutorials

Hands-on lessons. Each one also runs **interactively** in the builder (Help → Tutorials, or
`edge tutorial <name>`): the coach highlights the part of the screen to use, waits until you've done
the step, then moves on. Tutorials start from a fresh copy, so you can't break anything.

| Tutorial | Level | Time | You will learn |
|---|---|---|---|
| [Your first experiment (a Stroop task)](#your-first-experiment-a-stroop-task) | beginner | 12 min | screens, things on a screen, timing, trial lists, test runs, Try it |
| [Trial lists, randomization and counterbalancing](#trial-lists-randomization-and-counterbalancing) | beginner | 8 min | conditions tables, factorial designs, order types, sequence constraints |
| [Practice until criterion (workflows)](#practice-until-criterion-workflows) | intermediate | 10 min | state machines, routes with conditions, live loop accuracy, max_visits |
| [Eye tracking, gaze areas and event markers](#eye-tracking-gaze-areas-and-event-markers) | intermediate | 10 min | devices, gaze_roi components, markers, synchronization report |
| [Questionnaires and consent with HTML pages](#questionnaires-and-consent-with-html-pages) | beginner | 7 min | html component, forms, saved answers, placeholders |
| [Rules, hints and conditional components](#rules-hints-and-conditional-components) | intermediate | 7 min | when → do rules, component if, variables |
| [Your data: tables, summaries and exports](#your-data-tables-summaries-and-exports) | beginner | 6 min | Data tab, trial tables, summaries, data dictionary, Excel/BIDS exports |
| [Bring an experiment from PsychoPy, E-Prime, OpenSesame or jsPsych](#bring-an-experiment-from-psychopy-e-prime-opensesame-or-jspsych) | beginner | 5 min | importing, import reports, checking a converted experiment |
| [Questionnaires like a pro (surveys)](#questionnaires-like-a-pro-surveys) | beginner | 8 min | survey component, question types, validated questionnaires, display logic, scores |

## Your first experiment (a Stroop task)

*Beginner · about 12 minutes* · interactive version: `edge tutorial first_experiment`

Build a colour-word Stroop task from an empty file: a fixation cross, a coloured word and a key press, repeated over a trial list in random order, then test it and try it yourself.

**1. Welcome**

This is the EDGE builder. You will build a complete Stroop experiment in about ten minutes.

* **Left:** the things you can put on a screen (text, pictures, key presses …) and devices.
* **Centre:** the storyboard or one screen's timeline with a live preview, the **flow** (the order
  things happen in), and the console.
* **Right:** the properties of whatever you select.

(In a hurry? **New → Make a new experiment: answer a few questions** builds a task like this
for you. Here you'll build it by hand to see how it works.)

Press **Next** to start. The coach waits for you at each step and moves on by itself when
the step is done.

**2. Create a screen**

A **screen** is one step of the experiment, like a single trial (in the file it's called a
*routine*). Click **+ screen** at the top and name it `trial`.

**3. Show a word**

Things go *on* a screen. Click **Text** in the list on the left. It appears on the timeline as a
bar (shown for 1 s for now) and in the preview on the right.

**4. Make the word come from the trial list**

In **Properties**, type `$word` into **text**.

A value that starts with `$` is a *formula*, computed while the experiment runs. Here `word` will
be a column of the trial list you'll create shortly. (Once a trial list exists, you can also pick
its columns from the small value menu next to each property: **Fixed**, **⟳ a column**, or
**+ New trial-list column…**.)

**5. Colour the word**

Still in Properties, type `$ink` into **color**. Each trial will now draw the word in the ink
colour from the trial list (red, green, blue…).

**6. Collect a response**

Click **Key press** on the left. In its properties, set **keys** to `r, g, b` and
**correct** to `$key`. **ends the screen** is already ticked, so a key press ends the trial, and the
word now stays on screen until the key press.

**7. Add a fixation cross first**

Click **Fixation cross** on the left, then set **lasts (s)** to `0.5`.

Then select the text (click **text** on the timeline) and set **starts at (s)** to `0.5`, so the
word appears right after the cross. You can also drag the bars on the timeline, and press ▶
under the preview to play the screen at real speed.

**8. Repeat the trial with a loop**

In the **Flow** strip, click the round **+** and choose **Repeat with a trial list (loop)**. Then
click the **+** *inside* the green box and choose **Screen: trial**.

**9. Fill in the trial list**

With the loop selected, the Properties panel shows its **trial list**: one row per trial. Rename
the first column to `word`, and add columns `ink` and `key`. Then add at least 3 rows, for example:

| word | ink | key |
|---|---|---|
| RED | red | r |
| RED | green | g |
| BLUE | blue | b |

**10. Randomize**

Set the loop's **order** to `random` and **repeats** to `2`. Every participant now gets each row
twice, in a new random order.

**11. Test it**

Click **▶ Test run**. EDGE runs the whole experiment in a few seconds with a *virtual participant*
who presses keys with realistic reaction times. Look at the **Test results** tab: the number of
trials, the verdict, then the data preview.

Then press **▶ Try it** to do the task yourself, right in the builder.

**12. Save**

Press **Save** (or Ctrl/⌘+S) and give your experiment a file name. Every later save keeps the
previous version, so you can always go back (**Versions**).

That's it: you built a complete experiment. To collect data, press **Run with a participant**.


---

## Trial lists, randomization and counterbalancing

*Beginner · about 8 minutes* · interactive version: `edge tutorial trial_lists`

Control which trials participants see and in what order: random vs full random, limits on repetitions in a row, factorial designs and counterbalancing by participant.

**1. Select the loop**

This experiment already has a Stroop trial inside a loop called **trials**. Click the loop's
green header in the **Flow** strip to select it.

**2. Shuffle across repeats**

Set **repeats** to `3` and **order** to `fullrandom`.

* `random` shuffles each repeat separately (you see all rows once before any repeats).
* `fullrandom` shuffles all repeats together.
* `latin_square` and `counterbalance` order the rows by participant number.

**3. Avoid long runs of the same colour**

Random orders sometimes put the same ink colour five times in a row. Set **max_repeat** to

`{"ink": 2}`

and EDGE builds orders where the same ink never appears more than twice in a row.
(Per value works too: `{"kind": {"deviant": 1}}` keeps deviants apart.)

**4. Try a factorial design**

Change **conditions source** to `factorial`. Instead of typing every row, you list each factor
with its levels, and EDGE builds every combination. For example
`{"word": ["RED", "GREEN"], "ink": ["red", "green"]}` gives 4 rows.

(For this Stroop you'd also need a `key` column, so switch back to `table` afterwards if you like.)

**5. Conditions from a spreadsheet**

For real studies, trial lists usually live in a file. Choose **conditions source** = `file`
and type a CSV, TSV or XLSX name next to your experiment. The builder shows a preview of the
rows.

Press **Next** when you've had a look.

**6. Check what participants will see**

Click **▶ Test run**, then open the **Data** tab and tick *include test runs*. The trial table shows
the order this virtual participant got, and the `trials.row` column tells you which row of the
list each trial used.


---

## Practice until criterion (workflows)

*Intermediate · about 10 minutes* · interactive version: `edge tutorial workflow_practice`

Turn two loops into a workflow: participants repeat the practice block until they reach 80% correct (at most three times), then continue to the main task.

**1. The plan**

The flow has a **practice** loop (with feedback) and a **main** loop. You want:
*practice → if accuracy ≥ 80% go to main, otherwise practice again (at most 3 times)*.

That's a **workflow** (a state machine). Press **Next**.

**2. Add a workflow**

In the **Flow** strip, click the first round **+** (far left) and choose **Workflow (state machine)**.
A purple box appears with one state called `start`.

**3. Rename the state**

Click the state name **start** inside the purple box. In Properties, click the **name**
field and rename it to `practice`.

**4. Move the practice loop into it**

**Drag** the green *practice* loop header and drop it on the **+** inside the `practice` state.
(Every item in the flow can be dragged onto any + button.)

**5. Add the main state**

Click **+ state** in the workflow box, name it `main`, and drag the *main* loop into it.

**6. Route by accuracy**

Select the **practice** state. Under **Routes**, the first route has a condition and a target:

* condition: `$practice.accuracy >= 0.8` and go to **main**
* click **+ Route** and make the second one go to **practice** with an empty condition (that means "otherwise").

Loops measure accuracy live: `$practice.accuracy` is the proportion correct in the practice block.

**7. Limit the repetitions**

Set **max_visits** to `3`. After three practice rounds the participant moves on even if they
haven't reached the criterion, so nobody gets stuck.

**8. See the diagram**

Click the workflow's header (**⚙ … workflow**). The top panel turns into a live diagram of the
states and routes. Solid arrows have conditions; dashed ones are the defaults.

**9. Test run**

Click **▶ Test run**. The virtual participant answers 90% correctly, so they usually pass first time.
In the session data, the `workflow.state` and `workflow.visit` columns show the path taken.


---

## Eye tracking, gaze areas and event markers

*Intermediate · about 10 minutes* · interactive version: `edge tutorial eyetracking`

Add an eye tracker, measure where people look with gaze areas of interest, mark stimulus onsets for every device, and read the synchronization report.

**1. Add an eye tracker**

Click **+** next to **Devices** (left panel) and choose **sim_eyetracker**: a simulated tracker,
perfect for building at your desk. For real hardware you'd pick **tobii** or **gazepoint**; the
rest of the experiment stays the same.

**2. Open the trial**

Click the **look** screen in the Flow strip. It shows a red and a blue square for 4 seconds.

**3. Add a gaze area of interest**

Click **Where they look** on the left (under *Eye tracking*). In Properties, set **target** to
`left_box`. EDGE now records whether, when and how long the participant looked at the left square.

**4. A second area**

Add another **Where they look** with **target** `right_box`.

**5. Mark the stimulus onset**

Select **left_box** and set **marker** to `squares_on`. At the exact screen flip that shows the
squares, EDGE sends this event to every device: TTL triggers, LSL, the eye tracker's own data
file. It's written to the event log too.

**6. Send markers to LabRecorder too**

Add a device of type **lsl_markers**. Anything recording Lab Streaming Layer (LabRecorder, an EEG
system) then receives the same markers with matching timestamps.

**7. Test run and read the sync report**

Click **▶ Test run** and look at **Streams & synchronization** in the results. The simulated tracker
runs on its own drifting clock, and EDGE recovers the drift. The *triggers* column shows that
every marker arrived, and *alignment* shows how precisely.


---

## Questionnaires and consent with HTML pages

*Beginner · about 7 minutes* · interactive version: `edge tutorial html_questionnaire`

Put a real HTML form inside your experiment: every answer is saved as a data column, and test runs fill the form in automatically.

**1. Create a screen for the questionnaire**

Click **+ screen** and name it `survey`.

**2. Add an HTML page**

Click **Web page / form** on the left. HTML pages can show consent forms, questionnaires, rich
instructions, or even complete JavaScript tasks.

**3. Write the form**

In Properties, paste this into **html** (or use **file** to point at an `.html` file):

```html
<h2>How do you feel?</h2>
<form>
  <label><input type="radio" name="mood" value="1" required> bad</label>
  <label><input type="radio" name="mood" value="2"> okay</label>
  <label><input type="radio" name="mood" value="3"> great</label>
  <p>Age <input type="number" name="age" min="18" max="99"></p>
  <button>Continue</button>
</form>
```

The preview shows the real page.

**4. Move on when the form is sent**

Tick **ends the screen** in the **When** section.

**5. Put it in the flow**

In the **Flow** strip click **+** and choose **Screen: survey**.

**6. Test run and see the answers**

Click **▶ Test run**. The virtual participant fills in the form, and the data preview has the columns
`html.mood` and `html.age`. In real sessions, answers land in exactly the same place.

Tip: write `{{participant}}` or any trial variable in the HTML to show it on the page.


---

## Rules, hints and conditional components

*Intermediate · about 7 minutes* · interactive version: `edge tutorial rules_and_feedback`

Make screens react while they run: show a hint if the participant is slow, and show feedback only during practice.

**1. Open the trial**

Click **trial** in the Flow strip. It has a **hint** text that never starts by itself
(`start_if` is `$False`). You'll start it with a rule.

**2. Add a rule**

In the screen's Properties (click an empty part of the timeline header if a component is
selected), find **Rules (when → do)** and click **+ Rule**.

**3. Say when**

Set the rule's **When** to `$t > 1.5 and resp.keys is None`: 1.5 s into the trial, if no key
has been pressed yet.

**4. Say what to do**

Change the action from *end the screen* to **start component**, and pick **hint**. Slow
participants now see the key reminder.

Other actions: stop a component, set a variable, send a marker, or jump to another workflow state.

**5. Feedback only in practice**

Open the **feedback** screen and select the **fb** text. In its **When** section set **only if** to
`$practice.n < 6`, so feedback is shown only for the first six practice trials.
Any expression works, for example `$practice_mode` or `$word == 'RED'`.

**6. Check the summary**

Read the grey summary above the timeline. EDGE describes each screen in plain language,
including the rules, so you can check the logic at a glance. Click **▶ Test run** to finish.


---

## Your data: tables, summaries and exports

*Beginner · about 6 minutes* · interactive version: `edge tutorial data_and_export`

See what EDGE saves, read the automatic per-condition summary, and export to Excel, CSV or BIDS, for one participant or everyone at once.

**1. Collect some data**

Click **▶ Test run**. It writes a session folder exactly like a real participant would.

**2. Open the Data tab**

Open the **Data** tab in the console and tick *include test runs*. Every session in this folder is
listed. Click the newest one.

**3. One row per trial**

**Trials** shows one row per trial with columns in a sensible order: participant, design,
conditions, responses (`resp.keys`, `resp.rt`, `resp.corr`), timing.

**Summary** shows accuracy and RT per condition (correct trials only, outliers removed), and
**Data dictionary** explains every column. Press **Next** when you've looked around.

**4. Export**

Click **↓ Excel** for a workbook with all three tables. **↓ BIDS** writes a BIDS-style folder.
**Export all** (left) merges every participant into one dataset.

Press **Next**.

**5. Export automatically after every session**

Click **Settings** (top bar) and, under the data settings, edit the experiment file so it reads
`data: {exports: [csv, xlsx]}`. The easiest way is the **Source (YAML)** tab: add `xlsx` to `exports`
and click **Apply YAML**.
From then on, every session also gets an Excel file automatically.


---

## Bring an experiment from PsychoPy, E-Prime, OpenSesame or jsPsych

*Beginner · about 5 minutes* · interactive version: `edge tutorial import_existing`

Convert an existing experiment, read the import report, and verify the result with a test run.

**1. What can be imported**

* **PsychoPy:** the `.psyexp` file plus its conditions files and images.
* **E-Prime:** in E-Studio press *Generate* to get the `.ebs3` script; also save each List as `<ListName>.txt`.
* **OpenSesame:** the `.osexp` file.
* **jsPsych:** the `.html` (or `.js`) file with the timeline.

Press **Next**.

**2. Import**

Click **Import** in the top bar and select *all* the files at once (experiment, conditions,
images, list exports). EDGE converts them and shows a summary.

**3. Read the report**

The summary lists what **needs manual work** (e.g. movies or custom code) and what was
**converted approximately**. The full list is in `IMPORT_REPORT.md` next to the new experiment.

Click **Open and dry-run** to load the converted experiment and test it straight away.

**4. Verify**

Compare the test run with the original: number of trials, timing per screen (read the plain-language
summary above each timeline), response keys and correct answers. Fix anything flagged, then save.

Command-line alternative: `edge import my_task.psyexp`.


---

## Questionnaires like a pro (surveys)

*Beginner · about 8 minutes* · interactive version: `edge tutorial survey_builder`

Add a questionnaire after a task: a validated scale from the library that scores itself, your own multiple-choice question, and a follow-up that only appears for some answers.

**1. The plan**

This experiment has a placeholder **task** screen. After it you'll add a questionnaire with:

* a validated scale from the library (it scores itself),
* a multiple-choice question of your own,
* a follow-up question that appears only for some answers.

Press **Next**.

**2. Add a survey**

Click **Survey / questionnaire** on the left. Because the task screen already has something on
it, EDGE gives the survey its own screen, **questionnaire**, right after the task in the flow.

**3. Open the survey editor**

In **Properties**, click **✎ Edit questions**. The editor has three columns: the questions on the
left, the selected question in the middle, and on the right the **real page** participants will
see. You can click through it.

Press **Next** when you've had a look.

**4. Add a validated questionnaire**

Click **+ From library**, search for `life` and **Add** the *Satisfaction With Life Scale (SWLS)*.
Its five items, the 7-point scale and the scoring (`swls_total`, with interpretive bands) come with it.

**5. Your own multiple-choice question**

Click **+ Question → Multiple choice (checkboxes)**. In the middle column set the question to
*Which of these do you do at least once a week?* and the options (one per line) to
`Sport`, `Music`, `Reading`, `None of these`. Set **Exclusive option** to *None of these* and
the **Data name** to `weekly`.

**6. A follow-up with display logic**

Add **+ Question → Number**, data name `sport_hours`, question *How many hours of sport per week?*.
Under **Display logic** choose *only if weekly* and **includes** *Sport*.

In the preview, tick *Sport* in the earlier question and watch the follow-up appear.

**7. Test it**

Click **Done**, then **▶ Test run**. The virtual participant fills in the survey; in the data
preview you'll find `survey.weekly`, one 0/1 column per option (`weekly_sport` …),
`sport_hours` (empty when Sport wasn't ticked), the five SWLS items, `swls_total` and
`swls_total_band`.

**8. Try it yourself**

Press **▶ Try it** to fill in the survey yourself. Leave a required question empty and press
**Next** to see the plain-language check.

The [Surveys guide](SURVEYS.md) lists every question type, display logic, scores and the
whole questionnaire library.

