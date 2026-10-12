# WeakAuras Converter

Web tool that decodes a Retail WeakAuras export (`!WA:2!`), rewrites it for WoW: Forever, and encodes an import string you can paste back into WeakAuras.

Decoding uses the same Lua libraries as WeakAuras (LibDeflate and LibSerialize). That work runs on the server. GitHub Pages cannot run it.

## Run it on your computer

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000

On macOS or Linux, use `.venv/bin/pip` and `.venv/bin/python` instead.

## Put it on a website

The repo includes a Dockerfile and `render.yaml`. From the GitHub page, use **Deploy to Render** and pick this repository. Render builds the container and gives you a public address.

[Deploy to Render](https://render.com/deploy?repo=https://github.com/nikijernberg/wa-converter)

A large aura is held in memory for 30 minutes so Decode, To Forever, and Create import string can share it. It is not written to disk.

## What To Forever changes

- Old spell, aura, and item calls are rewritten to the Midnight API (`C_Spell`, `C_UnitAuras`, `C_Item`).
- Shield auras that read the combat log are switched to `UnitGetTotalAbsorbs`.
- Classic Aura triggers that already have a spell ID become Aura (Modern).

Combat Log triggers that are not shields, and classic auras that only have a spell name, are reported and left in place. Forever closes the combat log, and Aura (Modern) ignores names.

## Tests

```bash
pip install -r requirements-dev.txt
python -m unittest tests.test_roundtrip
```

## License

GNU General Public License v3.0 or later. The decoder includes [LibDeflate](https://github.com/safeteeWow/LibDeflate) by Haoqian He, which is GPL-3.0-or-later. LibSerialize is MIT, LibStub is public domain, and `json.lua` is CC-BY by Jeffrey Friedl.
