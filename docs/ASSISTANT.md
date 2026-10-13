# The assistant: build and change experiments by describing them

Open the **Assistant** (the button in the top bar, or **Ctrl+I**), describe what you want in your own words,
and attach the files you already have: a trial list in Excel or CSV, pictures, a consent page, your
instructions as text. The assistant changes the experiment you have open, checks it and test-runs it with a
virtual participant. You see every change before anything happens, and every change can be undone.

> *"Build a Stroop task from this list, 2 blocks, feedback after each trial."*
> *"Add a practice block of 6 trials that repeats until 80 % are correct."*
> *"Make the words bigger."* (with the word selected)

The assistant is optional: everything else in EDGE works without it. It can run on **Claude** (by
Anthropic, online, the best results), on **any OpenAI-compatible service** (OpenAI, OpenRouter …), or on
**Ollama** or **LM Studio**, which run a model on this computer: free, offline, nothing leaves the computer.

## Set up the assistant

Open **Assistant settings** (the ⋯ menu of the Assistant panel). Under **Where should the assistant run?**
choose one of the four services, fill in its fields, press **Test connection**, then **Save**.

| Service | You need | Notes |
|---|---|---|
| **Claude (Anthropic)** | an API key | Best results. Online. Your requests are billed to your Anthropic account. |
| **OpenAI-compatible** | the service and an API key | OpenAI, OpenRouter, or another address that speaks the OpenAI API. |
| **Ollama** | Ollama installed, a model downloaded | Free. Runs on this computer. |
| **LM Studio** | LM Studio installed, a model loaded | Free. Runs on this computer. |

Three switches apply to every service:

* **Test-run every change with a virtual participant**: after the assistant finishes, EDGE runs the new
  version with simulated devices and a virtual participant and shows the verdict and the number of trials.
* **Let the assistant see the pictures I attach**: pictures are sent to the model (if it can look at
  pictures); otherwise it only gets their names and sizes.
* **Keep a history of applied changes next to the experiment**: one line per applied change in
  `.edge/assistant/history.jsonl` in the experiment's folder (what you asked, what changed, which model).

### Set up Claude (Anthropic)

1. Make an API key: sign in at [console.anthropic.com](https://console.anthropic.com), open **API keys**,
   create a key and copy it (it starts with `sk-ant-`).
2. In **Assistant settings** choose **Claude (Anthropic)**, paste the key into **API key** and keep the
   **Model** at *Claude Opus 5.5 · best results (default)*. *Claude Sonnet 5.5* is faster and cheaper;
   *Claude Haiku 5.5* is the fastest and cheapest and fine for small edits; *Claude Fable 5.1* is the most
   capable and the most expensive.
3. Press **Test connection**: you should see "Connected to Claude Opus 5.5 ✓". Then **Save**.
4. The first time, EDGE shows **Before EDGE sends anything online** with the privacy note below. Press
   **Continue** (or **Use a local model instead**).

After saving, the key is never shown again: the field shows its last four characters, with **Replace** and
**Remove**. If you prefer, set the `ANTHROPIC_API_KEY` environment variable instead of saving a key; a saved
key wins over the variable. A key belongs to its address: a key from the environment is only sent to Anthropic's
own address, and changing the **Address** removes a saved key (type it again for the new address). **Test
connection** for an address you haven't saved needs the key typed again too.

In Expert mode, **Advanced** offers **Effort** (*high* by default: Claude takes more care; *medium* is
faster; *max* is the most careful) and the **Address** (only change it if your institution gives you another
gateway; `https://api.anthropic.com/v1` is understood as `https://api.anthropic.com`). If Claude declines a
request for safety reasons, it is automatically retried on another Claude model. Older Claude models that the
service still lists (e.g. Claude Sonnet 4.5) are marked *Older model*: they work, without progress notes.

### Set up an OpenAI-compatible service

Choose **OpenAI-compatible**, then the **Service**: *OpenAI* (`https://api.openai.com/v1`), *OpenRouter*
(`https://openrouter.ai/api/v1`, one key for many models) or *Custom address* (any server that speaks the
OpenAI Chat Completions API, e.g. a university gateway or vLLM). Paste the **API key**, press **Refresh** to
list the models, pick one that can call tools, and press **Test connection**. The keys can also come from the
`OPENAI_API_KEY` or `OPENROUTER_API_KEY` environment variables (used only with OpenAI's and OpenRouter's own
addresses; for a custom address type the key in). Online addresses must use `https://`. For Ollama choose the
**Ollama** option rather than Ollama's OpenAI-compatible address: only there can EDGE set the context size.

### Set up Ollama

[Ollama](https://ollama.com) runs open models on your computer.

1. Install Ollama from [ollama.com/download](https://ollama.com/download) and start it (on Windows and
   macOS it runs in the background after installing; on Linux run `ollama serve`).
2. Download a model **that can call tools**, in a terminal:
   ```bash
   ollama pull qwen2.5:14b
   ```
   Models with tool support work best: for example the Qwen 2.5 / Qwen 3 family (`qwen2.5:14b`, `qwen3:14b`),
   Llama 3.1 and later (`llama3.1:8b`), Mistral Small or `gpt-oss:20b`. Ollama's website marks them with
   *tools*. Small models (7–8 B) manage single changes; to build whole experiments from a description use a
   14 B+ model (about 10 GB of memory) or Claude. Models without tool support still work through a slower
   JSON mode, with more mistakes.
3. In **Assistant settings** choose **Ollama**. The **Address** is `http://localhost:11434` (a pasted `/v1` or
   `/api` is removed). Press **Refresh**, pick the model (models with tools are listed first, marked *tools*),
   and press **Test connection**.

   Ollama on **another computer** (e.g. a lab server, `http://192.168.1.20:11434`) works too, but then your
   requests leave this computer: the settings say "Ollama (at 192.168.1.20)", EDGE asks once before the first
   request (as for online services), and with an `http://` address the requests travel unencrypted on the
   network. Prefer this computer, or an address only your institution's network can reach.

In Expert mode, **Context size** sets how much the model reads at once (16 384 by default; 32 768 is better
for big experiments if your computer has the memory), and **Tool mode** forces the JSON mode for models that
claim tool support but use it badly.

### Set up LM Studio

[LM Studio](https://lmstudio.ai) runs open models on your computer with a desktop app.

1. Install LM Studio, open the **Discover** tab and download a model (one marked as supporting tool use,
   e.g. a Qwen 2.5 14B Instruct).
2. **Load** the model. Set its **Context Length** to 16 384 or more when you load it.
3. Start the local server: open the **Developer** tab and switch the server on (or run `lms server start`).
4. In **Assistant settings** choose **LM Studio**. The **Address** is `http://localhost:1234/v1`. Pick the
   model (loaded models come first) and press **Test connection**.

## Ask

Type in **Describe a change, or ask a question…** and press Enter (Shift+Enter for a new line). If an item or
a screen is selected, the request is *about* it (shown as "About: screen “trial”"), so "make this bigger"
works; press × on that chip to ask about the whole experiment. The quick starts (*Build an experiment from my
trial list*, *Add a practice block*, *Explain this experiment* …) fill in the text for you.

While it works, the panel shows its steps ("Reading words.csv", "Adding screen “trial”", "Checking for
problems", "Test run with a virtual participant: 18 trials, OK"). **Stop** ends it at once: nothing is changed
and any file it was writing is removed.

When it is done, the experiment opens as a **preview**: "Previewing 4 changes from the assistant. Nothing is
changed until you apply." New and changed screens and items are marked; you can **Try it** and start a test run
on the proposed version. The card in the panel lists each change (click one to see it), what the check found and
the test-run verdict. Then:

* **Apply** (Ctrl+Enter) makes the change: one step that **Undo** reverts.
* **Discard** throws it away and removes the files the assistant made for it.
* **Change something…** asks for a correction.

In **Preferences**, *Apply its changes right away (you can always undo)* skips the preview. The preview is
always shown when the assistant ran out of steps, when the change replaces most of your experiment, or when
you edited the experiment while it was working ("You changed the experiment while the assistant worked":
**Ask again with my changes**, **Apply anyway** or **Discard**).

Questions ("why does this screen never end?", "explain this experiment") are answered without changing anything.
Follow-ups keep the conversation; **New conversation** in the ⋯ menu starts afresh.

## Attach files

Press **Attach files**, drop files on the panel or paste a picture. **Attached files are copied into this
experiment's folder**, next to the experiment, so the experiment can use them and they travel with it:

| You attach | It goes to | The assistant can |
|---|---|---|
| Trial lists: `.csv`, `.tsv`, `.xlsx` (any sheet), tables in `.txt` (e.g. E-Prime lists), rows in `.json` / `.yaml` | `conditions/` | use it as a trial list: its columns become the values that change per trial |
| Pictures: `.png`, `.jpg`, `.gif`, `.webp`, `.bmp`, `.svg`, `.tif` | `images/` | show it, or put one picture per trial in a trial-list column |
| Web pages: `.html` (consent forms, questionnaires) | `pages/` | show it as a web page step and save the form's answers |
| Text: `.txt`, `.md` | `materials/` | use it as instructions or texts |
| Other JSON or YAML | `materials/` | read the part you point to |
| Sounds: `.wav` (also `.mp3`, `.ogg`, `.flac`) | `sounds/` | play it (use WAV for sounds whose timing matters) |

Each file shows as a chip with a one-line summary ("words.csv — 9 rows × 4 columns: word, ink, congruent,
correct_key"); × removes a file you have not sent yet. EDGE never overwrites a file: a second file with the same
name becomes `name_2.csv`. Old Excel files (`.xls`), Word documents and PDFs are not read yet: save them as
`.xlsx`, `.csv` or `.txt`. Program files and hidden files are refused.

If a table can't be a trial list as it is (another sheet than the one Excel opens with, column names with spaces,
rows inside a bigger JSON file, a table in a web page), the assistant writes a converted copy, e.g.
`conditions/words-trials.csv`, and tells you. Lists saved by Windows Excel in its old encoding are converted to
UTF-8 when attached, so accents come out right.

A new experiment needs a name (and so a folder) before files can be attached; the panel asks for it.

## What is sent where

**What is sent where.** With a cloud assistant (Claude by Anthropic, OpenAI, OpenRouter or another online
service), what you type, the experiment you are editing (its screens, texts, settings and trial lists) and the
files you attach are sent to that company to produce the answer, under its terms. EDGE never sends your
participants' data (the `data` folders) and never sends your API key anywhere except to that service. Check your
institution's rules before sending unpublished materials or anything that identifies people. With **Ollama** or
**LM Studio** on this computer, everything stays on this computer.

Your API key is stored only on this computer, in your user settings folder (`~/.config/edge/assistant.json` on
Linux, `~/Library/Application Support/EDGE/assistant.json` on macOS, `%APPDATA%\EDGE\assistant.json` on Windows),
readable only by your user account. It is never written into experiment files, bundles, support bundles or logs.
You can remove it at any time in **Assistant settings**.

Under the box you type in, the panel always says where your request goes: "On this computer: nothing is sent
anywhere." or "Sent to Anthropic to answer. Your API key stays on this computer." (or, for Ollama / LM Studio on
another computer, which computer). If an attached table looks like recorded participant data, the panel asks
before sending it to an online service.

"Participant data" is every session folder: the `data` folder, the folder the experiment saves its sessions in
(*Settings → Data → folder*, `settings.data.dir`, e.g. `results`), and any folder holding a session
(`session.json`, `trials.jsonl`). The assistant never lists, reads, previews or writes files there, and the
builder doesn't offer them as trial lists.

## What the assistant can and cannot do

* It changes only the experiment you have open, and only in the builder's memory: nothing is saved until you
  apply and save. It can write trial-list files (CSV) into the experiment's folder, never over an existing file
  and never into a data or session folder.
* It cannot run programs, reach the internet, read files outside the experiment's folder, or see participant data.
  Its test runs are offline too: a *Messages from another program* (UDP) device listens on this computer only
  and sends nothing during a test run; the result lists where it would send markers in a real session.
* It avoids Python **code** items. If it writes one, the result says "Python code written by the assistant —
  read it before running participants", it is **not** test-run — not in that request and not in any later one
  (also after you apply it, also from the terminal) until you press **I've read it** — and the Run page warns
  until then. **Try it** and **Start test run** ask first as well (*Review it* / *I've read it*), in every
  browser: "read" is kept next to the experiment (`.edge/assistant/reviewed.json`), not only in this browser.
  Code runs with your rights on this computer: read it as you would a script someone sent you.
* Web pages it adds or changes are listed for review when they run scripts or contact other servers (a script,
  `onload`/`onerror` and other `on…` attributes, `javascript:` links, embedded frames, forms or pictures that
  send to or load from another address, automatic redirects).
* Text inside attached files is treated as data, never as instructions to the assistant.

See [the security model](SECURITY.md#experiment-assistant) for the details.

## Undo and history

**Apply** is one step: **Undo** (Ctrl+Z) brings back the experiment exactly as it was. Discarded changes leave
nothing behind except the files you attached yourself. Every save keeps the previous version in **History**,
and with *Keep a history of applied changes* on, `.edge/assistant/history.jsonl` records each applied request.

## When something goes wrong

The panel says what happened and what to do. The common cases:

| Message | What to do |
|---|---|
| Ollama isn't running on this computer | Start the Ollama app, or run `ollama serve`, then press **Test connection**. |
| The model “…” isn't downloaded in Ollama | Run `ollama pull <model>` in a terminal, or pick an installed model. |
| LM Studio's local server isn't running / has no model loaded | Developer tab → switch the server on; load a model (`lms load <model>`). |
| Claude didn't accept the API key | Paste the key again in **Assistant settings** (it starts with `sk-ant-`). |
| … says the account has no credit left | Add credit in the service's billing page, or use a local model. |
| … is limiting requests / is busy | Wait a minute and try again. |
| … had a problem on its side | The service failed after EDGE tried three times: try again in a few minutes. |
| The address … doesn't lead to … | Check the **Address**: Claude `https://api.anthropic.com`, Ollama `http://localhost:11434`, LM Studio `http://localhost:1234/v1`. |
| Couldn't make a secure connection | Check the date and time. On a network that inspects traffic, ask IT for its certificate and set `SSL_CERT_FILE` to it (macOS with Python from python.org: run *Install Certificates.command*). |
| The model stopped: it doesn't fit in this computer's memory | Choose a smaller model, or lower the context size. |
| The answer was cut off by the model's output limit | The result is marked incomplete: ask for a shorter answer or a smaller change. |
| The request is too long for … | Attach fewer or smaller files, start a **New conversation**, or (Ollama / LM Studio) raise the context size. |
| This model can't follow EDGE's instructions | Choose a model with tool support. |
| The assistant needed more steps than allowed | **Apply** what it did so far (it is shown as a preview), or ask for a smaller change. |

## From the command line

```bash
edge assistant setup                         # step by step: service, key, model, test, privacy note
edge assistant config --provider ollama --model qwen2.5:14b
printf %s "$KEY" | edge assistant config --provider anthropic --set-key     # the key is never an argument
edge assistant test                          # check the connection
edge assistant models                        # list the models
edge assistant ask study/study.yaml "Add a practice block of 6 trials" --attach practice.xlsx
```

`ask` saves the experiment with a backup (`edge backups study/study.yaml` lists it as "assistant: …"), or prints
the new version with `--no-save`. `--new` creates the file first (only once the service, key and consent are in
order, so a refused request leaves nothing behind), `--json` prints the full result, `--yes` agrees to the privacy
note for an online service (or an Ollama / LM Studio on another computer). Python code the assistant wrote is
not test-run, in any later request either, until you have read it and add `--code-read`. It exits with 0 when the result checks out, 3 when it was saved but
still has problems to fix, 2 when the assistant isn't set up or the service failed, and 4 when it stopped,
declined or ran out of steps. See [the command reference](reference/cli.md#edge-assistant).
