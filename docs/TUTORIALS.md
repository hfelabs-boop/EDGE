# Tutorials

Hands-on lessons. Each one also runs **interactively** in the builder (**Help** › *Learn by doing*,
**All tutorials** on Home, or `edge tutorial <name>`): the coach points at the part of the screen to use,
waits until you've done the step, then moves on. Tutorials start from a fresh copy, so you can't break
anything.

| Tutorial | Level | Time | You will learn |
|---|---|---|---|
| [Your first experiment (a Stroop task)](#your-first-experiment-a-stroop-task) | beginner | 12 min | screens, items, timing, trial lists, test runs, saving |
| [Trial lists, randomization and counterbalancing](#trial-lists-randomization-and-counterbalancing) | beginner | 8 min | trial lists, every combination (factorial designs), order, limits on runs in a row |
| [Practice until criterion (workflows)](#practice-until-criterion-workflows) | intermediate | 10 min | workflows, phases, routes with conditions, live trial-list accuracy, repeat a phase at most N times |
| [Eye tracking, gaze areas and event markers](#eye-tracking-gaze-areas-and-event-markers) | intermediate | 10 min | devices, gaze areas of interest, event markers, the synchronisation report |
| [Questionnaires and consent with web pages](#questionnaires-and-consent-with-web-pages) | beginner | 7 min | web page / form items, forms, saved answers, placeholders |
| [Rules, hints and items shown only sometimes](#rules-hints-and-items-shown-only-sometimes) | intermediate | 7 min | rules (when … do …), items shown only if a condition holds, In words |
| [Your data: tables, summaries and exports](#your-data-tables-summaries-and-exports) | beginner | 6 min | the Data page, trial tables, summaries, what each column means, Excel/BIDS exports |
| [Bring an experiment from PsychoPy, E-Prime, OpenSesame or jsPsych](#bring-an-experiment-from-psychopy-e-prime-opensesame-or-jspsych) | beginner | 5 min | importing, import reports, checking a converted experiment |
| [Questionnaires like a pro (surveys)](#questionnaires-like-a-pro-surveys) | beginner | 8 min | survey / questionnaire items, question types, validated questionnaires, display logic, scores |
| [Build with the assistant](#build-with-the-assistant) | beginner | 6 min | the assistant panel, where it runs (Claude, OpenAI-compatible, Ollama, LM Studio), privacy, preview, Apply and Undo |

## Your first experiment (a Stroop task)

*Beginner · about 12 minutes* · interactive version: `edge tutorial first_experiment`

Build a colour-word Stroop task from an empty experiment: a fixation cross, a coloured word and a key press, repeated over a trial list in random order, then test it and save it.

**1. Welcome**

This is the EDGE builder. You will build a complete Stroop experiment in about 12 minutes.

* **Top:** the five workspaces, **Build · Measures · Test · Run · Data**, in the order you use them.
* **Left:** **Add** (the items you can put on a screen: text, pictures, key presses …), **Files**
  and **Devices**.
* **Centre:** the **Storyboard** (every screen in order) or one **Screen** with its live preview
  and timeline.
* **Right:** the **Properties** of whatever you select.

(In a hurry? **Answer a few questions** builds a task like this for you, and the **Assistant**
builds one from a description. Here you'll build it by hand to see how it works.)

Press **Next** to start. The coach waits for you at each step and moves on by itself when the
step is done.

**2. Create a screen**

A **screen** is one step of the experiment, like a single trial. Click **Add screen** at the
top of the canvas, type `trial` and press **Add screen**.

The new screen joins the experiment at once and opens in the **Screen** view.

**3. Show a word**

Things go *on* a screen. Click **Text** under **Add** on the left. It appears on the screen and
on the timeline as a bar (shown for 1 s for now), and Properties shows it.

**4. A different word on every trial**

In **Properties**, point at **Text**: a small **Fixed** button appears at the right of the label.
It says where the value comes from. Click it, choose **New trial-list column…**, type `word` and
press **Add column**.

EDGE puts the screen into a **trial list** (one row per trial) with a column `word`, and the text
now shows that column's value on each trial.

**5. Colour the word**

Do the same for **Colour**: **Fixed** › **New trial-list column…**, name it `ink`. Each trial will
draw the word in the colour from the trial list (red, green, blue …).

The word disappears from the preview for now: the new column is still empty. You'll fill it in
shortly.

**6. Collect a response**

Click **Key press** on the left. In its Properties:

* **Keys**: click the box, press Backspace to remove `space`, then press **R**, **G** and **B**.
* **Correct answer**: **Fixed** › **New trial-list column…**, name it `key`.

**Ends the screen** is already on, so a key press moves on to the next trial, and the word now
stays on the screen until the key press.

**7. Add a fixation cross first**

Click **Fixation cross** on the left, then set **Lasts** to `0.5` under **Timing**.

Then select the text (click **text** on the timeline) and set **Starts at** to `0.5`, so the word
appears right after the cross. You can also drag the bars on the timeline, and press the play
button under the preview to play the screen at real speed.

**8. Open the trial list**

The **Storyboard** shows the whole experiment: your screen sits inside the green frame
**Trial list “trials”**. Click **Open list** in its header.

**9. Fill in the trial list**

This is the trial list: one row per trial, one column per value that changes. It works like a
spreadsheet: click a cell and type, **Tab** moves right, **Enter** moves down, **+ Row** adds a
row, and **Ctrl+V** pastes rows copied from Excel.

Make at least 3 rows, for example:

| word | ink | key |
|---|---|---|
| RED | red | r |
| RED | green | g |
| BLUE | blue | b |

**10. Shuffle and repeat**

With the trial list open, Properties shows how it runs. **Order** is already **Shuffled each
time**: every participant gets the rows in a new random order. Set **Repeat the list** to `2` to
show each row twice; the line next to it counts the trials.

Press **Done** at the top right of the list to go back to the Storyboard, then **Next**.

**11. Test it**

Open **Test** (top) and click **Start test run**. EDGE runs the whole experiment in a few seconds
with a *virtual participant* who presses keys with realistic response times. The **Last test run**
card shows the number of trials, the verdict and a data preview.

Then press **Try it** (top right) to do the task yourself, right in the builder. **Esc** stops.
Press **Next** when you're done.

**12. Save**

Click the save button at the top, **Unsaved changes** (in a narrow window it is the disk icon with a
dot), or press Ctrl/⌘+S. Give your experiment a name and press
**Save**. It gets its own folder. Every later save keeps the previous version, so you can always
go back (**History…** in the Experiment menu).

That's it: you built a complete experiment. To collect data, open **Run**.


---

## Trial lists, randomization and counterbalancing

*Beginner · about 8 minutes* · interactive version: `edge tutorial trial_lists`

Control which trials participants see and in what order: shuffled each time or across repeats, limits on the same value in a row, every combination of your factors, and counterbalancing by participant number.

**1. Select the trial list**

This experiment already has a Stroop screen inside a trial list called **trials** (the green
frame in the **Storyboard**). Click the frame's title, **Trial list “trials”**, to select it.
Properties now shows how the list runs.

**2. Shuffle across repeats**

In Properties, set **Repeat the list** to `3`, then choose **Shuffled across repeats** under
**Order**.

* **Shuffled each time** shuffles each repeat separately: every row is shown once before any row
  comes back.
* **Shuffled across repeats** shuffles all repeats together.
* **Latin square by participant number** and **Counterbalanced by participant number** give each
  participant a different, planned order.

**3. Avoid long runs of the same colour**

A random order sometimes puts the same ink colour five times in a row. Open **More options** at
the bottom of Properties and, under **No more than N in a row**, type `2` next to **ink**.

EDGE now builds orders where the same ink never comes more than twice in a row.

**4. Open the trial list**

Click **Open list** (in Properties or in the frame's header). The trial list fills the canvas:
one row per trial, one column per value that changes.

**5. Every combination**

Instead of typing every row, you can list each factor with its levels and let EDGE build every
combination. Choose **Every combination** under **Rows come from**: each column becomes a factor
with its levels as chips, and the line under them counts the rows (3 × 3 × 3 = 27).

Have a look, then press **Next**.

**6. Back to your typed rows**

In this Stroop the right key depends on the ink colour, so not every combination makes sense
(RED in red ink with the key for blue would be scored wrong). Press **Undo** (Ctrl+Z) to go
back to your typed rows.

Don't remove the `key` column instead: the key press item reads its correct answer from it.

**7. Trial lists from a spreadsheet**

For real studies, trial lists usually live in a file. **A file** under **Rows come from** picks a
CSV, TSV or Excel file from the experiment's folder (or uploads one); the grid shows its rows,
read-only. **Copy into the experiment** turns a file's rows into typed rows you can edit here.

Press **Next** when you've had a look.

**8. Test run**

Open **Test** and click **Start test run**. A virtual participant does every trial in a few
seconds.

**9. See the order participants got**

Open **Data**, choose **Tests & tries** and click the newest session. The **Trials** table shows
the order this virtual participant got; the `trials.row` column says which row of the list each
trial used.


---

## Practice until criterion (workflows)

*Intermediate · about 10 minutes* · interactive version: `edge tutorial workflow_practice`

Turn two trial lists into a workflow: participants repeat the practice block until they reach 80% correct (at most three times), then continue to the main task.

**1. The plan**

The storyboard has a **practice** trial list (with feedback) and a **main** trial list. You want:
*practice → if accuracy ≥ 80 % go to main, otherwise practice again (at most 3 times)*.

That's a **workflow**: **phases** with "then go to…" **routes**. Press **Next**.

**2. Add a workflow**

In the **Storyboard**, click the round **+** at the far left, *outside* the practice list (the
highlighted one), and choose **Workflow (practice until good, screening…)**. A purple frame
appears with one phase called `start`.

**3. Rename the phase**

Click the phase name **start** inside the purple frame. In Properties, change **Name** to
`practice` and press Tab.

**4. Move the practice list into it**

**Drag** the green **Trial list “practice”** by its title and drop it on the **+** inside the
`practice` phase. (Every screen and trial list can be dragged onto any **+**.)

**5. Add the main phase**

Click **Add a phase** at the bottom of the workflow, name it `main`, then drag the
**Trial list “main”** onto the **+** inside the new phase.

**6. Route by accuracy**

Click the **practice** phase name to select it. Under **Then go to…**, click **Add a route**, then:

* route 1: **When** `$practice.accuracy >= 0.8`, **go to** **main**;
* route 2: leave **When** empty (that means *otherwise*), **go to** **practice (again)**.

Trial lists measure accuracy while they run: `$practice.accuracy` is the proportion correct in
the practice block. The line under the formula says it in words. Press **Next** when both routes
are set.

**7. Limit the repetitions**

Set **Repeat this phase at most** to `3`. After three practice rounds the participant moves on
even if they haven't reached the criterion, so nobody gets stuck. (In the file this is `max_visits: 3`.)

**8. See the diagram**

Click **Open diagram** in the workflow's header. The canvas shows the phases and their routes:
solid arrows have conditions, dashed ones are the *otherwise* routes. Click a phase there to edit
it; **Done** goes back to the Storyboard. Press **Next** when you've had a look.

**9. Test run**

Open **Test** and click **Start test run**. The virtual participant answers about 90 % correctly,
so they usually pass the first time. In the session's data (**Data** › **Tests & tries**), the
`workflow.state` and `workflow.visit` columns show the path taken.


---

## Eye tracking, gaze areas and event markers

*Intermediate · about 10 minutes* · interactive version: `edge tutorial eyetracking`

Add an eye tracker, measure where people look with gaze areas of interest, mark stimulus onsets for every device, and read the synchronisation report.

**1. Add an eye tracker**

In the **Devices** tab on the left, click **Add device**. Choose **Simulated (for testing)** ›
**Simulated eye tracker** (`sim_eyetracker`) and press **Add device**: a simulated tracker, perfect
for building at your desk. For real hardware you'd pick **Tobii Pro** or **Gazepoint** under
**Eye tracker**; the rest of the experiment stays the same.

**2. Open the screen**

Double-click the **look** card in the Storyboard (or click it and press Enter). It shows a red and
a blue square for 4 seconds.

**3. Add a gaze area of interest**

Click **Where they look** under **Eye tracking** on the left (`gaze_roi`). In Properties, set
**Area of** (`target`) to `left_box`. EDGE now records whether, when and how long the participant
looked at the left square.

**4. A second area**

Add another **Where they look** with **Area of** `right_box`.

**5. Mark the stimulus onset**

Click **left_box** on the timeline and set **Event marker** (`marker`) to `squares_on`. At the
exact screen refresh that shows the squares, EDGE sends this event to every device: TTL triggers,
LSL, the eye tracker's own data file. It's written to the event log too.

**6. Send markers to LabRecorder too**

**Add device** again and choose **Marker stream** › **LSL marker stream (LabRecorder)**
(`lsl_markers`). Anything recording Lab Streaming Layer (LabRecorder, an EEG system) then receives
the same markers with matching timestamps.

**7. Test run and read the synchronisation report**

Open **Test** and click **Start test run**, then look at **Streams & synchronisation** under
**Last test run**. The simulated tracker runs on its own drifting clock, and EDGE recovers the
drift. The *triggers* column shows that every marker arrived, and *alignment* shows how precisely.


---

## Questionnaires and consent with web pages

*Beginner · about 7 minutes* · interactive version: `edge tutorial html_questionnaire`

Put a real HTML form inside your experiment: every answer is saved as a data column, and test runs fill the form in automatically.

**1. Create a screen for the questionnaire**

Click **Add screen**, type `survey` and press **Add screen**.

**2. Add a web page**

Click **Web page / form** under **Add** on the left. Web pages can show consent forms,
questionnaires, rich instructions, or even complete JavaScript tasks.

(For ready-made questionnaires with scoring, use **Survey / questionnaire** instead: see the
tutorial *Questionnaires like a pro*.)

**3. Write the form**

In Properties, paste this into **Page content (HTML)** and press Tab (or use **Choose…** to pick
an `.html` file):

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

The preview shows the real page. **Ends the screen** is already on: the experiment moves on when
the form is sent.

**4. It's already in the experiment**

Click **Storyboard** at the top of the canvas (in a narrow window, the button with four squares).
New screens join the experiment where you make them, so `survey` is already in the order: its card
shows a thumbnail of the page.

**5. Test run and see the answers**

Open **Test** and click **Start test run**. The virtual participant fills in the form, and the data
preview has the columns `page.mood` and `page.age` (the item is called `page`). In real sessions,
answers land in exactly the same place.

Tip: write `{{participant}}` or any trial-list column in the HTML to show it on the page.


---

## Rules, hints and items shown only sometimes

*Intermediate · about 7 minutes* · interactive version: `edge tutorial rules_and_feedback`

Make screens react while they run: show a hint if the participant is slow, and show feedback only during the first practice trials.

**1. Select the trial**

Click the **trial** card in the Storyboard. Properties shows the screen. It has a **hint** text
that never starts by itself (its *starts when* is `$False`). You'll start it with a rule.

**2. Add a rule**

In Properties, find **Rules · react while the screen runs** and click **Add a rule**.

**3. Say when**

Set the rule's **When** to `$t > 1.5 and resp.keys is None` and press Tab: 1.5 s into the trial,
if no key has been pressed yet. The line under it says the same in words.

**4. Say what to do**

Under **Do**, change **End the screen** to **Start an item**, then pick **hint** in the menu next
to it. Slow participants now see the key reminder.

Other actions: stop an item, set variables, send a marker, go to a workflow phase, or write to the
log.

**5. Feedback only in practice**

First make sure the rule's item is **hint** (not `fix`). Then double-click the **feedback** card,
click **fb** on the timeline, and set **Only if** (`if`) to `$practice.n < 6`, so feedback is shown
only for the first six practice trials. Any formula works, for example `$word == 'RED'`.

**6. Check the summary**

Read **In words** above the timeline: EDGE describes each screen in plain language, including when
its items start, so you can check the logic at a glance. Then open **Test** and click
**Start test run** to finish.


---

## Your data: tables, summaries and exports

*Beginner · about 6 minutes* · interactive version: `edge tutorial data_and_export`

See what EDGE saves, read the automatic per-condition summary, and export to Excel, CSV or BIDS, for one participant or everyone at once.

**1. Collect some data**

Open **Test** and click **Start test run**. It writes a session folder exactly like a real
participant would.

**2. Open Data**

Open **Data** (top). Sessions with participants are listed under **Participants**; test runs and
your own tries under **Tests & tries**. Choose **Tests & tries** and click the newest session,
then press **Next**.

**3. One row per trial**

**Trials** shows one row per trial with the columns in a sensible order: participant, design,
trial-list columns, responses (`resp.keys`, `resp.rt`, `resp.corr`), timing.

**Summary** shows accuracy and response times per condition (correct trials only, outliers
removed), and **What each column means** explains every column. Press **Next** when you've
looked around.

**4. Export**

**Export** (top right of the session) writes this session as CSV, Excel, TSV, JSON or BIDS.
**Export all sessions** (under the list) merges every participant into one table (CSV + Excel) or
one BIDS folder. A message says where the files went, with **Show the files**.

Press **Next**.

**5. Back to Build**

Exports can also happen by themselves after every session. That is a setting of the experiment:
open **Build**.

**6. Export automatically after every session**

Click **Experiment settings** (the sliders button at the right of the Build toolbar, or
**Experiment settings…** in the Experiment menu). Under **Data files** › **Also save as**, tick
**Excel (.xlsx)**, then **Done**. From now on, every session also gets an Excel file automatically.
Press **Next** once the dialog is closed.

**7. The same setting in the file**

In Expert mode the Build view switch has **YAML**: the experiment file itself. Click it and find,
under `settings:` › `data:`, the lines

```
exports:
- csv
- xlsx
```

You can edit the file there and press
**Apply YAML**; everything you do in the builder ends up in this file.


---

## Bring an experiment from PsychoPy, E-Prime, OpenSesame or jsPsych

*Beginner · about 5 minutes* · interactive version: `edge tutorial import_existing`

Convert an existing experiment, read the import report, and check the result with a test run.

**1. What can be imported**

* **PsychoPy:** the `.psyexp` file plus its conditions files and images.
* **E-Prime:** in E-Studio press *Generate* to get the `.ebs3` script; also save each List as `<ListName>.txt`.
* **OpenSesame:** the `.osexp` file.
* **jsPsych:** the `.html` (or `.js`) file with the timeline.
* **EDGE:** a shared `.edgez` file opens as it is.

Press **Next**.

**2. Import**

Click the experiment's name at the top left to open the **Experiment menu** and choose
**Import…** (on Home, **Import** is a button). Then **Choose a folder…** (the experiment's whole
folder, with its pictures, sounds and condition files) or **Choose files…** and select *all* the
files at once. EDGE converts them and shows a summary.

**3. Read the report**

The summary counts what **needs work by hand** (e.g. movies or custom code) and what was converted
**approximately: please check**. **View the report** shows the full list, which is also saved as
`IMPORT_REPORT.md` next to the new experiment.

Click **Open and test** to load the converted experiment and test-run it straight away. (No files
to import right now? **Skip step**.)

**4. Check it**

Compare the test run with the original: the number of trials, the timing of each screen (read
**In words** above each timeline), the response keys and the correct answers. Fix anything the
report flagged, then save.

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

Double-click the **task** card to open the screen, then click **Survey / questionnaire** under
**Add** on the left. Because the task screen already has something on it, EDGE gives the survey
its own screen, **questionnaire**, right after the task.

**3. Open the survey editor**

In **Properties**, click **Edit questions**. The editor has three columns: the questions on the
left, the selected question in the middle, and on the right the **real page** participants will
see. You can click through it.

Press **Next** when you've had a look.

**4. Add a validated questionnaire**

Click **From the library**, search for `life` and press **Add** on the *Satisfaction With Life
Scale (SWLS)*. Its five items, the 7-point scale and the scoring (`swls_total`, with interpretive
bands) come with it.

**5. Your own multiple-choice question**

Click **Add a question** › **Multiple choice (checkboxes)**. In the middle column set **Question**
to *Which of these do you do at least once a week?* and **Options (one per line)** to `Sport`,
`Music`, `Reading`, `None of these`. Set **Exclusive option** to *None of these* and the
**Data name** to `weekly`.

**6. A follow-up with display logic**

Click **Add a question** › **Number**: data name `sport_hours`, question *How many hours of sport
per week?*. Under **Show it** choose **Only if weekly: …**, then **includes** and **Sport**.

In the preview, tick *Sport* in the earlier question and watch the follow-up appear. Then press
**Next**.

**7. Test it**

Click **Done**, then open **Test** and click **Start test run**. The virtual participant fills in
the survey; in the data preview you'll find `survey.weekly`, one 0/1 column per option
(`weekly_sport` …), `sport_hours` (empty when Sport wasn't ticked), the five SWLS items,
`swls_total` and `swls_total_band`.

**8. Try it yourself**

Press **Try it** (top right) to fill in the survey yourself. Leave a required question empty and
press **Next** to see the plain-language check.

The [Surveys guide](SURVEYS.md) lists every question type, display logic, scores and the
whole questionnaire library.


---

## Build with the assistant

*Beginner · about 6 minutes* · interactive version: `edge tutorial assistant_basics`

Meet the assistant: describe an experiment or a change in your own words, see it as a preview, and apply it (or undo it). Learn where the assistant can run and what is sent where. Works without a model: only the last steps need one.

**1. What the assistant does**

The **assistant** builds and changes experiments from a description in your own words, for
example *"Add a practice block of 6 trials that repeats until 80 % are correct"*. You can attach
the files you already have (a trial list in Excel or CSV, pictures, a consent page). It checks and
test-runs what it made, and you see every change as a preview before anything happens.

It is optional: everything else in EDGE works without it. Press **Next**.

**2. Open the assistant**

Click **Assistant** at the top right, the sparkle button (or press **Ctrl+I**). The assistant opens in a column next
to your work, so the experiment stays visible.

**3. Open the assistant settings**

Click the chip under the panel's title: it says **Not set up**, or which service the assistant
uses. It opens **Assistant settings** (also in the panel's **⋯** menu).

**4. Where should the assistant run?**

Choose one of four services:

* **Claude (Anthropic)**: the best results. Online; paste an API key from console.anthropic.com.
* **OpenAI-compatible**: OpenAI, OpenRouter or another online service, with its API key.
* **Ollama** or **LM Studio**: free, run a model on this computer, nothing leaves it. Install the
  app and download a model first (for Ollama: `ollama pull qwen2.5:14b`).

Fill in the fields, press **Test connection**, then **Save**. The [Assistant guide](ASSISTANT.md)
has the details for each service.

**5. What is sent where**

For an online service, open **What is sent where** under its fields and read it: what you type, the
experiment you are editing and the files you attach go to that company; your participants' data
never does, and your API key stays on this computer. For Ollama or LM Studio the settings say
*On this computer: nothing is sent anywhere.* The panel repeats this in one line under the box you
type in.

Then press **Save** (or **Cancel** if you are not setting it up now) and **Next**. For an online
service EDGE asks once, *Before EDGE sends anything online*: press **Continue**.

**6. Describe an experiment**

*Skip this step if you haven't set up a model yet.*

Type a description in **Describe a change, or ask a question…** and press Enter, for example:
*A Stroop task: the words RED, GREEN and BLUE in red, green or blue ink; the participant presses
r, g or b for the ink colour.* The panel shows each step while it works.

The result opens as a **preview**: new screens are marked, and the bar at the top says "Nothing is
changed until you apply". Read the list of changes, then press **Apply**.

**7. Undo, attach, and more**

* **Apply** is one step: **Undo** (in the panel, or Ctrl+Z) brings back the experiment exactly as
  it was. **Discard** throws a preview away.
* **Attach files** (the paper clip, or drop files on the panel): they are copied into this
  experiment's folder, so the experiment can use them.
* Select a screen or an item first to ask about it (*"make this bigger"*).
* **Ask the assistant** also appears next to problems, and Home has a **Describe it** box for new
  experiments.

That's it. Press **Finish**.

