# Translator Overlay

A screen region translator for Windows. Press a hotkey, select any text on screen, and read the
translation in a popup next to it: game chat, a stream, a program without a translation.

- **Works without setup.** Google Translate needs no key; DeepL, Azure or an LLM can be used with
  your own key.
- **Can run fully offline.** A local NLLB-200 model, fine-tuned for game chat and paired with a
  glossary of chat terms (`wts`, `lf2m`, `gg`), translates without the network.
- **Private by default.** The text you translate is never written to the logs, and with the
  local model it never leaves your computer.

## Start here

| I want to… | Go to |
|---|---|
| Install and start translating | [Installation](installation.md) |
| Change the hotkeys, backend or languages | [Configuration](configuration.md) |
| Translate offline | [Local offline model](local-model.md) |
| Know what is sent where | [Privacy](privacy.md) |
| Fix a problem | [FAQ](faq.md) |
| Understand the pipeline and the model lifecycle | [How it works](how-it-works.md) |
| Train or re-score the model | [Training](training.md), [Reproducing experiments](experiments.md) |
| Work on the code | [Development](development.md) |

The source code is MIT-licensed; the NLLB model and its builds are CC-BY-NC-4.0 (non-commercial).
