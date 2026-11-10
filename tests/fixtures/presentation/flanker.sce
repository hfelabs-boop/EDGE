# Eriksen flanker task, no PCL: the trials run in the order below
# (pseudo-randomised by hand, two runs of the same list).
scenario = "Flanker";
active_buttons = 2;
button_codes = 1, 2;
default_background_color = 128, 128, 128;
default_font_size = 40;
default_text_color = 0, 0, 0;
write_codes = true;

begin;

text { caption = "+"; } plus;
picture { text plus; x = 0; y = 0; } fixation;

trial {
   trial_duration = forever;
   trial_type = first_response;
   picture { text { caption = "Press the button for the MIDDLE arrow.\nLeft = 1, right = 2"; font_size = 24; }; x = 0; y = 0; };
} instructions;

LOOP $run 2;
TEMPLATE "flanker_trial.tem" {
   arrows     target   code;
   "<<<<<"    1        "congruent_left";
   ">><>>"    1        "incongruent_left";
   ">>>>>"    2        "congruent_right";
   "<<><<"    2        "incongruent_right";
};
ENDLOOP;
