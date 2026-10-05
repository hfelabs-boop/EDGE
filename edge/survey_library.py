"""Ready-made questionnaires and question blocks for the ``survey`` component.

Every instrument here is free to use for research (public domain, or released by its authors for
non-commercial research use without permission). Each entry records the citation, the licence note
and the scoring rule, and the items are reproduced as published. **Check the wording and the licence
against the original publication before you collect data**, especially for translations, clinical or
commercial use. Instruments that are copyrighted or sold (BDI-II, STAI, PANAS, NEO, MMPI …) are
deliberately not included.

Use them in an experiment with ``{instrument: phq9}`` inside a survey's ``questions`` list.
"""

from __future__ import annotations

import copy
from typing import Any

# ------------------------------------------------------------------------------------------ scales
# Answer scales shared by many questions. Each option is (value, label); values are what is saved.
SCALES: dict[str, list[tuple[Any, str]]] = {
    "agree5": [(1, "Strongly disagree"), (2, "Disagree"), (3, "Neither agree nor disagree"), (4, "Agree"),
               (5, "Strongly agree")],
    "agree7": [(1, "Strongly disagree"), (2, "Disagree"), (3, "Somewhat disagree"), (4, "Neither agree nor disagree"),
               (5, "Somewhat agree"), (6, "Agree"), (7, "Strongly agree")],
    "agree4": [(1, "Strongly disagree"), (2, "Disagree"), (3, "Agree"), (4, "Strongly agree")],
    "agree6": [(1, "Strongly disagree"), (2, "Disagree"), (3, "Slightly disagree"), (4, "Slightly agree"),
               (5, "Agree"), (6, "Strongly agree")],
    "frequency5": [(1, "Never"), (2, "Rarely"), (3, "Sometimes"), (4, "Often"), (5, "Always")],
    "satisfaction5": [(1, "Very dissatisfied"), (2, "Dissatisfied"), (3, "Neither satisfied nor dissatisfied"),
                      (4, "Satisfied"), (5, "Very satisfied")],
    "likelihood5": [(1, "Very unlikely"), (2, "Unlikely"), (3, "Neither likely nor unlikely"), (4, "Likely"),
                    (5, "Very likely")],
    "importance5": [(1, "Not at all important"), (2, "Slightly important"), (3, "Moderately important"),
                    (4, "Very important"), (5, "Extremely important")],
    "quality5": [(1, "Very poor"), (2, "Poor"), (3, "Fair"), (4, "Good"), (5, "Excellent")],
    "extent5": [(1, "Not at all"), (2, "A little"), (3, "Moderately"), (4, "Quite a bit"), (5, "Extremely")],
    "accuracy5": [(1, "Very inaccurate"), (2, "Moderately inaccurate"), (3, "Neither accurate nor inaccurate"),
                  (4, "Moderately accurate"), (5, "Very accurate")],
    "confidence5": [(1, "Not at all confident"), (2, "Slightly confident"), (3, "Somewhat confident"),
                    (4, "Very confident"), (5, "Completely confident")],
    "difficulty5": [(1, "Very easy"), (2, "Easy"), (3, "Neither easy nor difficult"), (4, "Difficult"),
                    (5, "Very difficult")],
    "yesno": [(1, "Yes"), (0, "No")],
    "yesnounsure": [(1, "Yes"), (0, "No"), (-1, "Not sure")],
    "truefalse": [(1, "True"), (0, "False")],
}

SCALE_TITLES = {
    "agree5": "Agreement (5 points)", "agree7": "Agreement (7 points)", "agree4": "Agreement (4 points, no middle)",
    "agree6": "Agreement (6 points, no middle)", "frequency5": "Frequency (never … always)",
    "satisfaction5": "Satisfaction", "likelihood5": "Likelihood", "importance5": "Importance",
    "quality5": "Quality (very poor … excellent)", "extent5": "Extent (not at all … extremely)",
    "accuracy5": "Self-description accuracy", "confidence5": "Confidence", "difficulty5": "Difficulty",
    "yesno": "Yes / No", "yesnounsure": "Yes / No / Not sure", "truefalse": "True / False",
}


def scale_options(name: str) -> list[dict[str, Any]]:
    if name not in SCALES:
        raise KeyError(f"unknown scale '{name}' (available: {', '.join(SCALES)})")
    return [{"value": v, "label": lab} for v, lab in SCALES[name]]


def _opts(pairs: list[tuple[Any, str]]) -> list[dict[str, Any]]:
    return [{"value": v, "label": lab} for v, lab in pairs]


def _items(prefix: str, texts: list[str], reverse: set[int] = frozenset()) -> list[dict[str, Any]]:
    return [{"id": f"{prefix}{i}", "text": t, **({"reverse": True} if i in reverse else {})}
            for i, t in enumerate(texts, 1)]


# ------------------------------------------------------------------------------------------ instruments
_PHQ_SCALE = _opts([(0, "Not at all"), (1, "Several days"), (2, "More than half the days"), (3, "Nearly every day")])

INSTRUMENTS: dict[str, dict[str, Any]] = {}


def _add(key: str, **entry: Any) -> None:
    entry.setdefault("id", key)
    INSTRUMENTS[key] = entry


# ---- study logistics ----------------------------------------------------------------------------
_add("consent", title="Informed consent", category="Study logistics", minutes=1,
     description="A consent page with an agree / do not agree choice. Replace the text with your approved "
                 "information sheet. Route people who decline to the end with a workflow (see the docs).",
     citation="Template (EDGE).", licence="Free to use and adapt.",
     questions=[
         {"id": "consent_text", "type": "text_block",
          "text": "<h2>Information and consent</h2><p>Replace this text with the information sheet approved by your "
                  "ethics committee: purpose, procedure, duration, risks, data protection, voluntary participation "
                  "and the right to withdraw at any time without giving a reason, and contact details.</p>"},
         {"id": "consent", "type": "single", "required": True, "test_answer": "yes",
          "text": "I have read and understood the information above and agree to take part.",
          "options": [{"value": "yes", "label": "I agree to take part"},
                      {"value": "no", "label": "I do not agree"}]}])

_add("demographics", title="Demographics (standard)", category="Study logistics", minutes=2,
     description="Age, gender, education, handedness, first language, country and vision. Inclusive answer "
                 "options with 'prefer not to say'. Delete what you don't need.",
     citation="Template (EDGE), following common reporting recommendations.", licence="Free to use and adapt.",
     questions=[
         {"id": "age", "type": "number", "text": "How old are you (in years)?", "min": 16, "max": 110,
          "required": True},
         {"id": "gender", "type": "single", "text": "What is your gender?", "required": True,
          "options": ["Woman", "Man", "Non-binary", "Prefer to self-describe", "Prefer not to say"],
          "other_option": "Prefer to self-describe"},
         {"id": "education", "type": "dropdown", "text": "What is the highest level of education you have completed?",
          "options": ["No formal qualification", "Secondary school", "Vocational qualification", "Bachelor's degree",
                      "Master's degree", "Doctorate", "Prefer not to say"]},
         {"id": "handedness", "type": "single", "text": "Which hand do you write with?",
          "options": ["Right", "Left", "Both / ambidextrous"], "layout": "horizontal"},
         {"id": "first_language", "type": "text", "text": "What is your first language?"},
         {"id": "country", "type": "text", "text": "In which country do you currently live?"},
         {"id": "vision", "type": "single", "text": "Do you have normal or corrected-to-normal vision?",
          "options": ["Yes, normal", "Yes, corrected (glasses or contact lenses)", "No"]}])

_add("attention_checks", title="Attention checks (instructed response)", category="Study logistics", minutes=1,
     description="Two instructed-response items to place between questionnaire items. The data has "
                 "attention_passed (0, 1 or 2). Use them as a pre-registered exclusion criterion, not post hoc.",
     citation="Meade, A. W., & Craig, S. B. (2012). Identifying careless responses in survey data. "
              "Psychological Methods, 17(3), 437-455.",
     licence="Free to use.",
     questions=[
         {"id": "attn1", "type": "likert", "scale": "agree5", "required": True,
          "text": "To show that you are reading carefully, please select \"Strongly disagree\" for this statement.",
          "correct": 1},
         {"id": "attn2", "type": "single", "required": True,
          "text": "This is an attention check. Please choose \"Blue\" from the options below.",
          "options": ["Red", "Green", "Blue", "Yellow"], "correct": "Blue", "randomize": True}],
     scores={"attention_passed": {"correct": ["attn1", "attn2"],
                                  "description": "Number of attention checks answered as instructed (0-2)"}})

_add("debrief", title="Funnel debriefing", category="Study logistics", minutes=2,
     description="Open questions asked from general to specific to probe for suspicion and demand awareness, "
                 "then a seriousness check.",
     citation="Bargh, J. A., & Chartrand, T. L. (2000). The mind in the middle: A practical guide to priming and "
              "automaticity research. In Reis & Judd (Eds.), Handbook of research methods in social and "
              "personality psychology (pp. 253-285). Cambridge University Press.",
     licence="Free to use (question wording adapted).",
     questions=[
         {"id": "purpose", "type": "essay", "text": "What do you think this study was about?"},
         {"id": "noticed", "type": "essay", "text": "Did you notice anything unusual or anything that seemed connected "
                                                    "between the different parts of the study?"},
         {"id": "strategy", "type": "essay", "text": "Did you use any particular strategy during the task?"},
         {"id": "serious", "type": "single", "required": True,
          "text": "Honestly, should we use your data? (Your answer does not affect your payment.)",
          "options": [{"value": 1, "label": "Yes, I took part seriously"},
                      {"value": 0, "label": "No, I was distracted or answered at random"}]}])

# ---- mood, anxiety, distress --------------------------------------------------------------------
_add("phq9", title="PHQ-9: depression symptoms", category="Mental health", minutes=2,
     description="Nine DSM-IV depression criteria over the last two weeks, plus a functional item. Total 0-27 "
                 "with severity bands. Item 9 asks about thoughts of self-harm: have a safety protocol "
                 "(the data flags it as phq9_item9_flag).",
     citation="Kroenke, K., Spitzer, R. L., & Williams, J. B. W. (2001). The PHQ-9: Validity of a brief "
              "depression severity measure. Journal of General Internal Medicine, 16(9), 606-613.",
     licence="Developed with an educational grant from Pfizer; no permission required to reproduce, translate, "
             "display or distribute (phqscreeners.com).",
     questions=[
         {"id": "phq9", "type": "matrix", "required": True, "options": _PHQ_SCALE,
          "text": "Over the last 2 weeks, how often have you been bothered by any of the following problems?",
          "items": _items("phq9_", [
              "Little interest or pleasure in doing things",
              "Feeling down, depressed, or hopeless",
              "Trouble falling or staying asleep, or sleeping too much",
              "Feeling tired or having little energy",
              "Poor appetite or overeating",
              "Feeling bad about yourself — or that you are a failure or have let yourself or your family down",
              "Trouble concentrating on things, such as reading the newspaper or watching television",
              "Moving or speaking so slowly that other people could have noticed? Or the opposite — being so "
              "fidgety or restless that you have been moving around a lot more than usual",
              "Thoughts that you would be better off dead or of hurting yourself in some way"])},
         {"id": "phq9_difficulty", "type": "single",
          "text": "If you checked off any problems, how difficult have these problems made it for you to do your "
                  "work, take care of things at home, or get along with other people?",
          "options": _opts([(0, "Not difficult at all"), (1, "Somewhat difficult"), (2, "Very difficult"),
                            (3, "Extremely difficult")])}],
     scores={"phq9_total": {"items": [f"phq9_{i}" for i in range(1, 10)], "method": "sum",
                            "bands": [[4, "minimal"], [9, "mild"], [14, "moderate"], [19, "moderately severe"],
                                      [27, "severe"]],
                            "description": "PHQ-9 total (0-27)"},
             "phq9_item9_flag": {"items": ["phq9_9"], "method": "flag", "threshold": 1,
                                 "description": "1 if item 9 (thoughts of self-harm) was answered 'several days' or more"}})

_add("gad7", title="GAD-7: anxiety symptoms", category="Mental health", minutes=1,
     description="Seven items on generalized anxiety over the last two weeks. Total 0-21 with severity bands.",
     citation="Spitzer, R. L., Kroenke, K., Williams, J. B. W., & Löwe, B. (2006). A brief measure for assessing "
              "generalized anxiety disorder: The GAD-7. Archives of Internal Medicine, 166(10), 1092-1097.",
     licence="No permission required to reproduce, translate, display or distribute (phqscreeners.com).",
     questions=[
         {"id": "gad7", "type": "matrix", "required": True, "options": _PHQ_SCALE,
          "text": "Over the last 2 weeks, how often have you been bothered by the following problems?",
          "items": _items("gad7_", [
              "Feeling nervous, anxious, or on edge",
              "Not being able to stop or control worrying",
              "Worrying too much about different things",
              "Trouble relaxing",
              "Being so restless that it is hard to sit still",
              "Becoming easily annoyed or irritable",
              "Feeling afraid, as if something awful might happen"])}],
     scores={"gad7_total": {"items": [f"gad7_{i}" for i in range(1, 8)], "method": "sum",
                            "bands": [[4, "minimal"], [9, "mild"], [14, "moderate"], [21, "severe"]],
                            "description": "GAD-7 total (0-21)"}})

_add("k6", title="Kessler K6: psychological distress", category="Mental health", minutes=1,
     description="Six items on non-specific distress in the past 30 days. Total 0-24; 13 or more indicates "
                 "serious psychological distress.",
     citation="Kessler, R. C., et al. (2002). Short screening scales to monitor population prevalences and trends "
              "in non-specific psychological distress. Psychological Medicine, 32(6), 959-976.",
     licence="Public domain (developed for the US National Health Interview Survey).",
     questions=[
         {"id": "k6", "type": "matrix", "required": True,
          "options": _opts([(0, "None of the time"), (1, "A little of the time"), (2, "Some of the time"),
                            (3, "Most of the time"), (4, "All of the time")]),
          "text": "During the past 30 days, about how often did you feel …",
          "items": _items("k6_", ["… nervous?", "… hopeless?", "… restless or fidgety?",
                                  "… so depressed that nothing could cheer you up?", "… that everything was an effort?",
                                  "… worthless?"])}],
     scores={"k6_total": {"items": [f"k6_{i}" for i in range(1, 7)], "method": "sum",
                          "bands": [[12, "below cut-off"], [24, "serious psychological distress"]],
                          "description": "K6 total (0-24)"}})

_add("pss10", title="PSS-10: perceived stress", category="Mental health", minutes=2,
     description="How unpredictable, uncontrollable and overloaded life felt in the last month. Total 0-40; "
                 "items 4, 5, 7 and 8 are reverse scored.",
     citation="Cohen, S., Kamarck, T., & Mermelstein, R. (1983). A global measure of perceived stress. Journal of "
              "Health and Social Behavior, 24(4), 385-396. (10-item version: Cohen & Williamson, 1988.)",
     licence="Free for non-profit academic research; permission needed for commercial use.",
     questions=[
         {"id": "pss10", "type": "matrix", "required": True,
          "options": _opts([(0, "Never"), (1, "Almost never"), (2, "Sometimes"), (3, "Fairly often"), (4, "Very often")]),
          "text": "The questions in this scale ask you about your feelings and thoughts during the last month. In "
                  "each case, please indicate how often you felt or thought a certain way. In the last month, how "
                  "often have you …",
          "items": _items("pss10_", [
              "… been upset because of something that happened unexpectedly?",
              "… felt that you were unable to control the important things in your life?",
              "… felt nervous and \"stressed\"?",
              "… felt confident about your ability to handle your personal problems?",
              "… felt that things were going your way?",
              "… found that you could not cope with all the things that you had to do?",
              "… been able to control irritations in your life?",
              "… felt that you were on top of things?",
              "… been angered because of things that were outside of your control?",
              "… felt difficulties were piling up so high that you could not overcome them?"], {4, 5, 7, 8})}],
     scores={"pss10_total": {"items": [f"pss10_{i}" for i in range(1, 11)], "method": "sum",
                             "description": "PSS-10 total (0-40), items 4, 5, 7, 8 reversed"}})

# ---- well-being, self -----------------------------------------------------------------------------
_add("who5", title="WHO-5 Well-Being Index", category="Well-being and self", minutes=1,
     description="Five positively worded items about the last two weeks. Percentage score 0-100 (raw × 4); "
                 "50 or below suggests poor well-being.",
     citation="World Health Organization Regional Office for Europe (1998). Wellbeing measures in primary health "
              "care: The DepCare project. Topp, C. W., et al. (2015). The WHO-5 Well-Being Index: A systematic "
              "review of the literature. Psychotherapy and Psychosomatics, 84(3), 167-176.",
     licence="Free to use, no permission required (Psychiatric Research Unit, Mental Health Centre North Zealand).",
     questions=[
         {"id": "who5", "type": "matrix", "required": True,
          "options": _opts([(5, "All of the time"), (4, "Most of the time"), (3, "More than half of the time"),
                            (2, "Less than half of the time"), (1, "Some of the time"), (0, "At no time")]),
          "text": "Please indicate for each of the five statements which is closest to how you have been feeling "
                  "over the last two weeks. Over the last two weeks …",
          "items": _items("who5_", ["I have felt cheerful and in good spirits", "I have felt calm and relaxed",
                                    "I have felt active and vigorous", "I woke up feeling fresh and rested",
                                    "My daily life has been filled with things that interest me"])}],
     scores={"who5_percent": {"items": [f"who5_{i}" for i in range(1, 6)], "method": "sum", "multiply": 4,
                              "bands": [[28, "likely depression (screen further)"], [50, "poor well-being"],
                                        [100, "adequate well-being"]],
                              "description": "WHO-5 percentage score (0-100)"}})

_add("swls", title="Satisfaction With Life Scale (SWLS)", category="Well-being and self", minutes=1,
     description="Five items on global life satisfaction, 7-point agreement. Total 5-35 with interpretive bands.",
     citation="Diener, E., Emmons, R. A., Larsen, R. J., & Griffin, S. (1985). The Satisfaction With Life Scale. "
              "Journal of Personality Assessment, 49(1), 71-75.",
     licence="Copyrighted by the authors; free to use without permission with credit to the authors.",
     questions=[
         {"id": "swls", "type": "matrix", "required": True,
          "options": _opts([(1, "Strongly disagree"), (2, "Disagree"), (3, "Slightly disagree"),
                            (4, "Neither agree nor disagree"), (5, "Slightly agree"), (6, "Agree"), (7, "Strongly agree")]),
          "text": "Below are five statements that you may agree or disagree with. Please indicate your agreement "
                  "with each item.",
          "items": _items("swls_", ["In most ways my life is close to my ideal.", "The conditions of my life are excellent.",
                                    "I am satisfied with my life.",
                                    "So far I have gotten the important things I want in life.",
                                    "If I could live my life over, I would change almost nothing."])}],
     scores={"swls_total": {"items": [f"swls_{i}" for i in range(1, 6)], "method": "sum",
                            "bands": [[9, "extremely dissatisfied"], [14, "dissatisfied"], [19, "slightly dissatisfied"],
                                      [20, "neutral"], [25, "slightly satisfied"], [30, "satisfied"],
                                      [35, "extremely satisfied"]],
                            "description": "SWLS total (5-35)"}})

_add("rses", title="Rosenberg Self-Esteem Scale (RSES)", category="Well-being and self", minutes=2,
     description="Ten items on global self-worth, 4-point agreement scored 0-3. Total 0-30; items 2, 5, 6, 8 and 9 "
                 "are reverse scored.",
     citation="Rosenberg, M. (1965). Society and the adolescent self-image. Princeton University Press.",
     licence="Free to use for research; the Rosenberg family asks for the original to be cited.",
     questions=[
         {"id": "rses", "type": "matrix", "required": True,
          "options": _opts([(0, "Strongly disagree"), (1, "Disagree"), (2, "Agree"), (3, "Strongly agree")]),
          "text": "Below is a list of statements dealing with your general feelings about yourself. Please indicate "
                  "how strongly you agree or disagree with each statement.",
          "items": _items("rses_", [
              "On the whole, I am satisfied with myself.", "At times I think I am no good at all.",
              "I feel that I have a number of good qualities.", "I am able to do things as well as most other people.",
              "I feel I do not have much to be proud of.", "I certainly feel useless at times.",
              "I feel that I'm a person of worth, at least on an equal plane with others.",
              "I wish I could have more respect for myself.", "All in all, I am inclined to feel that I am a failure.",
              "I take a positive attitude toward myself."], {2, 5, 6, 8, 9})}],
     scores={"rses_total": {"items": [f"rses_{i}" for i in range(1, 11)], "method": "sum",
                            "description": "RSES total (0-30), items 2, 5, 6, 8, 9 reversed"}})

# ---- personality ----------------------------------------------------------------------------------
_TIPI = ["Extraverted, enthusiastic.", "Critical, quarrelsome.", "Dependable, self-disciplined.",
         "Anxious, easily upset.", "Open to new experiences, complex.", "Reserved, quiet.", "Sympathetic, warm.",
         "Disorganized, careless.", "Calm, emotionally stable.", "Conventional, uncreative."]
_add("tipi", title="TIPI: Ten-Item Personality Inventory (Big Five)", category="Personality", minutes=1,
     description="Two items per Big Five trait, 7-point agreement. Trait scores are the mean of the two items "
                 "(one reversed). Very short: for when time is tight, not for individual assessment.",
     citation="Gosling, S. D., Rentfrow, P. J., & Swann, W. B., Jr. (2003). A very brief measure of the Big-Five "
              "personality domains. Journal of Research in Personality, 37(6), 504-528.",
     licence="Free for non-commercial research (the authors' website).",
     questions=[
         {"id": "tipi", "type": "matrix", "required": True,
          "options": _opts([(1, "Disagree strongly"), (2, "Disagree moderately"), (3, "Disagree a little"),
                            (4, "Neither agree nor disagree"), (5, "Agree a little"), (6, "Agree moderately"),
                            (7, "Agree strongly")]),
          "text": "Here are a number of personality traits that may or may not apply to you. Please indicate the "
                  "extent to which you agree or disagree with each statement. You should rate the extent to which "
                  "the pair of traits applies to you, even if one characteristic applies more strongly than the "
                  "other. I see myself as:",
          "items": _items("tipi_", _TIPI, {2, 4, 6, 8, 10})}],
     scores={"tipi_extraversion": {"items": ["tipi_1", "tipi_6"], "method": "mean", "description": "TIPI Extraversion (1-7)"},
             "tipi_agreeableness": {"items": ["tipi_2", "tipi_7"], "method": "mean", "description": "TIPI Agreeableness (1-7)"},
             "tipi_conscientiousness": {"items": ["tipi_3", "tipi_8"], "method": "mean",
                                        "description": "TIPI Conscientiousness (1-7)"},
             "tipi_emotional_stability": {"items": ["tipi_4", "tipi_9"], "method": "mean",
                                          "description": "TIPI Emotional Stability (1-7)"},
             "tipi_openness": {"items": ["tipi_5", "tipi_10"], "method": "mean", "description": "TIPI Openness (1-7)"}})

_MINI = [("Am the life of the party.", "E", False), ("Sympathize with others' feelings.", "A", False),
         ("Get chores done right away.", "C", False), ("Have frequent mood swings.", "N", False),
         ("Have a vivid imagination.", "I", False), ("Don't talk a lot.", "E", True),
         ("Am not interested in other people's problems.", "A", True),
         ("Often forget to put things back in their proper place.", "C", True), ("Am relaxed most of the time.", "N", True),
         ("Am not interested in abstract ideas.", "I", True), ("Talk to a lot of different people at parties.", "E", False),
         ("Feel others' emotions.", "A", False), ("Like order.", "C", False), ("Get upset easily.", "N", False),
         ("Have difficulty understanding abstract ideas.", "I", True), ("Keep in the background.", "E", True),
         ("Am not really interested in others.", "A", True), ("Make a mess of things.", "C", True),
         ("Seldom feel blue.", "N", True), ("Do not have a good imagination.", "I", True)]
_TRAITS = {"E": "extraversion", "A": "agreeableness", "C": "conscientiousness", "N": "neuroticism",
           "I": "intellect_imagination"}
_add("mini_ipip", title="Mini-IPIP: Big Five (20 items)", category="Personality", minutes=3,
     description="Four items per Big Five trait from the International Personality Item Pool, 5-point accuracy "
                 "scale. Trait scores are sums (4-20).",
     citation="Donnellan, M. B., Oswald, F. L., Baird, B. M., & Lucas, R. E. (2006). The Mini-IPIP scales: "
              "Tiny-yet-effective measures of the Big Five factors of personality. Psychological Assessment, "
              "18(2), 192-203.",
     licence="Public domain (IPIP items, ipip.ori.org).",
     questions=[
         {"id": "mini_ipip", "type": "matrix", "required": True, "scale": "accuracy5",
          "text": "Describe yourself as you generally are now, not as you wish to be in the future. Describe yourself "
                  "as you honestly see yourself, in relation to other people you know of the same sex as you are, "
                  "and roughly your same age.",
          "items": [{"id": f"ipip_{i}", "text": t, **({"reverse": True} if r else {})}
                    for i, (t, _trait, r) in enumerate(_MINI, 1)]}],
     scores={f"ipip_{name}": {"items": [f"ipip_{i}" for i, (_t, tr, _r) in enumerate(_MINI, 1) if tr == key],
                              "method": "sum", "description": f"Mini-IPIP {name.replace('_', '/')} (4-20)"}
             for key, name in _TRAITS.items()})

_add("ehi_sf", title="Edinburgh Handedness Inventory: short form", category="Personality", minutes=1,
     description="Four everyday actions. Laterality quotient from -100 (fully left) to +100 (fully right); "
                 "above 60 is usually classed as right-handed, below -60 left-handed.",
     citation="Veale, J. F. (2014). Edinburgh Handedness Inventory – Short Form: A revised version based on "
              "confirmatory factor analysis. Laterality, 19(2), 164-177. (After Oldfield, 1971.)",
     licence="Free to use for research.",
     questions=[
         {"id": "ehi", "type": "matrix", "required": True,
          "options": _opts([(-100, "Always left"), (-50, "Usually left"), (0, "Both equally"), (50, "Usually right"),
                            (100, "Always right")]),
          "text": "Please indicate which hand you prefer for each of these activities.",
          "items": _items("ehi_", ["Writing", "Throwing", "Toothbrush", "Spoon"])}],
     scores={"ehi_lq": {"items": ["ehi_1", "ehi_2", "ehi_3", "ehi_4"], "method": "mean",
                        "bands": [[-61, "left-handed"], [60, "mixed-handed"], [100, "right-handed"]],
                        "description": "Laterality quotient (-100 left to +100 right)"}})

# ---- state ratings, workload, usability ----------------------------------------------------------
_add("nasa_tlx", title="NASA-TLX: workload (raw)", category="Task experience", minutes=1,
     description="Six workload dimensions rated on 0-100 sliders after a task. Raw TLX is their mean "
                 "(performance runs from perfect to failure, so higher always means more workload).",
     citation="Hart, S. G., & Staveland, L. E. (1988). Development of NASA-TLX (Task Load Index): Results of "
              "empirical and theoretical research. Advances in Psychology, 52, 139-183. Raw TLX: Hart (2006).",
     licence="Public domain (NASA Ames Research Center).",
     questions=[
         {"id": f"tlx_{k}", "type": "slider", "min": 0, "max": 100, "step": 5, "required": True, "text": text,
          "labels": labels}
         for k, text, labels in [
             ("mental", "Mental demand: How mentally demanding was the task?", ["Very low", "Very high"]),
             ("physical", "Physical demand: How physically demanding was the task?", ["Very low", "Very high"]),
             ("temporal", "Temporal demand: How hurried or rushed was the pace of the task?", ["Very low", "Very high"]),
             ("performance", "Performance: How successful were you in accomplishing what you were asked to do?",
              ["Perfect", "Failure"]),
             ("effort", "Effort: How hard did you have to work to accomplish your level of performance?",
              ["Very low", "Very high"]),
             ("frustration", "Frustration: How insecure, discouraged, irritated, stressed, and annoyed were you?",
              ["Very low", "Very high"])]],
     scores={"tlx_raw": {"items": ["tlx_mental", "tlx_physical", "tlx_temporal", "tlx_performance", "tlx_effort",
                                   "tlx_frustration"], "method": "mean", "description": "Raw NASA-TLX (0-100)"}})

_add("kss", title="Karolinska Sleepiness Scale (KSS)", category="Task experience", minutes=0.5,
     description="One 9-point rating of sleepiness in the last 10 minutes. Often repeated before and after tasks.",
     citation="Åkerstedt, T., & Gillberg, M. (1990). Subjective and objective sleepiness in the active individual. "
              "International Journal of Neuroscience, 52(1-2), 29-37.",
     licence="Free to use.",
     questions=[{"id": "kss", "type": "single", "required": True,
                 "text": "Please indicate your sleepiness during the last 10 minutes.",
                 "options": _opts([(1, "1 – Extremely alert"), (2, "2 – Very alert"), (3, "3 – Alert"),
                                   (4, "4 – Rather alert"), (5, "5 – Neither alert nor sleepy"),
                                   (6, "6 – Some signs of sleepiness"), (7, "7 – Sleepy, but no effort to keep awake"),
                                   (8, "8 – Sleepy, some effort to keep awake"),
                                   (9, "9 – Very sleepy, great effort to keep awake, fighting sleep")])}])

_add("affect_grid", title="Valence and arousal ratings (SAM-style)", category="Task experience", minutes=0.5,
     description="Two 9-point ratings of how pleasant and how activated the participant feels, as used with the "
                 "Self-Assessment Manikin (text anchors instead of the manikin pictures). Use after each "
                 "stimulus or block.",
     citation="Bradley, M. M., & Lang, P. J. (1994). Measuring emotion: The Self-Assessment Manikin and the semantic "
              "differential. Journal of Behavior Therapy and Experimental Psychiatry, 25(1), 49-59.",
     licence="Text-anchored ratings, free to use. (The SAM pictures themselves are distributed by the authors.)",
     questions=[
         {"id": "valence", "type": "scale", "points": 9, "required": True, "labels": ["Very unpleasant", "Very pleasant"],
          "text": "How do you feel right now?"},
         {"id": "arousal", "type": "scale", "points": 9, "required": True, "labels": ["Very calm", "Very excited"],
          "text": "How calm or excited do you feel right now?"}])

_add("sus", title="System Usability Scale (SUS)", category="Task experience", minutes=2,
     description="Ten alternating positive and negative items on usability. Score 0-100 (68 is about average).",
     citation="Brooke, J. (1996). SUS: A 'quick and dirty' usability scale. In Jordan et al. (Eds.), Usability "
              "Evaluation in Industry (pp. 189-194). Taylor & Francis.",
     licence="Free to use with acknowledgement of the source.",
     questions=[
         {"id": "sus", "type": "matrix", "required": True,
          "options": _opts([(0, "Strongly disagree"), (1, "Disagree"), (2, "Neutral"), (3, "Agree"), (4, "Strongly agree")]),
          "text": "Please rate your agreement with each statement about the system you just used.",
          "items": _items("sus_", [
              "I think that I would like to use this system frequently.",
              "I found the system unnecessarily complex.", "I thought the system was easy to use.",
              "I think that I would need the support of a technical person to be able to use this system.",
              "I found the various functions in this system were well integrated.",
              "I thought there was too much inconsistency in this system.",
              "I would imagine that most people would learn to use this system very quickly.",
              "I found the system very cumbersome to use.", "I felt very confident using the system.",
              "I needed to learn a lot of things before I could get going with this system."], {2, 4, 6, 8, 10})}],
     scores={"sus_score": {"items": [f"sus_{i}" for i in range(1, 11)], "method": "sum", "multiply": 2.5,
                           "description": "SUS score (0-100)"}})

# ---- health behaviour -----------------------------------------------------------------------------
_add("audit_c", title="AUDIT-C: alcohol use", category="Health behaviour", minutes=1,
     description="The three consumption items of the WHO AUDIT. Total 0-12; common screening cut-offs are 4 or more "
                 "for men and 3 or more for women.",
     citation="Bush, K., Kivlahan, D. R., McDonell, M. B., Fihn, S. D., & Bradley, K. A. (1998). The AUDIT alcohol "
              "consumption questions (AUDIT-C). Archives of Internal Medicine, 158(16), 1789-1795.",
     licence="Public domain (World Health Organization AUDIT; US Department of Veterans Affairs).",
     questions=[
         {"id": "audit_1", "type": "single", "required": True, "text": "How often do you have a drink containing alcohol?",
          "options": _opts([(0, "Never"), (1, "Monthly or less"), (2, "2-4 times a month"), (3, "2-3 times a week"),
                            (4, "4 or more times a week")])},
         {"id": "audit_2", "type": "single", "required": True,
          "text": "How many standard drinks containing alcohol do you have on a typical day?",
          "options": _opts([(0, "1 or 2"), (1, "3 or 4"), (2, "5 or 6"), (3, "7 to 9"), (4, "10 or more")]),
          "show_if": {"audit_1": {"!=": 0}}},
         {"id": "audit_3", "type": "single", "required": True,
          "text": "How often do you have six or more drinks on one occasion?",
          "options": _opts([(0, "Never"), (1, "Less than monthly"), (2, "Monthly"), (3, "Weekly"),
                            (4, "Daily or almost daily")]),
          "show_if": {"audit_1": {"!=": 0}}}],
     scores={"audit_c_total": {"items": ["audit_1", "audit_2", "audit_3"], "method": "sum", "missing_as": 0,
                               "description": "AUDIT-C total (0-12); skipped items count 0"}})

_add("nps", title="Net Promoter Score question", category="Task experience", minutes=0.5,
     description="The 0-10 'how likely are you to recommend' question with a follow-up reason.",
     citation="Reichheld, F. F. (2003). The one number you need to grow. Harvard Business Review, 81(12), 46-54.",
     licence="Free to use (Net Promoter is a trademark of Bain & Company, Satmetrix and Fred Reichheld).",
     questions=[{"id": "nps", "type": "nps", "required": True,
                 "text": "How likely are you to recommend this study to a friend or colleague?"},
                {"id": "nps_reason", "type": "essay", "text": "What is the main reason for your score?"}])


CATEGORY_ORDER = ["Study logistics", "Mental health", "Well-being and self", "Personality", "Task experience",
                  "Health behaviour"]


def instrument(key: str) -> dict[str, Any]:
    if key not in INSTRUMENTS:
        raise KeyError(f"unknown questionnaire '{key}' (available: {', '.join(INSTRUMENTS)})")
    return copy.deepcopy(INSTRUMENTS[key])


def catalogue() -> list[dict[str, Any]]:
    """Summary of every instrument for menus and the MCP server."""
    from .survey import count_items
    out = []
    for key, ins in INSTRUMENTS.items():
        out.append({"id": key, "title": ins["title"], "category": ins["category"], "minutes": ins["minutes"],
                    "items": count_items(ins["questions"]), "description": ins["description"],
                    "citation": ins["citation"], "licence": ins["licence"], "scores": list((ins.get("scores") or {}))})
    out.sort(key=lambda d: (CATEGORY_ORDER.index(d["category"]) if d["category"] in CATEGORY_ORDER else 99, d["title"]))
    return out
