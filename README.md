# Project 018 — Fireworks Show

![Python](https://img.shields.io/badge/Python-3.12%2B-blue)
![Pygame](https://img.shields.io/badge/Pygame-2.6.1-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

A fireworks display built from chained particle emitters, with
fully synthesized sound. Part of the **EIDOLON** series: 500+ coding
experiments, one new project at a time.

## What it does

A rocket climbs, slows under gravity, and bursts at its peak. Each burst
is a chain of emitters:

```text
rocket -> shell -> star -> secondary sparks -> crackle pops
```

Seven shell designs: **peony**, **chrysanthemum**, **ring**, **willow**,
**crossette** (stars that split into an X), **heart**, and **double-break**.

## Features

- Glow trails that fade over time, plus optional bloom
- Night sky, twinkling stars, city skyline, and sky flashes on every burst
- Stereo audio with no sound files: launch whistle, booms that arrive
  slightly late (the higher the burst, the longer the delay), crackle, pops
- Auto show that builds in intensity and ends in a finale
- Click to launch a rocket exactly where you want it to burst
- Title screen and 3-2-1 countdown
- Repeatable shows with `--seed`

## Install

```bash
python -m pip install -r requirements.txt
```

## Run

```bash
python main.py
```

Options:

```bash
python main.py --seed 18      # repeatable show
python main.py --no-audio     # silent
python main.py --smoke-test   # headless self-test
```

## Controls

| Key | Action |
|---|---|
| SPACE | Start / pause |
| Left-click | Launch a rocket to the cursor |
| 1 - 7 | Select shell type (0 = random) |
| A | Toggle automatic show |
| F | Trigger a finale |
| C | Clear the sky |
| R | Reset counters and the sky |
| B | Toggle bloom |
| T | Cycle trail length |
| M | Mute / unmute |
| [ / ] | Lower / raise volume |
| H | Show / hide HUD |
| P | Save a screenshot to `screenshots/` |
| ESC | Quit |

## How it works

- **Physics:** every star has velocity, drag, and gravity. Drag is applied
  as `exp(-drag * dt)`, so motion looks the same at any frame rate.
- **Chaining:** particles can emit trail sparks, split into new stars, or
  end with a crackle pop that spawns more sparks.
- **Glow:** particles are drawn onto a persistent layer that loses a little
  brightness every frame. The fade is what makes trails.
- **Bloom:** the glow layer is shrunk and enlarged again, then added back
  on top for a soft halo.
- **Audio:** every sound is generated from sine waves, filtered noise, and
  envelopes at start-up. Panning follows the burst position.
- **Architecture:** `FireworksWorld` is pure simulation (no drawing or
  audio). `App` handles drawing, input, and sound.

## What I learned

- Chained particle emitters
- Persistent-buffer trails and additive blending
- Procedural audio synthesis and stereo panning
- Separating simulation from rendering so it can be tested headless

## Tuning

If the frame rate drops, press `B` to turn bloom off, press `T` for
shorter trails, or lower `MAX_PARTICLES` in `main.py`.

## Project structure

```text
project-018-fireworks-show/
├── main.py
├── requirements.txt
├── README.md
├── LICENSE
└── .gitignore
```

## License

MIT. See [LICENSE](LICENSE).