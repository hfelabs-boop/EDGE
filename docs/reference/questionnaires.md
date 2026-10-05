# Questionnaire library

Generated from the code by `edge docs build`. Add any of these to a survey with
`{instrument: <id>}` (or **+ Questionnaire** in the builder). Scores are computed when the participant
submits and saved as data columns. See [Surveys](../SURVEYS.md) for how to build your own questions.

> All instruments listed are free to use for research. Check the wording and licence against the
> original publication before collecting data, especially for translations, clinical or commercial use.

| id | questionnaire | items | minutes | scores |
|---|---|---|---|---|
| `attention_checks` | [Attention checks (instructed response)](#attention-checks-instructed-response) | 2 | 1 | `attention_passed` |
| `demographics` | [Demographics (standard)](#demographics-standard) | 7 | 2 | — |
| `debrief` | [Funnel debriefing](#funnel-debriefing) | 4 | 2 | — |
| `consent` | [Informed consent](#informed-consent) | 1 | 1 | — |
| `gad7` | [GAD-7: anxiety symptoms](#gad-7-anxiety-symptoms) | 7 | 1 | `gad7_total` |
| `k6` | [Kessler K6: psychological distress](#kessler-k6-psychological-distress) | 6 | 1 | `k6_total` |
| `phq9` | [PHQ-9: depression symptoms](#phq-9-depression-symptoms) | 10 | 2 | `phq9_total`, `phq9_item9_flag` |
| `pss10` | [PSS-10: perceived stress](#pss-10-perceived-stress) | 10 | 2 | `pss10_total` |
| `rses` | [Rosenberg Self-Esteem Scale (RSES)](#rosenberg-self-esteem-scale-rses) | 10 | 2 | `rses_total` |
| `swls` | [Satisfaction With Life Scale (SWLS)](#satisfaction-with-life-scale-swls) | 5 | 1 | `swls_total` |
| `who5` | [WHO-5 Well-Being Index](#who-5-well-being-index) | 5 | 1 | `who5_percent` |
| `ehi_sf` | [Edinburgh Handedness Inventory: short form](#edinburgh-handedness-inventory-short-form) | 4 | 1 | `ehi_lq` |
| `mini_ipip` | [Mini-IPIP: Big Five (20 items)](#mini-ipip-big-five-20-items) | 20 | 3 | `ipip_extraversion`, `ipip_agreeableness`, `ipip_conscientiousness`, `ipip_neuroticism`, `ipip_intellect_imagination` |
| `tipi` | [TIPI: Ten-Item Personality Inventory (Big Five)](#tipi-ten-item-personality-inventory-big-five) | 10 | 1 | `tipi_extraversion`, `tipi_agreeableness`, `tipi_conscientiousness`, `tipi_emotional_stability`, `tipi_openness` |
| `kss` | [Karolinska Sleepiness Scale (KSS)](#karolinska-sleepiness-scale-kss) | 1 | 0.5 | — |
| `nasa_tlx` | [NASA-TLX: workload (raw)](#nasa-tlx-workload-raw) | 6 | 1 | `tlx_raw` |
| `nps` | [Net Promoter Score question](#net-promoter-score-question) | 2 | 0.5 | — |
| `sus` | [System Usability Scale (SUS)](#system-usability-scale-sus) | 10 | 2 | `sus_score` |
| `affect_grid` | [Valence and arousal ratings (SAM-style)](#valence-and-arousal-ratings-sam-style) | 2 | 0.5 | — |
| `audit_c` | [AUDIT-C: alcohol use](#audit-c-alcohol-use) | 3 | 1 | `audit_c_total` |

## Study logistics

### Attention checks (instructed response)

Two instructed-response items to place between questionnaire items. The data has attention_passed (0, 1 or 2). Use them as a pre-registered exclusion criterion, not post hoc.

**Use:** `{instrument: attention_checks}`  
**Cite:** Meade, A. W., & Craig, S. B. (2012). Identifying careless responses in survey data. Psychological Methods, 17(3), 437-455.  
**Licence:** Free to use.

* `attn1` (likert item): To show that you are reading carefully, please select "Strongly disagree" for this statement.
  Answers: 1 = Strongly disagree; 2 = Disagree; 3 = Neither agree nor disagree; 4 = Agree; 5 = Strongly agree
* `attn2` (single choice): This is an attention check. Please choose "Blue" from the options below.
  Answers: Red; Green; Blue; Yellow

Scores:

* `attention_passed`: Number of attention checks answered as instructed (0-2). Rule: number answered as instructed among attn1, attn2.

### Demographics (standard)

Age, gender, education, handedness, first language, country and vision. Inclusive answer options with 'prefer not to say'. Delete what you don't need.

**Use:** `{instrument: demographics}`  
**Cite:** Template (EDGE), following common reporting recommendations.  
**Licence:** Free to use and adapt.

* `age` (number): How old are you (in years)?
* `gender` (single choice): What is your gender?
  Answers: Woman; Man; Non-binary; Prefer to self-describe; Prefer not to say
* `education` (drop-down list): What is the highest level of education you have completed?
  Answers: No formal qualification; Secondary school; Vocational qualification; Bachelor's degree; Master's degree; Doctorate; Prefer not to say
* `handedness` (single choice): Which hand do you write with?
  Answers: Right; Left; Both / ambidextrous
* `first_language` (short text): What is your first language?
* `country` (short text): In which country do you currently live?
* `vision` (single choice): Do you have normal or corrected-to-normal vision?
  Answers: Yes, normal; Yes, corrected (glasses or contact lenses); No

### Funnel debriefing

Open questions asked from general to specific to probe for suspicion and demand awareness, then a seriousness check.

**Use:** `{instrument: debrief}`  
**Cite:** Bargh, J. A., & Chartrand, T. L. (2000). The mind in the middle: A practical guide to priming and automaticity research. In Reis & Judd (Eds.), Handbook of research methods in social and personality psychology (pp. 253-285). Cambridge University Press.  
**Licence:** Free to use (question wording adapted).

* `purpose` (long text (essay)): What do you think this study was about?
* `noticed` (long text (essay)): Did you notice anything unusual or anything that seemed connected between the different parts of the study?
* `strategy` (long text (essay)): Did you use any particular strategy during the task?
* `serious` (single choice): Honestly, should we use your data? (Your answer does not affect your payment.)
  Answers: 1 = Yes, I took part seriously; 0 = No, I was distracted or answered at random

### Informed consent

A consent page with an agree / do not agree choice. Replace the text with your approved information sheet. Route people who decline to the end with a workflow (see the docs).

**Use:** `{instrument: consent}`  
**Cite:** Template (EDGE).  
**Licence:** Free to use and adapt.

* `consent` (single choice): I have read and understood the information above and agree to take part.
  Answers: yes = I agree to take part; no = I do not agree

## Mental health

### GAD-7: anxiety symptoms

Seven items on generalized anxiety over the last two weeks. Total 0-21 with severity bands.

**Use:** `{instrument: gad7}`  
**Cite:** Spitzer, R. L., Kroenke, K., Williams, J. B. W., & Löwe, B. (2006). A brief measure for assessing generalized anxiety disorder: The GAD-7. Archives of Internal Medicine, 166(10), 1092-1097.  
**Licence:** No permission required to reproduce, translate, display or distribute (phqscreeners.com).

* `gad7` (matrix / likert table): Over the last 2 weeks, how often have you been bothered by the following problems?
  Answers: 0 = Not at all; 1 = Several days; 2 = More than half the days; 3 = Nearly every day
  * `gad7_1` Feeling nervous, anxious, or on edge
  * `gad7_2` Not being able to stop or control worrying
  * `gad7_3` Worrying too much about different things
  * `gad7_4` Trouble relaxing
  * `gad7_5` Being so restless that it is hard to sit still
  * `gad7_6` Becoming easily annoyed or irritable
  * `gad7_7` Feeling afraid, as if something awful might happen

Scores:

* `gad7_total`: GAD-7 total (0-21). Rule: sum of gad7_1, gad7_2, gad7_3, gad7_4, gad7_5, gad7_6, gad7_7. Bands: ≤4 minimal, ≤9 mild, ≤14 moderate, ≤21 severe

### Kessler K6: psychological distress

Six items on non-specific distress in the past 30 days. Total 0-24; 13 or more indicates serious psychological distress.

**Use:** `{instrument: k6}`  
**Cite:** Kessler, R. C., et al. (2002). Short screening scales to monitor population prevalences and trends in non-specific psychological distress. Psychological Medicine, 32(6), 959-976.  
**Licence:** Public domain (developed for the US National Health Interview Survey).

* `k6` (matrix / likert table): During the past 30 days, about how often did you feel …
  Answers: 0 = None of the time; 1 = A little of the time; 2 = Some of the time; 3 = Most of the time; 4 = All of the time
  * `k6_1` … nervous?
  * `k6_2` … hopeless?
  * `k6_3` … restless or fidgety?
  * `k6_4` … so depressed that nothing could cheer you up?
  * `k6_5` … that everything was an effort?
  * `k6_6` … worthless?

Scores:

* `k6_total`: K6 total (0-24). Rule: sum of k6_1, k6_2, k6_3, k6_4, k6_5, k6_6. Bands: ≤12 below cut-off, ≤24 serious psychological distress

### PHQ-9: depression symptoms

Nine DSM-IV depression criteria over the last two weeks, plus a functional item. Total 0-27 with severity bands. Item 9 asks about thoughts of self-harm: have a safety protocol (the data flags it as phq9_item9_flag).

**Use:** `{instrument: phq9}`  
**Cite:** Kroenke, K., Spitzer, R. L., & Williams, J. B. W. (2001). The PHQ-9: Validity of a brief depression severity measure. Journal of General Internal Medicine, 16(9), 606-613.  
**Licence:** Developed with an educational grant from Pfizer; no permission required to reproduce, translate, display or distribute (phqscreeners.com).

* `phq9` (matrix / likert table): Over the last 2 weeks, how often have you been bothered by any of the following problems?
  Answers: 0 = Not at all; 1 = Several days; 2 = More than half the days; 3 = Nearly every day
  * `phq9_1` Little interest or pleasure in doing things
  * `phq9_2` Feeling down, depressed, or hopeless
  * `phq9_3` Trouble falling or staying asleep, or sleeping too much
  * `phq9_4` Feeling tired or having little energy
  * `phq9_5` Poor appetite or overeating
  * `phq9_6` Feeling bad about yourself — or that you are a failure or have let yourself or your family down
  * `phq9_7` Trouble concentrating on things, such as reading the newspaper or watching television
  * `phq9_8` Moving or speaking so slowly that other people could have noticed? Or the opposite — being so fidgety or restless that you have been moving around a lot more than usual
  * `phq9_9` Thoughts that you would be better off dead or of hurting yourself in some way
* `phq9_difficulty` (single choice): If you checked off any problems, how difficult have these problems made it for you to do your work, take care of things at home, or get along with other people?
  Answers: 0 = Not difficult at all; 1 = Somewhat difficult; 2 = Very difficult; 3 = Extremely difficult

Scores:

* `phq9_total`: PHQ-9 total (0-27). Rule: sum of phq9_1, phq9_2, phq9_3, phq9_4, phq9_5, phq9_6, phq9_7, phq9_8, phq9_9. Bands: ≤4 minimal, ≤9 mild, ≤14 moderate, ≤19 moderately severe, ≤27 severe
* `phq9_item9_flag`: 1 if item 9 (thoughts of self-harm) was answered 'several days' or more. Rule: 1 if any of phq9_9 ≥ 1.

### PSS-10: perceived stress

How unpredictable, uncontrollable and overloaded life felt in the last month. Total 0-40; items 4, 5, 7 and 8 are reverse scored.

**Use:** `{instrument: pss10}`  
**Cite:** Cohen, S., Kamarck, T., & Mermelstein, R. (1983). A global measure of perceived stress. Journal of Health and Social Behavior, 24(4), 385-396. (10-item version: Cohen & Williamson, 1988.)  
**Licence:** Free for non-profit academic research; permission needed for commercial use.

* `pss10` (matrix / likert table): The questions in this scale ask you about your feelings and thoughts during the last month. In each case, please indicate how often you felt or thought a certain way. In the last month, how often have you …
  Answers: 0 = Never; 1 = Almost never; 2 = Sometimes; 3 = Fairly often; 4 = Very often
  * `pss10_1` … been upset because of something that happened unexpectedly?
  * `pss10_2` … felt that you were unable to control the important things in your life?
  * `pss10_3` … felt nervous and "stressed"?
  * `pss10_4` … felt confident about your ability to handle your personal problems? **(R)**
  * `pss10_5` … felt that things were going your way? **(R)**
  * `pss10_6` … found that you could not cope with all the things that you had to do?
  * `pss10_7` … been able to control irritations in your life? **(R)**
  * `pss10_8` … felt that you were on top of things? **(R)**
  * `pss10_9` … been angered because of things that were outside of your control?
  * `pss10_10` … felt difficulties were piling up so high that you could not overcome them?

Scores:

* `pss10_total`: PSS-10 total (0-40), items 4, 5, 7, 8 reversed. Rule: sum of pss10_1, pss10_2, pss10_3, pss10_4, pss10_5, pss10_6, pss10_7, pss10_8, pss10_9, pss10_10 (R) items reversed.

## Well-being and self

### Rosenberg Self-Esteem Scale (RSES)

Ten items on global self-worth, 4-point agreement scored 0-3. Total 0-30; items 2, 5, 6, 8 and 9 are reverse scored.

**Use:** `{instrument: rses}`  
**Cite:** Rosenberg, M. (1965). Society and the adolescent self-image. Princeton University Press.  
**Licence:** Free to use for research; the Rosenberg family asks for the original to be cited.

* `rses` (matrix / likert table): Below is a list of statements dealing with your general feelings about yourself. Please indicate how strongly you agree or disagree with each statement.
  Answers: 0 = Strongly disagree; 1 = Disagree; 2 = Agree; 3 = Strongly agree
  * `rses_1` On the whole, I am satisfied with myself.
  * `rses_2` At times I think I am no good at all. **(R)**
  * `rses_3` I feel that I have a number of good qualities.
  * `rses_4` I am able to do things as well as most other people.
  * `rses_5` I feel I do not have much to be proud of. **(R)**
  * `rses_6` I certainly feel useless at times. **(R)**
  * `rses_7` I feel that I'm a person of worth, at least on an equal plane with others.
  * `rses_8` I wish I could have more respect for myself. **(R)**
  * `rses_9` All in all, I am inclined to feel that I am a failure. **(R)**
  * `rses_10` I take a positive attitude toward myself.

Scores:

* `rses_total`: RSES total (0-30), items 2, 5, 6, 8, 9 reversed. Rule: sum of rses_1, rses_2, rses_3, rses_4, rses_5, rses_6, rses_7, rses_8, rses_9, rses_10 (R) items reversed.

### Satisfaction With Life Scale (SWLS)

Five items on global life satisfaction, 7-point agreement. Total 5-35 with interpretive bands.

**Use:** `{instrument: swls}`  
**Cite:** Diener, E., Emmons, R. A., Larsen, R. J., & Griffin, S. (1985). The Satisfaction With Life Scale. Journal of Personality Assessment, 49(1), 71-75.  
**Licence:** Copyrighted by the authors; free to use without permission with credit to the authors.

* `swls` (matrix / likert table): Below are five statements that you may agree or disagree with. Please indicate your agreement with each item.
  Answers: 1 = Strongly disagree; 2 = Disagree; 3 = Slightly disagree; 4 = Neither agree nor disagree; 5 = Slightly agree; 6 = Agree; 7 = Strongly agree
  * `swls_1` In most ways my life is close to my ideal.
  * `swls_2` The conditions of my life are excellent.
  * `swls_3` I am satisfied with my life.
  * `swls_4` So far I have gotten the important things I want in life.
  * `swls_5` If I could live my life over, I would change almost nothing.

Scores:

* `swls_total`: SWLS total (5-35). Rule: sum of swls_1, swls_2, swls_3, swls_4, swls_5. Bands: ≤9 extremely dissatisfied, ≤14 dissatisfied, ≤19 slightly dissatisfied, ≤20 neutral, ≤25 slightly satisfied, ≤30 satisfied, ≤35 extremely satisfied

### WHO-5 Well-Being Index

Five positively worded items about the last two weeks. Percentage score 0-100 (raw × 4); 50 or below suggests poor well-being.

**Use:** `{instrument: who5}`  
**Cite:** World Health Organization Regional Office for Europe (1998). Wellbeing measures in primary health care: The DepCare project. Topp, C. W., et al. (2015). The WHO-5 Well-Being Index: A systematic review of the literature. Psychotherapy and Psychosomatics, 84(3), 167-176.  
**Licence:** Free to use, no permission required (Psychiatric Research Unit, Mental Health Centre North Zealand).

* `who5` (matrix / likert table): Please indicate for each of the five statements which is closest to how you have been feeling over the last two weeks. Over the last two weeks …
  Answers: 5 = All of the time; 4 = Most of the time; 3 = More than half of the time; 2 = Less than half of the time; 1 = Some of the time; 0 = At no time
  * `who5_1` I have felt cheerful and in good spirits
  * `who5_2` I have felt calm and relaxed
  * `who5_3` I have felt active and vigorous
  * `who5_4` I woke up feeling fresh and rested
  * `who5_5` My daily life has been filled with things that interest me

Scores:

* `who5_percent`: WHO-5 percentage score (0-100). Rule: sum of who5_1, who5_2, who5_3, who5_4, who5_5, × 4. Bands: ≤28 likely depression (screen further), ≤50 poor well-being, ≤100 adequate well-being

## Personality

### Edinburgh Handedness Inventory: short form

Four everyday actions. Laterality quotient from -100 (fully left) to +100 (fully right); above 60 is usually classed as right-handed, below -60 left-handed.

**Use:** `{instrument: ehi_sf}`  
**Cite:** Veale, J. F. (2014). Edinburgh Handedness Inventory – Short Form: A revised version based on confirmatory factor analysis. Laterality, 19(2), 164-177. (After Oldfield, 1971.)  
**Licence:** Free to use for research.

* `ehi` (matrix / likert table): Please indicate which hand you prefer for each of these activities.
  Answers: -100 = Always left; -50 = Usually left; 0 = Both equally; 50 = Usually right; 100 = Always right
  * `ehi_1` Writing
  * `ehi_2` Throwing
  * `ehi_3` Toothbrush
  * `ehi_4` Spoon

Scores:

* `ehi_lq`: Laterality quotient (-100 left to +100 right). Rule: mean of ehi_1, ehi_2, ehi_3, ehi_4. Bands: ≤-61 left-handed, ≤60 mixed-handed, ≤100 right-handed

### Mini-IPIP: Big Five (20 items)

Four items per Big Five trait from the International Personality Item Pool, 5-point accuracy scale. Trait scores are sums (4-20).

**Use:** `{instrument: mini_ipip}`  
**Cite:** Donnellan, M. B., Oswald, F. L., Baird, B. M., & Lucas, R. E. (2006). The Mini-IPIP scales: Tiny-yet-effective measures of the Big Five factors of personality. Psychological Assessment, 18(2), 192-203.  
**Licence:** Public domain (IPIP items, ipip.ori.org).

* `mini_ipip` (matrix / likert table): Describe yourself as you generally are now, not as you wish to be in the future. Describe yourself as you honestly see yourself, in relation to other people you know of the same sex as you are, and roughly your same age.
  Answers: 1 = Very inaccurate; 2 = Moderately inaccurate; 3 = Neither accurate nor inaccurate; 4 = Moderately accurate; 5 = Very accurate
  * `ipip_1` Am the life of the party.
  * `ipip_2` Sympathize with others' feelings.
  * `ipip_3` Get chores done right away.
  * `ipip_4` Have frequent mood swings.
  * `ipip_5` Have a vivid imagination.
  * `ipip_6` Don't talk a lot. **(R)**
  * `ipip_7` Am not interested in other people's problems. **(R)**
  * `ipip_8` Often forget to put things back in their proper place. **(R)**
  * `ipip_9` Am relaxed most of the time. **(R)**
  * `ipip_10` Am not interested in abstract ideas. **(R)**
  * `ipip_11` Talk to a lot of different people at parties.
  * `ipip_12` Feel others' emotions.
  * `ipip_13` Like order.
  * `ipip_14` Get upset easily.
  * `ipip_15` Have difficulty understanding abstract ideas. **(R)**
  * `ipip_16` Keep in the background. **(R)**
  * `ipip_17` Am not really interested in others. **(R)**
  * `ipip_18` Make a mess of things. **(R)**
  * `ipip_19` Seldom feel blue. **(R)**
  * `ipip_20` Do not have a good imagination. **(R)**

Scores:

* `ipip_extraversion`: Mini-IPIP extraversion (4-20). Rule: sum of ipip_1, ipip_6, ipip_11, ipip_16 (R) items reversed.
* `ipip_agreeableness`: Mini-IPIP agreeableness (4-20). Rule: sum of ipip_2, ipip_7, ipip_12, ipip_17 (R) items reversed.
* `ipip_conscientiousness`: Mini-IPIP conscientiousness (4-20). Rule: sum of ipip_3, ipip_8, ipip_13, ipip_18 (R) items reversed.
* `ipip_neuroticism`: Mini-IPIP neuroticism (4-20). Rule: sum of ipip_4, ipip_9, ipip_14, ipip_19 (R) items reversed.
* `ipip_intellect_imagination`: Mini-IPIP intellect/imagination (4-20). Rule: sum of ipip_5, ipip_10, ipip_15, ipip_20 (R) items reversed.

### TIPI: Ten-Item Personality Inventory (Big Five)

Two items per Big Five trait, 7-point agreement. Trait scores are the mean of the two items (one reversed). Very short: for when time is tight, not for individual assessment.

**Use:** `{instrument: tipi}`  
**Cite:** Gosling, S. D., Rentfrow, P. J., & Swann, W. B., Jr. (2003). A very brief measure of the Big-Five personality domains. Journal of Research in Personality, 37(6), 504-528.  
**Licence:** Free for non-commercial research (the authors' website).

* `tipi` (matrix / likert table): Here are a number of personality traits that may or may not apply to you. Please indicate the extent to which you agree or disagree with each statement. You should rate the extent to which the pair of traits applies to you, even if one characteristic applies more strongly than the other. I see myself as:
  Answers: 1 = Disagree strongly; 2 = Disagree moderately; 3 = Disagree a little; 4 = Neither agree nor disagree; 5 = Agree a little; 6 = Agree moderately; 7 = Agree strongly
  * `tipi_1` Extraverted, enthusiastic.
  * `tipi_2` Critical, quarrelsome. **(R)**
  * `tipi_3` Dependable, self-disciplined.
  * `tipi_4` Anxious, easily upset. **(R)**
  * `tipi_5` Open to new experiences, complex.
  * `tipi_6` Reserved, quiet. **(R)**
  * `tipi_7` Sympathetic, warm.
  * `tipi_8` Disorganized, careless. **(R)**
  * `tipi_9` Calm, emotionally stable.
  * `tipi_10` Conventional, uncreative. **(R)**

Scores:

* `tipi_extraversion`: TIPI Extraversion (1-7). Rule: mean of tipi_1, tipi_6 (R) items reversed.
* `tipi_agreeableness`: TIPI Agreeableness (1-7). Rule: mean of tipi_2, tipi_7 (R) items reversed.
* `tipi_conscientiousness`: TIPI Conscientiousness (1-7). Rule: mean of tipi_3, tipi_8 (R) items reversed.
* `tipi_emotional_stability`: TIPI Emotional Stability (1-7). Rule: mean of tipi_4, tipi_9 (R) items reversed.
* `tipi_openness`: TIPI Openness (1-7). Rule: mean of tipi_5, tipi_10 (R) items reversed.

## Task experience

### Karolinska Sleepiness Scale (KSS)

One 9-point rating of sleepiness in the last 10 minutes. Often repeated before and after tasks.

**Use:** `{instrument: kss}`  
**Cite:** Åkerstedt, T., & Gillberg, M. (1990). Subjective and objective sleepiness in the active individual. International Journal of Neuroscience, 52(1-2), 29-37.  
**Licence:** Free to use.

* `kss` (single choice): Please indicate your sleepiness during the last 10 minutes.
  Answers: 1 = 1 – Extremely alert; 2 = 2 – Very alert; 3 = 3 – Alert; 4 = 4 – Rather alert; 5 = 5 – Neither alert nor sleepy; 6 = 6 – Some signs of sleepiness; 7 = 7 – Sleepy, but no effort to keep awake; 8 = 8 – Sleepy, some effort to keep awake; 9 = 9 – Very sleepy, great effort to keep awake, fighting sleep

### NASA-TLX: workload (raw)

Six workload dimensions rated on 0-100 sliders after a task. Raw TLX is their mean (performance runs from perfect to failure, so higher always means more workload).

**Use:** `{instrument: nasa_tlx}`  
**Cite:** Hart, S. G., & Staveland, L. E. (1988). Development of NASA-TLX (Task Load Index): Results of empirical and theoretical research. Advances in Psychology, 52, 139-183. Raw TLX: Hart (2006).  
**Licence:** Public domain (NASA Ames Research Center).

* `tlx_mental` (slider / visual analogue scale): Mental demand: How mentally demanding was the task?
  0-100, labels: Very low / Very high
* `tlx_physical` (slider / visual analogue scale): Physical demand: How physically demanding was the task?
  0-100, labels: Very low / Very high
* `tlx_temporal` (slider / visual analogue scale): Temporal demand: How hurried or rushed was the pace of the task?
  0-100, labels: Very low / Very high
* `tlx_performance` (slider / visual analogue scale): Performance: How successful were you in accomplishing what you were asked to do?
  0-100, labels: Perfect / Failure
* `tlx_effort` (slider / visual analogue scale): Effort: How hard did you have to work to accomplish your level of performance?
  0-100, labels: Very low / Very high
* `tlx_frustration` (slider / visual analogue scale): Frustration: How insecure, discouraged, irritated, stressed, and annoyed were you?
  0-100, labels: Very low / Very high

Scores:

* `tlx_raw`: Raw NASA-TLX (0-100). Rule: mean of tlx_mental, tlx_physical, tlx_temporal, tlx_performance, tlx_effort, tlx_frustration.

### Net Promoter Score question

The 0-10 'how likely are you to recommend' question with a follow-up reason.

**Use:** `{instrument: nps}`  
**Cite:** Reichheld, F. F. (2003). The one number you need to grow. Harvard Business Review, 81(12), 46-54.  
**Licence:** Free to use (Net Promoter is a trademark of Bain & Company, Satmetrix and Fred Reichheld).

* `nps` (net promoter (0-10)): How likely are you to recommend this study to a friend or colleague?
  Answers: 0; 1; 2; 3; 4; 5; 6; 7; 8; 9; 10
* `nps_reason` (long text (essay)): What is the main reason for your score?

### System Usability Scale (SUS)

Ten alternating positive and negative items on usability. Score 0-100 (68 is about average).

**Use:** `{instrument: sus}`  
**Cite:** Brooke, J. (1996). SUS: A 'quick and dirty' usability scale. In Jordan et al. (Eds.), Usability Evaluation in Industry (pp. 189-194). Taylor & Francis.  
**Licence:** Free to use with acknowledgement of the source.

* `sus` (matrix / likert table): Please rate your agreement with each statement about the system you just used.
  Answers: 0 = Strongly disagree; 1 = Disagree; 2 = Neutral; 3 = Agree; 4 = Strongly agree
  * `sus_1` I think that I would like to use this system frequently.
  * `sus_2` I found the system unnecessarily complex. **(R)**
  * `sus_3` I thought the system was easy to use.
  * `sus_4` I think that I would need the support of a technical person to be able to use this system. **(R)**
  * `sus_5` I found the various functions in this system were well integrated.
  * `sus_6` I thought there was too much inconsistency in this system. **(R)**
  * `sus_7` I would imagine that most people would learn to use this system very quickly.
  * `sus_8` I found the system very cumbersome to use. **(R)**
  * `sus_9` I felt very confident using the system.
  * `sus_10` I needed to learn a lot of things before I could get going with this system. **(R)**

Scores:

* `sus_score`: SUS score (0-100). Rule: sum of sus_1, sus_2, sus_3, sus_4, sus_5, sus_6, sus_7, sus_8, sus_9, sus_10 (R) items reversed, × 2.5.

### Valence and arousal ratings (SAM-style)

Two 9-point ratings of how pleasant and how activated the participant feels, as used with the Self-Assessment Manikin (text anchors instead of the manikin pictures). Use after each stimulus or block.

**Use:** `{instrument: affect_grid}`  
**Cite:** Bradley, M. M., & Lang, P. J. (1994). Measuring emotion: The Self-Assessment Manikin and the semantic differential. Journal of Behavior Therapy and Experimental Psychiatry, 25(1), 49-59.  
**Licence:** Text-anchored ratings, free to use. (The SAM pictures themselves are distributed by the authors.)

* `valence` (numbered scale (1-n)): How do you feel right now?
  Answers: 1; 2; 3; 4; 5; 6; 7; 8; 9
* `arousal` (numbered scale (1-n)): How calm or excited do you feel right now?
  Answers: 1; 2; 3; 4; 5; 6; 7; 8; 9

## Health behaviour

### AUDIT-C: alcohol use

The three consumption items of the WHO AUDIT. Total 0-12; common screening cut-offs are 4 or more for men and 3 or more for women.

**Use:** `{instrument: audit_c}`  
**Cite:** Bush, K., Kivlahan, D. R., McDonell, M. B., Fihn, S. D., & Bradley, K. A. (1998). The AUDIT alcohol consumption questions (AUDIT-C). Archives of Internal Medicine, 158(16), 1789-1795.  
**Licence:** Public domain (World Health Organization AUDIT; US Department of Veterans Affairs).

* `audit_1` (single choice): How often do you have a drink containing alcohol?
  Answers: 0 = Never; 1 = Monthly or less; 2 = 2-4 times a month; 3 = 2-3 times a week; 4 = 4 or more times a week
* `audit_2` (single choice): How many standard drinks containing alcohol do you have on a typical day? *(shown if {'audit_1': {'!=': 0}})*
  Answers: 0 = 1 or 2; 1 = 3 or 4; 2 = 5 or 6; 3 = 7 to 9; 4 = 10 or more
* `audit_3` (single choice): How often do you have six or more drinks on one occasion? *(shown if {'audit_1': {'!=': 0}})*
  Answers: 0 = Never; 1 = Less than monthly; 2 = Monthly; 3 = Weekly; 4 = Daily or almost daily

Scores:

* `audit_c_total`: AUDIT-C total (0-12); skipped items count 0. Rule: sum of audit_1, audit_2, audit_3.

## Answer scales

Use `scale: <name>` on single, likert and matrix questions.

| name | scale | answers (saved value = label) |
|---|---|---|
| `agree5` | Agreement (5 points) | 1 = Strongly disagree; 2 = Disagree; 3 = Neither agree nor disagree; 4 = Agree; 5 = Strongly agree |
| `agree7` | Agreement (7 points) | 1 = Strongly disagree; 2 = Disagree; 3 = Somewhat disagree; 4 = Neither agree nor disagree; 5 = Somewhat agree; 6 = Agree; 7 = Strongly agree |
| `agree4` | Agreement (4 points, no middle) | 1 = Strongly disagree; 2 = Disagree; 3 = Agree; 4 = Strongly agree |
| `agree6` | Agreement (6 points, no middle) | 1 = Strongly disagree; 2 = Disagree; 3 = Slightly disagree; 4 = Slightly agree; 5 = Agree; 6 = Strongly agree |
| `frequency5` | Frequency (never … always) | 1 = Never; 2 = Rarely; 3 = Sometimes; 4 = Often; 5 = Always |
| `satisfaction5` | Satisfaction | 1 = Very dissatisfied; 2 = Dissatisfied; 3 = Neither satisfied nor dissatisfied; 4 = Satisfied; 5 = Very satisfied |
| `likelihood5` | Likelihood | 1 = Very unlikely; 2 = Unlikely; 3 = Neither likely nor unlikely; 4 = Likely; 5 = Very likely |
| `importance5` | Importance | 1 = Not at all important; 2 = Slightly important; 3 = Moderately important; 4 = Very important; 5 = Extremely important |
| `quality5` | Quality (very poor … excellent) | 1 = Very poor; 2 = Poor; 3 = Fair; 4 = Good; 5 = Excellent |
| `extent5` | Extent (not at all … extremely) | 1 = Not at all; 2 = A little; 3 = Moderately; 4 = Quite a bit; 5 = Extremely |
| `accuracy5` | Self-description accuracy | 1 = Very inaccurate; 2 = Moderately inaccurate; 3 = Neither accurate nor inaccurate; 4 = Moderately accurate; 5 = Very accurate |
| `confidence5` | Confidence | 1 = Not at all confident; 2 = Slightly confident; 3 = Somewhat confident; 4 = Very confident; 5 = Completely confident |
| `difficulty5` | Difficulty | 1 = Very easy; 2 = Easy; 3 = Neither easy nor difficult; 4 = Difficult; 5 = Very difficult |
| `yesno` | Yes / No | 1 = Yes; 0 = No |
| `yesnounsure` | Yes / No / Not sure | 1 = Yes; 0 = No; -1 = Not sure |
| `truefalse` | True / False | 1 = True; 0 = False |
