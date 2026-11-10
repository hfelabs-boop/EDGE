function flanker()
% Flanker task with picture stimuli, a conditions table and KbQueue responses.
% Left/right arrow keys for the direction of the middle arrow.

try
    PsychDefaultSetup(2);
    InitializePsychSound(1);
    screenNumber = max(Screen('Screens'));
    [win, rect] = PsychImaging('OpenWindow', screenNumber, [0.5 0.5 0.5]);
    Screen('TextSize', win, 40);

    % beep for errors
    pahandle = PsychPortAudio('Open', [], 1, 1, 44100, 1);
    [beep, fs] = audioread('stimuli/beep.wav');
    PsychPortAudio('FillBuffer', pahandle, beep');

    KbName('UnifyKeyNames');
    leftKey = KbName('LeftArrow');
    rightKey = KbName('RightArrow');
    keysOfInterest = zeros(1, 256);
    keysOfInterest([leftKey rightKey]) = 1;
    KbQueueCreate([], keysOfInterest);

    T = readtable('conditions.csv');
    nTrials = height(T);
    order = randperm(nTrials);
    results = zeros(nTrials, 3);

    DrawFormattedText(win, 'Which way does the MIDDLE arrow point?\nPress LEFT or RIGHT.\n\nPress SPACE to start.', 'center', 'center', [0 0 0]);
    Screen('Flip', win);
    KbWait;

    for t = 1:nTrials
        row = order(t);
        img = imread(T.image{row});
        tex = Screen('MakeTexture', win, img);

        DrawFormattedText(win, '+', 'center', 'center', [0 0 0]);
        Screen('Flip', win);
        WaitSecs(T.fixdur(row) / 1000);

        Screen('DrawTexture', win, tex);
        onset = Screen('Flip', win);
        KbQueueStart;
        WaitSecs(1.5);
        KbQueueStop;
        [pressed, firstPress] = KbQueueCheck;
        KbQueueFlush;
        if pressed
            keyPressed = find(firstPress, 1);
            rt = firstPress(keyPressed) - onset;
            correct = strcmp(KbName(keyPressed), T.correct_key{row});
        else
            rt = NaN;
            correct = 0;
        end
        if ~correct
            PsychPortAudio('Start', pahandle, 1, 0, 1);
        end
        results(t, :) = [row correct rt];
        Screen('Close', tex);

        Screen('Flip', win);
        WaitSecs(0.5);
    end

    writetable(array2table(results), 'flanker_results.csv');
    KbQueueRelease;
    PsychPortAudio('Close', pahandle);
    sca;
catch err
    sca;
    rethrow(err);
end
end
