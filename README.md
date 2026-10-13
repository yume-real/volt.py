# Volt.py

**Version 1.0**

[Русская версия](README.ru.md)

A console text-world simulation: you describe a world, an LLM brings it to life,
and from then on you simply write what you do and watch the world react.

Everything runs in a single process and a single terminal. No second windows,
no websocket server, no external GUI dialogs.

A fork of [ThetaInterface/volt](https://github.com/ThetaInterface/volt),
rewritten in Python — see [Differences from the original](#differences-from-the-original).

```
Volt.py
├── volt/                 the package
│   ├── models/           world, actors, locations, time
│   ├── engine.py         LLM access (streaming, cancellation)
│   ├── game.py           game loop: input, queue, background events
│   ├── ui.py             menus, settings, new-world wizard
│   ├── console.py        colours, timed input, typewriter narration
│   ├── config.py         typed settings
│   ├── saves.py          save files
│   └── prompts.py        prompt texts
└── assets/locales/       ru.json, en.json
```

## Requirements

Python 3.9 or newer. No third-party packages — the standard library only, and
nothing to build.

## Quick start

```bash
python Volt.py
```

The main menu has five items: Play, Saves, Settings, **About** (version,
authorship, active provider and where the files live) and Exit.

Then: **Settings** → paste your Aika AI API key and pick a model, then **Play**
→ **New world** → describe the world in a few lines.

The description ends with an empty line or a lone dot. Generating a world takes
from a few dozen seconds to a couple of minutes.

### Command line flags

| Flag | What it does |
|---|---|
| `--saves` | list save files and exit |
| `--lang ru\|en` | switch the interface language (stored in `config.json`) |
| `--no-color` | disable colours |
| `--debug` | dump raw LLM replies into `./debug/` |
| `--version` | print the version and exit |

Environment variables: `NO_COLOR`, `VOLT_PY_FORCE_COLOR`, `VOLT_PY_DEBUG`.

## AI provider

**Aika AI** is used by default (`https://api.aika-ai.com/v1/chat/completions`).
Paste an API key and choose a model in Settings:

* **aika** — Aika AI, 60+ models (GPT, Claude, Gemini, DeepSeek, Qwen, GLM,
  Kimi, Grok, Llama and others);
* **custom** — any other OpenAI-compatible provider: URL, key, model.

When editing a model you can let Volt.py fetch the list from the provider
(`/v1/models`) instead of typing a name; typing it by hand works too. Aika AI
reports friendly names in that list (`ChatGPT-4o`) while the request carries the
technical identifier (`gpt-4o`) — Settings shows both.

If a provider rejects `response_format`, Volt.py retries once without it.

## How to play

In game you type an action in plain text — no numbered menus:

```
2026Y5M2D 08:15:00 > look at the kitchen

You switch the kettle on. Footsteps behind the wall.

2026Y5M2D 08:18:00 > go to the window
```

Console commands start with a slash:

| Command | What it does |
|---|---|
| `/help` | list the commands |
| `/look` | inspect the current location — no LLM call |
| `/state` | world state: time, player, location, needs, events |
| `/who` | who is nearby |
| `/inventory` | player inventory |
| `/wait N` | wait N minutes |
| `/cancel` | cancel the running generation |
| `/revert` | revert the last turn |
| `/save` | save right now |
| `/reload` | show the last narration again |
| `/log` | recent log lines |
| `/exit` | leave the game |

Short aliases, also after the slash: `/q` `/quit` exit, `/?` `/h` help,
`/l` look, `/i` inventory, `/w` wait, `/s` save, `/r` replay the last line.
Typing `exit` on its own (configurable as the "stop phrase") also leaves the
game, without a slash.

### What happens while you type

Generation runs on a background thread, therefore:

* `/cancel` works immediately, without waiting for the generation to finish;
* actions typed during generation are queued and sent as soon as it ends;
* background events print without garbling the line you are typing — every
  output erases the active input line and redraws it.

Replies are typed out character by character; the speed is controlled by the
"Text printing speed" setting (`1.0` prints instantly, no animation).

### The world keeps living

While you are not typing, the world goes on:

* every `localEventInterval` seconds (300 by default) a local event happens
  with growing probability — time passes, NPCs act;
* when the day rolls over, a world-scale event is generated automatically;
* if an event generation is cancelled, the clock is rolled back so the world
  never skips an undescribed stretch of time.

Switch this off with **Settings → Local events**.

## Settings

**Settings** lists every option; a number edits it, `0` goes back, `r` resets
everything to defaults. Values are written to `config.json` immediately.

| Key | Meaning |
|---|---|
| `aiProvider` | provider: `aika` or `custom` |
| `aikaApiKey` | Aika AI API key |
| `aikaModel` | Aika AI model, e.g. `gpt-4o-mini` |
| `customProviderUrl` / `customProviderApiKey` / `customProviderModel` | your own provider |
| `language` | interface language (`ru`, `en`) |
| `exitPhrase` | the word that leaves the game |
| `textSpeed` | narration speed, `0`–`1` |
| `temperature` | sampling temperature, `0.1`–`1.0` |
| `generateLocalEvents` | enable background local events |
| `localEventInterval` | base interval for local events, seconds |
| `regenerateAttempts` | how many times to retry an event |
| `messageHistorySize` | how many recent messages to keep |
| `worldHistorySize` / `worldEventsSize` / `worldRumorsSize` | limits for world data |
| `actorMemorySize` / `actorKnowledgeSize` | limits for an actor's memory and knowledge |
| `logRotation` / `logRotationLimit` | `log.txt` rotation by line count |

## Files next to the program

| Path | What it is |
|---|---|
| `config.json` | settings, created on first run |
| `saves/` | saves, one JSON per world: `{id}_{date}.json` |
| `log.txt` | errors and warnings |
| `debug/` | raw LLM replies, only with `--debug` |

You can copy the whole folder — worlds, settings and logs travel with it.

## How it works

The world is a single JSON document: locations, actors with their needs, memory
and knowledge, history, rumors, hidden history (what the player does not know)
and world flags.

For each action the LLM returns `narration` (what the player perceives) and a
list of `stateChanges` — commands such as `moveActor`, `addMemory`, `setNeed`,
`addCurrentEvent`, `addHiddenHistory` and several dozen more. Volt.py applies
them and saves the file. That is why reverting is just restoring the previous
snapshot instead of regenerating anything.

Prompts live in `volt/prompts.py` and read as plain text: one each for world
generation, player action, local event and world event.

## Differences from the original

The original was a Dart console app split into a client and a "server" talking
over WebSocket on `127.0.0.1:9999`. The server opened in a separate terminal
window, and text entry went through an external dialog written in C++.

All of that is gone:

| | Before | Now |
|---|---|---|
| Processes | client + WebSocket server, two windows | one process, one terminal |
| Input | numbered menus + a GUI dialog (`dialog.exe`) | plain text and `/` commands |
| Cancellation | only between turns | `/cancel` interrupts generation at once |
| Queue | none | actions typed during generation wait their turn |
| Interface | Russian only, `en.json` was nearly empty | full `ru` and `en`, switchable in Settings |
| Providers | a separate SDK for Mistral | one OpenAI-compatible client, Aika AI by default |
| Dependencies | Dart SDK + CMake + a build step | Python standard library only |

The world model, the save format and the prompt texts are preserved: the
prompts were carried over almost verbatim, only the mention of the language
changed inside the model instructions. All 42 `stateChanges` types described in
the prompts are implemented.

The code that applies changes was rewritten — the original had bugs:

* the `addActor` check was inverted, so an actor could be added twice;
* an incomplete `updateActor` from the model wiped location, needs and age;
* a repeated `addCurrentEvent` with the same `id` produced duplicates — the
  entry is now updated in place;
* `Time` computed seconds differently when comparing and when adding;
* world events were generated with the local-event prompt.

## License

MIT — see [LICENSE](LICENSE). Important: the original project was published
without a license, so the MIT terms cover only what was written here, not the
prompt texts and the data schema carried over from it.

Author: ✧✼ Y U M E ✼✧