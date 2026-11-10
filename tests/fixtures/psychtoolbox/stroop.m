% Stroop task (Psychtoolbox-3)
% Respond to the INK colour: d = red, f = green, j = blue
% Written for the lab's PTB course, 2023

sca;
close all;
clear;

subjID = input('Participant number: ', 's');

PsychDefaultSetup(2);
Screen('Preference', 'SkipSyncTests', 1);
screens = Screen('Screens');
screenNumber = max(screens);
white = WhiteIndex(screenNumber);
black = BlackIndex(screenNumber);
[window, windowRect] = PsychImaging('OpenWindow', screenNumber, black);
[xCenter, yCenter] = RectCenter(windowRect);
Screen('BlendFunction', window, 'GL_SRC_ALPHA', 'GL_ONE_MINUS_SRC_ALPHA');
Screen('TextFont', window, 'Arial');
Screen('TextSize', window, 60);
ifi = Screen('GetFlipInterval', window);
HideCursor;

% ---------------------------------------------------------------- keys
KbName('UnifyKeyNames');
escapeKey = KbName('ESCAPE');
redKey = KbName('d');
greenKey = KbName('f');
blueKey = KbName('j');

% ---------------------------------------------------------------- conditions
wordList = {'RED', 'GREEN', 'BLUE'};
rgbColors = [1 0 0; 0 1 0; 0 0 1];

% columns: word number, colour number
condMatrix = [1 1; 2 2; 3 3; 1 2; 2 3; 3 1];
numReps = 2;
condMatrixRep = repmat(condMatrix, numReps, 1);
numTrials = size(condMatrixRep, 1);
shuffler = Shuffle(1:numTrials);
condMatrixShuffled = condMatrixRep(shuffler, :);

% results: word, colour, response, RT
respMat = nan(numTrials, 4);

% ---------------------------------------------------------------- instructions
DrawFormattedText(window, 'Name the INK colour of each word\n\nd = red   f = green   j = blue\n\nPress any key to begin', 'center', 'center', white);
Screen('Flip', window);
KbStrokeWait;

% ---------------------------------------------------------------- trial loop
for trial = 1:numTrials

    wordNum = condMatrixShuffled(trial, 1);
    colorNum = condMatrixShuffled(trial, 2);
    theWord = wordList{wordNum};
    theColor = rgbColors(colorNum, :);

    % fixation cross for 500 ms
    DrawFormattedText(window, '+', 'center', 'center', white);
    vbl = Screen('Flip', window);
    WaitSecs(0.5);

    % the word, until a response or 2 s
    DrawFormattedText(window, theWord, 'center', 'center', theColor);
    vbl = Screen('Flip', window);
    tStart = GetSecs;
    respToBeMade = true;
    response = 0;
    rt = NaN;
    while respToBeMade && GetSecs - tStart < 2
        [keyIsDown, secs, keyCode] = KbCheck;
        if keyCode(escapeKey)
            ShowCursor;
            sca;
            return
        elseif keyCode(redKey)
            response = 1;
            respToBeMade = false;
        elseif keyCode(greenKey)
            response = 2;
            respToBeMade = false;
        elseif keyCode(blueKey)
            response = 3;
            respToBeMade = false;
        end
    end
    rt = secs - tStart;
    correct = response == colorNum;

    respMat(trial, :) = [wordNum colorNum response rt];

    % blank inter-trial interval
    Screen('Flip', window);
    WaitSecs(0.8);
end

save(['stroop_' subjID '.mat'], 'respMat');

DrawFormattedText(window, 'Thank you!', 'center', 'center', white);
Screen('Flip', window);
WaitSecs(2);
ShowCursor;
sca;
