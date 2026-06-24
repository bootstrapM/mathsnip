# MathSnip

An open-source, self-hosted clone of [Mathpix Snip](https://mathpix.com/) for macOS.
Press a global hotkey, drag a box around any equation or text on screen, and get
clean **LaTeX** copied to your clipboard — with a rendered preview and Markdown /
MathML outputs. Runs **fully offline** by default, with an optional cloud fallback
for hard captures.

## How it works

1. A menu-bar icon (Σ) sits in your macOS status bar.
2. Your hotkey (default **⌘⌃M**) triggers the native crosshair selection — the
   same drag-to-select that Mathpix uses (`screencapture -i`).
3. The image is OCR'd to LaTeX:
   - **local** — [Pix2Text](https://github.com/breezedeus/Pix2Text), using its
     SOTA `mfr-1.5` formula model (runs on your machine, weights auto-download on
     first use, no key, no cost, and returns a real confidence score). A
     `text_formula` mode handles mixed text+math and outputs Markdown.
   - **cloud** — an OpenAI-compatible vision model (needs an API key).

   The engine is `local` by default; switch to `cloud` in Settings to use the API.
4. A result window opens with tabs: **Preview** (rendered with MathJax),
   **LaTeX**, **Equation**, **Markdown**, **MathML**. The default format is also
   auto-copied to your clipboard.

## Install

Requires Python 3.9+ on macOS.

```bash
cd MathPix
./run.sh          # creates .venv, installs deps, launches the app
```

Or manually:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m mathsnip
```

The first capture downloads the Pix2Text model weights (~a few hundred MB) — give
it a minute that one time.

### A note on dependency pins

The ML stack (PyTorch, transformers, optimum, OpenCV, NumPy…) doesn't pin its own
sub-dependencies, so a plain "install the latest of everything" resolves
differently on different machines and can land on an incompatible combo. The key
constraint: on Intel Macs the available PyTorch wheels are built against NumPy
1.x, but the newest OpenCV (4.12+) and NumPy (2.x) have moved on — and they're
mutually exclusive. `requirements.txt` therefore carries bounded pins:

- `numpy<2` — PyTorch wheels are built against NumPy 1.x.
- `opencv-python<4.12` — 4.12+ requires NumPy ≥2.
- `optimum<2` — optimum 2.0 relocated an import Pix2Text relies on.

These resolve to a consistent, working set on both Intel and Apple Silicon. (A
full `pip freeze` lockfile isn't used because it's architecture-specific — a
lock from one Mac can pin a `torch` version with no wheel for the other.)

### macOS permissions

Grant your terminal (or the packaged app) permission under
**System Settings → Privacy & Security**:

- **Screen Recording** — required for `screencapture` to see the screen.
- **Accessibility** — required for the global hotkey listener.

## Usage

- Press **⌘⌃M** (or use the menu-bar **Snip & Convert**) → drag a box → done.
- **Convert Image from Clipboard** OCRs an image you've already copied.
- The chosen format is auto-copied; switch tabs and hit **Copy** for another.

Pasting into Word: use the **MathML** tab — Word imports MathML as a native
equation. Word's equation editor also accepts the **LaTeX** output directly.

### Headless / scripting

```bash
python -m mathsnip.cli equation.png                 # prints all formats
python -m mathsnip.cli equation.png --format mathml # one format
```

## Configuration

Config lives at `~/.mathsnip/config.json` (created on first run; menu →
**Open Config File…**).

```jsonc
{
  "engine": "local",                  // "local" | "cloud"
  "pix2text_mode": "formula",         // "formula" | "text_formula" (mixed text+math)
  "hotkey": "<cmd>+<ctrl>+m",         // pynput syntax
  "default_copy_format": "latex_inline",
  "show_window": true,
  "cloud": {
    "provider": "openai",            // "openai" | "mathpix"
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini",
    "api_key": "",                   // or set MATHSNIP_CLOUD_API_KEY in env
    "mathpix_app_id": "",
    "mathpix_app_key": ""
  }
}
```

To keep the cloud key off disk, leave `api_key` empty and export
`MATHSNIP_CLOUD_API_KEY` instead. For a fully local setup, set `"engine": "local"`.
You can also point `base_url` at a local OpenAI-compatible server (Ollama,
llama.cpp) for an offline "cloud" tier.

## Project layout

```
mathsnip/
  app.py            menu-bar app, hotkey, orchestration (run: python -m mathsnip)
  ocr.py            OCR engine: local Pix2Text or cloud API
  capture.py        macOS region snip + clipboard image
  convert.py        LaTeX -> inline/display/markdown/mathml + confidence checks
  result_window.py  tabbed result panel with MathJax preview
  config.py         ~/.mathsnip/config.json
  cli.py            headless OCR for one image file
```

## Uninstall

Deleting the project folder removes the app and its `.venv` (the bulk of the
disk use). A few things live in your home folder and should be cleaned up
separately:

```bash
# your settings + snip history
rm -rf ~/.mathsnip

# cached model weights (a few hundred MB – ~1 GB)
rm -rf ~/.pix2text ~/.cache/huggingface
```

If you installed with pipx, run `pipx uninstall mathsnip` instead of deleting a
folder, then clean the home-folder paths above. You may also remove the terminal
(or app) entry under System Settings → Privacy & Security → Screen Recording and
Accessibility.

## Notes & limitations

- macOS only (relies on `screencapture` and the status-bar). The OCR and
  conversion modules are cross-platform; only capture + tray are macOS-specific.
- Pix2Text's `formula` mode targets isolated equations. For full mixed pages of
  text+math, use `text_formula` mode or the cloud fallback.
- The rendered preview needs `PyQt6-WebEngine`; without it the Preview tab shows
  the LaTeX as text and everything else still works.
- MathML is best-effort via `latex2mathml`; exotic macros may not convert.

Built for personal use. No telemetry, no account, your captures never leave your
machine unless you explicitly enable the cloud engine.
