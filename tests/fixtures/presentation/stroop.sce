# Stroop task -- Presentation scenario
# Buttons (Settings > Response): 1 = D (red), 2 = F (green), 3 = J (blue)
# Port codes: 11-13 congruent, 21-23 incongruent
scenario = "Colour-word Stroop";
pcl_file = "stroop.pcl";

scenario_type = trials;
response_matching = simple_matching;
active_buttons = 3;
button_codes = 1, 2, 3;
target_button_codes = 51, 52, 53;
response_logging = log_active;
write_codes = true;
pulse_width = 10;

default_background_color = 0, 0, 0;
default_font = "Arial";
default_font_size = 48;
default_text_color = 255, 255, 255;
default_formatted_text = true;

begin;

# ---------------------------------------------------------------- stimuli
text { caption = "+"; font_size = 60; } fix_text;
text { caption = "RED"; font_size = 72; font_color = 255, 0, 0; } word_text;
text {
   caption = "Name the INK colour of each word.\n\nD = red     F = green     J = blue\n\nPress any button to start.";
   font_size = 28;
} instr_text;
text { caption = "Thank you!"; } end_text;
text { caption = "Correct"; font_color = 0, 200, 0; } correct_text;
text { caption = "Wrong"; font_color = 255, 0, 0; } wrong_text;

bitmap { filename = "keys.png"; } keys_bmp;

wavefile { filename = "correct.wav"; } correct_wav;
sound { wavefile { filename = "wrong.wav"; }; } wrong_snd;

picture { text fix_text; x = 0; y = 0; } fix_pic;
picture { text word_text; x = 0; y = 0; } word_pic;
picture { text instr_text; x = 0; y = 100; bitmap keys_bmp; x = 0; y = -200; } instr_pic;
picture { text end_text; x = 0; y = 0; } end_pic;
picture { } blank_pic;

# ---------------------------------------------------------------- trials
trial {
   trial_duration = forever;
   trial_type = first_response;
   picture instr_pic;
} instr_trial;

trial {
   trial_duration = 500;
   picture fix_pic;
   code = "fixation";
} fix_trial;

trial {
   trial_duration = 2000;
   trial_type = first_response;
   all_responses = false;
   stimulus_event {
      picture word_pic;
      time = 0;
      duration = response;
      target_button = 1;
      code = "word";
      port_code = 11;
   } word_event;
} stroop_trial;

trial {
   trial_duration = 500;
   stimulus_event {
      picture { text correct_text; x = 0; y = 0; };
      time = 0;
      code = "fb_correct";
   };
   stimulus_event {
      sound correct_wav;
      time = 0;
   };
} correct_trial;

trial {
   trial_duration = 500;
   stimulus_event {
      picture { text wrong_text; x = 0; y = 0; };
      time = 0;
      code = "fb_wrong";
   };
   stimulus_event {
      sound wrong_snd;
      time = 0;
   };
} wrong_trial;

trial {
   trial_duration = 1000;
   picture blank_pic;
} iti_trial;

trial {
   trial_duration = 3000;
   picture end_pic;
} end_trial;
