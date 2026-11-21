# Task library: attention and inhibition tasks

Sixteen classic attention, inhibition and vigilance paradigms, written natively for EDGE. Each one lives in
`edge/library/tasks/<id>/` as an ordinary experiment (`<id>.yaml`, its trial lists as CSV files, and `meta.yaml`
with the description, measures and references). Open one in the builder, try it, and change it like any of your own
experiments: trial counts are the `repeats` of the trial lists, timings are item start/duration values or variables,
and conditions and correct answers are columns of the trial lists.

Every task has a plain-language instruction screen, a practice block (with feedback where the paradigm normally
has one), the test block(s) and a thank-you screen, and declares its **measures**, so `measures.csv` and the
session report give the main outcome per condition right after a session. The practice block's data are in
`trials.csv` too (loop `practice`); the measures use only the test block (loop `main`).

These are independent implementations of the published methods, with our own wording and stimuli. Each task's
`meta.yaml` cites the original papers and links to the matching page of the PsyToolkit experiment library.

| task (id) | what the participant does | main outcome | min |
|---|---|---|---|
| Attentional blink (`ab`) | reports two digits hidden in a 10-per-second letter stream | second digit correct (when the first was) by lag | 5 |
| ABBA reversed compatibility (`abba`) | plans a left/right key, answers a coloured circle at once, then carries out the plan | RT to the circle when it shares the planned side vs not | 6 |
| Attention Network Test (`ant`) | cued arrow flanker task | alerting, orienting and executive scores from RT by cue and flanker | 9 |
| AX-CPT (`ax_cpt`) | M only for X after A, Z otherwise | errors and RT on AY and BX pairs | 6 |
| Spatial cueing / Posner (`cueing`) | locates a dot after a central arrow (80% valid) | validity effect (invalid - valid RT) | 5 |
| Endogenous vs exogenous cueing (`endo_exo_cueing`) | locates a dot after an arrow (75% valid) or a box flash (50%), 100 / 600 ms | validity effect by cue type and interval | 7 |
| Inhibition of return (`ior`) | detects a dot after an uninformative box flash, 100 / 800 ms | cued vs uncued RT: facilitation, then IOR | 5 |
| Dot probe (`dotprobe`) | locates a dot that replaces one of two words (threat / neutral) | attentional bias (incongruent - congruent RT) | 4 |
| Go/no-go (`go_no_go`) | SPACE for P (75%), nothing for R | commission errors, go RT | 3 |
| SART (`sart`) | SPACE for every digit except 3 | commission errors on 3s, omissions, go RT | 5 |
| SART with feedback (`sart2`) | the SART with a right/wrong message after every digit | as the SART | 6 |
| Stop-signal task (`stopsignal`) | arrow keys, but stop when the arrow turns red; the delay adapts | SSRT, go RT, P(stop), mean delay | 6 |
| Flanker, letters (`flanker`) | classifies the middle letter of five | flanker effect by condition | 4 |
| Flanker, arrows (`flanker_arrows`) | arrow key for the middle arrow of five | incongruent - congruent RT | 4 |
| Attentional capture and grouping (`maabrams`) | finds a diamond among circles, one sometimes red and linked to it by a bar | capture cost, grouped vs ungrouped | 5 |
| Visual search (`search`) | is there a red T among 4, 8 or 16 letters? (feature and conjunction search) | search slopes, present vs absent | 5 |

## Notes for adapting them

* **Proportions are rows.** The go/no-go ratio, the share of valid cues, AX pairs or stop trials come from how many
  rows of each kind the trial list has (e.g. `go_no_go.csv` has three go rows and one no-go row). Add or remove rows
  to change a ratio; raise the main list's `repeats` for a longer test.
* **Random displays are recorded.** Tasks that build each display while running (attentional blink, AX-CPT,
  visual search, attentional capture) do it with *Set a variable* items, so the data hold exactly what was shown
  (`place.items`, `letters.cue_letter`, `layout.pos`, `place.bar_edge` …).
* **Stop-signal delay.** The delay goes up 50 ms after a successful stop and down 50 ms after a failed one; go
  trials leave it alone (a *Set a variable* item at the end of each trial does this, so stop and go trials can stay
  mixed in one random trial list). The thank-you screen computes the SSRT by the mean method (mean go RT minus mean
  delay); the integration method can be computed from `trials.csv`. Set the variable `stop_tone` to `true` to add a
  beep to the visual stop signal.
* **Block order.** The endogenous/exogenous task runs its two blocks in an order counterbalanced by participant
  number (`order: counterbalance`), each block's trials coming from the file named in `blocks.csv`.
* **Word lists.** The dot-probe word pairs were chosen for this library and are matched only on length; for a study,
  use a validated set for your population (keep four rows per pair so the dot is equally often at each word).
* **The capture task** (`maabrams`) is a generic additional-singleton search with a grouping manipulation, written
  from the general paradigm; it is not a replication of the exact displays of Ma and Abrams (2023).
* **Test runs** use a virtual participant who answers correctly about 90% of the time and does not race the stop
  signal, so its stop-signal numbers and effects are not meaningful, only the data layout is.
