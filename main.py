"""
EIDOLON — PROJECT 018
FIREWORKS SHOW
Chained Particle Emitters

Python 3.12+
Pygame 2.6.1

Features

- Rockets climb, slow under gravity, and burst at their peak
- Seven shell designs: peony, chrysanthemum, ring, willow,
  crossette, heart, and double-break
- Chained emitters: rocket -> shell -> star -> secondary
  sparks -> crackle pops
- Persistent glow trails and optional bloom
- Night sky, twinkling stars, city skyline, and sky flashes
- Synthesized stereo audio: launch whistle, delayed booms
  (speed of sound), crackle, and pops. No audio files needed.
- Automatic show director with periodic finales
- Click-to-launch with shell selection
- Title screen and 3-2-1 countdown

Controls

SPACE        Start / pause
Left-click   Launch a rocket to the cursor
1 - 7        Select shell type (0 = random)
A            Toggle automatic show
F            Trigger a finale
C            Clear the sky
R            Reset counters and the sky
B            Toggle bloom
T            Cycle trail length
M            Mute / unmute
[ / ]        Lower / raise volume
H            Show / hide HUD
P            Save a screenshot to screenshots/
ESC          Quit

Command line

python main.py                 Run the show
python main.py --seed 18       Repeatable show (useful for recording)
python main.py --no-audio      Disable sound
python main.py --smoke-test    Headless self-test
"""

from __future__ import annotations

import argparse
import array
import math
import os
import random
import sys
import time

if "--smoke-test" in sys.argv:
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

# ============================================================
# CONFIGURATION
# ============================================================

APP_NAME = "FIREWORKS SHOW"
PROJECT_NUMBER = "018"

SCREEN_W = 1280
SCREEN_H = 800
FPS = 60
GROUND_Y = SCREEN_H - 96

ROCKET_GRAVITY = 330.0
STAR_GRAVITY = 125.0
MAX_PARTICLES = 4200
MAX_FLASHES = 28
COUNTDOWN_SECONDS = 3.0

BG_TOP = (3, 4, 14)
BG_BOTTOM = (16, 13, 42)
UI_TEXT = (226, 232, 255)
UI_DIM = (128, 138, 176)
UI_ACCENT = (255, 196, 92)

PALETTES = [
    ((255, 72, 64), (255, 176, 64)),
    ((255, 204, 84), (255, 240, 190)),
    ((72, 204, 255), (128, 128, 255)),
    ((255, 84, 204), (255, 168, 232)),
    ((92, 255, 144), (204, 255, 104)),
    ((172, 112, 255), (240, 240, 255)),
    ((255, 255, 255), (176, 204, 255)),
    ((64, 255, 212), (255, 212, 92)),
]
GOLD = ((255, 198, 92), (255, 232, 172))

KINDS = (
    "peony",
    "chrysanthemum",
    "ring",
    "willow",
    "crossette",
    "heart",
    "double",
)
KIND_WEIGHTS = (3, 3, 2, 2, 2, 1, 2)

# (label, brightness removed from the glow layer every frame)
TRAIL_LEVELS = (("SHORT", 46), ("MEDIUM", 26), ("LONG", 14))

# Minimum seconds between repeats of the same sound.
MIN_GAP = {
    "pop": 0.035,
    "crackle": 0.08,
    "boom_s": 0.05,
    "boom_m": 0.05,
    "boom_l": 0.05,
    "whoosh": 0.05,
}

STAR = 0
SPARK = 1

# ============================================================
# HELPERS
# ============================================================


def clamp(value, low, high):
    return max(low, min(high, value))


def mix_color(a, b, amount):
    amount = clamp(amount, 0.0, 1.0)
    return tuple(int(a[i] + (b[i] - a[i]) * amount) for i in range(3))


def scale_color(color, factor):
    return tuple(int(clamp(c * factor, 0, 255)) for c in color)


# ============================================================
# AUDIO SYNTHESIS (pure functions, no mixer needed)
# ============================================================


def synth_whoosh(rate, rnd, duration=1.0):
    """Rising whistle plus filtered noise."""
    count = int(rate * duration)
    out = []
    low = 0.0
    phase = 0.0

    for i in range(count):
        p = i / count
        envelope = min(1.0, p / 0.1) * (1.0 - p) ** 1.4
        freq = 480.0 + 1500.0 * p**1.4
        phase += math.tau * freq / rate
        low += (0.04 + 0.28 * p) * ((rnd.random() * 2.0 - 1.0) - low)
        out.append((math.sin(phase) * 0.20 + low * 1.1) * envelope * 0.55)

    return out


def synth_boom(rate, rnd, power):
    """Low thump, rumbling body, and a sharp crack. power is 0..1."""
    duration = 0.9 + 0.7 * power
    count = int(rate * duration)
    out = []
    low = 0.0
    phase = 0.0
    start_freq = 150.0 - 55.0 * power

    for i in range(count):
        t = i / rate
        freq = 36.0 + (start_freq - 36.0) * math.exp(-t * 7.0)
        phase += math.tau * freq / rate
        thump = math.sin(phase) * math.exp(-t * (4.2 - 1.6 * power))
        low += (0.10 + 0.05 * (1.0 - power)) * (
            (rnd.random() * 2.0 - 1.0) - low
        )
        body = low * math.exp(-t * (5.0 - 2.0 * power)) * 2.2
        crack = (rnd.random() * 2.0 - 1.0) * math.exp(-t * 90.0) * 0.8
        out.append((thump * 0.85 + body * 0.7 + crack) * 0.62)

    return out


def synth_crackle(rate, rnd, duration=1.1):
    """Dozens of tiny clicks, denser at the start."""
    count = int(rate * duration)
    out = [0.0] * count

    for _ in range(58):
        start = int(count * (rnd.random() ** 1.7) * 0.96)
        length = int(rate * rnd.uniform(0.003, 0.011))
        amp = rnd.uniform(0.25, 0.8) * (1.0 - start / count * 0.6)
        previous = 0.0

        for j in range(length):
            index = start + j
            if index >= count:
                break
            x = rnd.random() * 2.0 - 1.0
            out[index] += (
                (x - previous)
                * 0.5
                * amp
                * math.exp(-j / (length * 0.35))
            )
            previous = x

    return out


def synth_pop(rate, rnd, freq):
    """A very short snap with a little pitch."""
    count = int(rate * 0.09)
    out = []
    previous = 0.0

    for i in range(count):
        t = i / rate
        x = rnd.random() * 2.0 - 1.0
        snap = (x - previous) * 0.5 * math.exp(-t * 60.0) * 0.9
        tone = math.sin(math.tau * freq * t) * math.exp(-t * 50.0) * 0.25
        out.append(snap + tone)
        previous = x

    return out


def synth_tone(rate, freq, duration, volume=0.4, overtone=0.0):
    count = int(rate * duration)
    out = []

    for i in range(count):
        t = i / rate
        attack = min(1.0, t / 0.005)
        release = clamp((duration - t) / 0.06, 0.0, 1.0)
        value = math.sin(math.tau * freq * t)
        value += overtone * math.sin(math.tau * freq * 2.0 * t)
        out.append(value * attack * release * volume)

    return out


def to_pcm(samples, channels=2):
    """Convert float samples to signed 16-bit PCM bytes."""
    if channels not in (1, 2):
        raise ValueError(f"Unsupported channel count: {channels}")

    data = array.array("h")
    for sample in samples:
        value = int(32767 * clamp(sample, -1.0, 1.0))
        data.append(value)
        if channels == 2:
            data.append(value)

    return data.tobytes()


class AudioEngine:
    """
    Builds every sound mathematically at start-up and plays it with
    stereo panning and optional delay. If audio is unavailable, the
    show still runs silently.
    """

    def __init__(self, enabled=True):
        self.available = False
        self.enabled = True
        self.volume = 0.65
        self.rate = 22050
        self.channels = 2
        self.sounds = {}
        self.pending = []
        self.last = {}

        if not enabled:
            return

        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(
                    frequency=22050, size=-16, channels=2, buffer=512
                )

            info = pygame.mixer.get_init()
            if info is None:
                raise pygame.error("mixer did not initialise")

            self.rate, fmt, self.channels = info
            if fmt not in (-16, 32784):
                raise pygame.error(f"unsupported sample format {fmt}")

            pygame.mixer.set_num_channels(32)
            self.build()
            self.available = True
        except (pygame.error, ValueError, OSError) as exc:
            print(f"Audio unavailable: {exc}")
            self.available = False

    def build(self):
        rate = self.rate
        rnd = random.Random(18)

        def sound(samples):
            return pygame.mixer.Sound(buffer=to_pcm(samples, self.channels))

        self.sounds = {
            "whoosh": [
                sound(synth_whoosh(rate, rnd, 0.9)),
                sound(synth_whoosh(rate, rnd, 1.1)),
            ],
            "boom_s": [sound(synth_boom(rate, rnd, 0.0)) for _ in range(2)],
            "boom_m": [sound(synth_boom(rate, rnd, 0.5)) for _ in range(2)],
            "boom_l": [sound(synth_boom(rate, rnd, 1.0)) for _ in range(2)],
            "crackle": [sound(synth_crackle(rate, rnd)) for _ in range(2)],
            "pop": [
                sound(synth_pop(rate, rnd, freq)) for freq in (900, 1250, 1700)
            ],
            "tick": [sound(synth_tone(rate, 880, 0.09, 0.35))],
            "go": [sound(synth_tone(rate, 1320, 0.32, 0.35, 0.35))],
            "blip": [sound(synth_tone(rate, 660, 0.06, 0.25))],
        }

    def adjust_volume(self, amount):
        self.volume = clamp(self.volume + amount, 0.0, 1.0)

    def update(self, dt):
        if not self.pending:
            return

        remaining = []
        for item in self.pending:
            item[0] -= dt
            if item[0] <= 0.0:
                self.play(item[1], item[2], item[3])
            else:
                remaining.append(item)
        self.pending = remaining

    def play(self, name, volume=1.0, pan=0.0, delay=0.0):
        if not self.available or not self.enabled:
            return

        if delay > 0.0:
            self.pending.append([delay, name, volume, pan])
            return

        now = time.perf_counter()
        if now - self.last.get(name, -10.0) < MIN_GAP.get(name, 0.0):
            return
        self.last[name] = now

        bank = self.sounds.get(name)
        if not bank:
            return

        channel = random.choice(bank).play()
        if channel is None:
            return

        level = clamp(volume * self.volume, 0.0, 1.0)
        pan = clamp(pan, -1.0, 1.0)
        left = level * (1.0 - max(0.0, pan) * 0.75)
        right = level * (1.0 + min(0.0, pan) * 0.75)
        channel.set_volume(left, right)


# ============================================================
# SIMULATION OBJECTS
# ============================================================


class Particle:
    """
    One star or spark. Particles can emit trail sparks, split into
    secondary stars, or end with a crackle pop. That is the chain.
    """

    __slots__ = (
        "x", "y", "px", "py", "vx", "vy", "life", "max_life",
        "r", "g", "b", "drag", "grav", "width", "twinkle",
        "trail", "split", "pop", "kind",
    )

    def __init__(
        self,
        x,
        y,
        vx,
        vy,
        life,
        color,
        drag=1.7,
        grav=STAR_GRAVITY,
        width=1,
        twinkle=False,
        trail=0.0,
        split=0.0,
        pop=False,
        kind=STAR,
    ):
        self.x = x
        self.y = y
        self.px = x
        self.py = y
        self.vx = vx
        self.vy = vy
        self.life = life
        self.max_life = life
        self.r, self.g, self.b = color
        self.drag = drag
        self.grav = grav
        self.width = width
        self.twinkle = twinkle
        self.trail = trail
        self.split = split
        self.pop = pop
        self.kind = kind

    def update(self, dt, world):
        self.life -= dt

        if self.life <= 0.0:
            if self.pop:
                world.spawn_pop(self)
            return False

        if self.split and self.life <= self.max_life * self.split:
            world.split_star(self)
            return False

        damping = math.exp(-self.drag * dt)
        self.vx *= damping
        self.vy = self.vy * damping + self.grav * dt
        self.px = self.x
        self.py = self.y
        self.x += self.vx * dt
        self.y += self.vy * dt

        if self.trail and world.rng.random() < self.trail:
            world.spawn_trail(self)

        return self.y < GROUND_Y + 30 and -300 < self.x < SCREEN_W + 300


class Rocket:
    __slots__ = (
        "x", "y", "vx", "vy", "kind", "size", "palette",
        "target_y", "age", "spark_timer",
    )

    def __init__(self, x, y, vx, vy, kind, size, palette, target_y):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.kind = kind
        self.size = size
        self.palette = palette
        self.target_y = target_y
        self.age = 0.0
        self.spark_timer = 0.0

    def update(self, dt, world):
        self.age += dt
        self.vy += ROCKET_GRAVITY * dt
        self.x += self.vx * dt
        self.y += self.vy * dt

        self.spark_timer += dt
        while self.spark_timer >= 0.012:
            self.spark_timer -= 0.012
            world.spawn_rocket_spark(self)

        if self.age > 0.25 and (self.vy >= -25.0 or self.y <= self.target_y):
            world.explode(self)
            return False

        return True


class Flash:
    __slots__ = ("x", "y", "radius", "life", "max_life", "color")

    def __init__(self, x, y, radius, life, color):
        self.x = x
        self.y = y
        self.radius = radius
        self.life = life
        self.max_life = life
        self.color = color

    def advance(self, dt):
        self.life -= dt
        return self.life > 0.0


class FireworksWorld:
    """Pure simulation. It knows nothing about drawing or audio."""

    def __init__(self, seed=None, on_event=None):
        self.rng = random.Random(seed)
        self.on_event = on_event
        self.reset()

    def reset(self):
        self.clear_sky()
        self.time = 0.0
        self.launched = 0
        self.bursts = 0
        self.peak = 0
        self.last_kind = "-"
        self.sky_flash = 0.0
        self.flash_color = (255, 255, 255)

    def clear_sky(self):
        self.rockets = []
        self.particles = []
        self.flashes = []
        self._spawn = []

    def emit(self, name, x, y, power=1.0):
        if self.on_event:
            self.on_event(name, x, y, power)

    def spawn(self, particle):
        if len(self.particles) + len(self._spawn) < MAX_PARTICLES:
            self._spawn.append(particle)

    def add_flash(self, x, y, radius, color):
        if len(self.flashes) >= MAX_FLASHES:
            return
        life = 0.32 if radius > 30.0 else 0.16
        self.flashes.append(Flash(x, y, radius, life, tuple(color)))

    # ---------------------------------------------------------
    # Launching
    # ---------------------------------------------------------

    def launch(self, kind=None, target=None, size=None, palette=None):
        rng = self.rng

        if kind is None:
            kind = rng.choices(KINDS, weights=KIND_WEIGHTS, k=1)[0]
        if size is None:
            size = rng.uniform(0.8, 1.25)

        if target is None:
            start_x = rng.uniform(SCREEN_W * 0.12, SCREEN_W * 0.88)
            target_y = rng.uniform(SCREEN_H * 0.14, SCREEN_H * 0.46)
            target_x = start_x + rng.uniform(-90.0, 90.0)
        else:
            target_x, target_y = target
            target_y = clamp(target_y, 80.0, GROUND_Y - 160.0)
            target_x = clamp(target_x, 60.0, SCREEN_W - 60.0)
            start_x = clamp(
                target_x + rng.uniform(-140.0, 140.0), 40.0, SCREEN_W - 40.0
            )

        start_y = float(GROUND_Y)
        speed = math.sqrt(2.0 * ROCKET_GRAVITY * (start_y - target_y))
        flight_time = speed / ROCKET_GRAVITY
        vx = (target_x - start_x) / flight_time

        if palette is None:
            palette = rng.choice(PALETTES)

        self.rockets.append(
            Rocket(start_x, start_y, vx, -speed, kind, size, palette, target_y)
        )
        self.launched += 1
        self.emit("launch", start_x, start_y, 0.8)

    def explode(self, rocket):
        handler = getattr(self, "_burst_" + rocket.kind)
        handler(rocket.x, rocket.y, rocket.size, rocket.palette)

        self.bursts += 1
        self.last_kind = rocket.kind
        self.add_flash(rocket.x, rocket.y, 70.0 * rocket.size, rocket.palette[0])
        self.sky_flash = max(self.sky_flash, min(1.0, 0.55 * rocket.size))
        self.flash_color = rocket.palette[0]

        self.emit("burst", rocket.x, rocket.y, rocket.size)
        if rocket.kind in ("chrysanthemum", "willow", "crossette"):
            self.emit("crackle", rocket.x, rocket.y, rocket.size)

    # ---------------------------------------------------------
    # Chained emitters
    # ---------------------------------------------------------

    def spawn_rocket_spark(self, rocket):
        rng = self.rng
        self.spawn(
            Particle(
                rocket.x,
                rocket.y,
                rng.uniform(-18.0, 18.0) - rocket.vx * 0.1,
                rng.uniform(30.0, 90.0),
                rng.uniform(0.3, 0.6),
                (255, 190, 100),
                drag=1.5,
                grav=100.0,
                kind=SPARK,
            )
        )

    def spawn_trail(self, p):
        rng = self.rng
        color = (int(p.r * 0.75), int(p.g * 0.75), int(p.b * 0.75))
        self.spawn(
            Particle(
                p.x,
                p.y,
                p.vx * 0.04 + rng.uniform(-16.0, 16.0),
                p.vy * 0.04 + rng.uniform(-8.0, 22.0),
                rng.uniform(0.35, 0.7),
                color,
                drag=2.4,
                grav=70.0,
                kind=SPARK,
            )
        )

    def split_star(self, p):
        """Crossette: one star becomes four, in an X pattern."""
        rng = self.rng
        heading = math.atan2(p.vy, p.vx)
        color = mix_color((p.r, p.g, p.b), (255, 255, 255), 0.45)

        for k in range(4):
            angle = heading + math.pi / 4.0 + k * math.pi / 2.0
            speed = rng.uniform(140.0, 185.0)
            self.spawn(
                Particle(
                    p.x,
                    p.y,
                    math.cos(angle) * speed + p.vx * 0.25,
                    math.sin(angle) * speed + p.vy * 0.25,
                    rng.uniform(0.7, 1.0),
                    color,
                    drag=2.0,
                    grav=95.0,
                    width=2,
                    twinkle=True,
                    pop=rng.random() < 0.55,
                )
            )

        self.add_flash(p.x, p.y, 16.0, color)
        self.emit("pop", p.x, p.y, 0.6)

    def spawn_pop(self, p):
        """The last link in the chain: a tiny crackle."""
        rng = self.rng

        for _ in range(3):
            angle = rng.uniform(0.0, math.tau)
            speed = rng.uniform(50.0, 130.0)
            self.spawn(
                Particle(
                    p.x,
                    p.y,
                    math.cos(angle) * speed,
                    math.sin(angle) * speed,
                    rng.uniform(0.18, 0.34),
                    (255, 236, 200),
                    drag=3.0,
                    grav=40.0,
                    kind=SPARK,
                )
            )

        self.add_flash(p.x, p.y, 10.0, (p.r, p.g, p.b))
        self.emit("pop", p.x, p.y, 0.4)

    # ---------------------------------------------------------
    # Shell designs
    # ---------------------------------------------------------

    def _radial(
        self,
        x,
        y,
        count,
        base,
        palette,
        life,
        trail=0.0,
        width=1,
        drag=1.7,
        grav=STAR_GRAVITY,
        tone=0.72,
    ):
        rng = self.rng

        for _ in range(count):
            angle = rng.uniform(0.0, math.tau)
            speed = base * (1.0 - 0.65 * rng.random() ** 2)
            color = palette[0] if rng.random() < tone else palette[1]
            self.spawn(
                Particle(
                    x,
                    y,
                    math.cos(angle) * speed,
                    math.sin(angle) * speed,
                    rng.uniform(life[0], life[1]),
                    color,
                    drag=drag,
                    grav=grav,
                    width=width,
                    twinkle=rng.random() < 0.35,
                    trail=trail,
                )
            )

    def _burst_peony(self, x, y, size, palette):
        rng = self.rng
        self._radial(
            x, y,
            int(rng.uniform(105, 145)),
            rng.uniform(300, 350) * size,
            palette,
            (1.6, 2.2),
        )

    def _burst_chrysanthemum(self, x, y, size, palette):
        rng = self.rng
        self._radial(
            x, y,
            int(rng.uniform(90, 120)),
            rng.uniform(290, 340) * size,
            palette,
            (2.0, 2.7),
            trail=0.06,
        )

    def _burst_ring(self, x, y, size, palette):
        rng = self.rng
        tilt = rng.uniform(0.25, 1.0)
        rotation = rng.uniform(0.0, math.pi)
        cos_r = math.cos(rotation)
        sin_r = math.sin(rotation)
        count = 72
        speed = rng.uniform(290.0, 330.0) * size

        for i in range(count):
            angle = i / count * math.tau
            ux = math.cos(angle)
            uy = math.sin(angle) * tilt
            self.spawn(
                Particle(
                    x,
                    y,
                    (ux * cos_r - uy * sin_r) * speed,
                    (ux * sin_r + uy * cos_r) * speed,
                    rng.uniform(1.7, 2.1),
                    palette[0],
                    width=2,
                )
            )

        if rng.random() < 0.5:
            inner = (palette[1], palette[1])
            self._radial(x, y, 36, 150.0 * size, inner, (1.2, 1.6))

    def _burst_willow(self, x, y, size, palette):
        rng = self.rng
        self._radial(
            x, y,
            95,
            rng.uniform(190, 260) * size,
            GOLD,
            (3.2, 4.2),
            trail=0.10,
            width=2,
            drag=1.9,
            grav=190.0,
            tone=0.8,
        )

    def _burst_crossette(self, x, y, size, palette):
        rng = self.rng
        count = rng.randint(14, 18)
        speed = rng.uniform(250.0, 300.0) * size

        for i in range(count):
            angle = i / count * math.tau + rng.uniform(-0.15, 0.15)
            self.spawn(
                Particle(
                    x,
                    y,
                    math.cos(angle) * speed,
                    math.sin(angle) * speed,
                    rng.uniform(1.6, 1.9),
                    palette[i % 2],
                    drag=1.5,
                    width=2,
                    split=0.5,
                )
            )

    def _burst_heart(self, x, y, size, palette):
        rng = self.rng
        count = 80
        scale = 21.0 * size

        for i in range(count):
            t = i / count * math.tau
            hx = 16.0 * math.sin(t) ** 3
            hy = (
                13.0 * math.cos(t)
                - 5.0 * math.cos(2.0 * t)
                - 2.0 * math.cos(3.0 * t)
                - math.cos(4.0 * t)
            )
            jitter = rng.uniform(0.97, 1.03)
            self.spawn(
                Particle(
                    x,
                    y,
                    hx * scale * jitter,
                    -hy * scale * jitter,
                    rng.uniform(1.8, 2.2),
                    palette[0],
                    width=2,
                )
            )

    def _burst_double(self, x, y, size, palette):
        rng = self.rng
        self._radial(
            x, y,
            100,
            rng.uniform(320, 360) * size,
            (palette[0], palette[0]),
            (1.7, 2.3),
        )
        self._radial(
            x, y,
            50,
            170.0 * size,
            (palette[1], palette[1]),
            (1.3, 1.8),
        )

    # ---------------------------------------------------------
    # Update
    # ---------------------------------------------------------

    def update(self, dt):
        self.time += dt

        self.rockets = [r for r in self.rockets if r.update(dt, self)]
        self.particles = [p for p in self.particles if p.update(dt, self)]

        if self._spawn:
            self.particles.extend(self._spawn)
            self._spawn = []

        self.flashes = [f for f in self.flashes if f.advance(dt)]
        self.sky_flash = max(0.0, self.sky_flash - dt * 2.4)
        self.peak = max(self.peak, len(self.particles))


class Director:
    """Decides when to launch. Builds in intensity, then finales."""

    def __init__(self, rng):
        self.rng = rng
        self.reset()

    def reset(self):
        self.clock = 0.0
        self.timer = 0.6
        self.finale_left = 0.0
        self.next_finale = 55.0
        self.finales = 0

    def start_finale(self):
        self.finale_left = self.rng.uniform(5.0, 7.0)
        self.timer = 0.0
        self.finales += 1

    def update(self, dt, world):
        rng = self.rng
        self.clock += dt
        self.timer -= dt

        if self.finale_left > 0.0:
            self.finale_left -= dt
            if self.timer <= 0.0:
                world.launch(size=rng.uniform(0.9, 1.3))
                world.launch()
                self.timer = rng.uniform(0.13, 0.28)
            if self.finale_left <= 0.0:
                self.timer = 2.5
                self.next_finale = self.clock + rng.uniform(50.0, 70.0)
            return

        if self.clock >= self.next_finale:
            self.start_finale()
            return

        if self.timer <= 0.0:
            ramp = min(1.0, self.clock / 40.0)
            for _ in range(1 if rng.random() < 0.75 else 2):
                world.launch()
            self.timer = rng.uniform(0.9 - 0.55 * ramp, 1.8 - 0.9 * ramp)


# ============================================================
# SCENERY
# ============================================================


def build_sky():
    surface = pygame.Surface((SCREEN_W, SCREEN_H))
    horizon = (34, 24, 66)

    for y in range(SCREEN_H):
        t = y / (SCREEN_H - 1)
        color = mix_color(BG_TOP, BG_BOTTOM, t)
        if y > GROUND_Y - 220:
            glow = (y - (GROUND_Y - 220)) / 220.0
            color = mix_color(color, horizon, clamp(glow, 0.0, 1.0) * 0.55)
        pygame.draw.line(surface, color, (0, y), (SCREEN_W, y))

    return surface.convert()


def build_skyline():
    surface = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
    rnd = random.Random(1018)
    x = -10

    while x < SCREEN_W:
        width = rnd.randint(34, 92)
        height = rnd.randint(38, 210)
        top = GROUND_Y - height
        shade = rnd.randint(5, 12)

        pygame.draw.rect(
            surface,
            (shade, shade + 1, shade + 8, 255),
            (x, top, width, height + 4),
        )

        for wy in range(top + 10, GROUND_Y - 8, 14):
            for wx in range(x + 7, x + width - 8, 11):
                if rnd.random() < 0.16:
                    lit = (150, 118, 64, 255)
                    if rnd.random() < 0.5:
                        lit = (105, 82, 46, 255)
                    pygame.draw.rect(surface, lit, (wx, wy, 4, 6))

        x += width + rnd.randint(0, 6)

    pygame.draw.rect(
        surface, (4, 5, 12, 255), (0, GROUND_Y, SCREEN_W, SCREEN_H - GROUND_Y)
    )
    return surface.convert_alpha()


def build_stars():
    rnd = random.Random(18)
    stars = []

    for _ in range(170):
        stars.append(
            (
                rnd.randint(0, SCREEN_W - 1),
                int(GROUND_Y * 0.82 * rnd.random() ** 1.3),
                rnd.uniform(90.0, 220.0),
                rnd.uniform(0.0, math.tau),
                rnd.uniform(0.6, 2.4),
                1 if rnd.random() < 0.8 else 2,
            )
        )

    return stars


def build_glow_sprite(size=128):
    sprite = pygame.Surface((size, size))
    sprite.fill((0, 0, 0))
    center = size // 2

    for radius in range(center, 0, -1):
        level = int(255 * (1.0 - radius / center) ** 2.2)
        pygame.draw.circle(sprite, (level, level, level), (center, center), radius)

    return sprite.convert()


# ============================================================
# APPLICATION
# ============================================================


class App:
    def __init__(self, seed=None, audio_enabled=True):
        pygame.mixer.pre_init(22050, -16, 2, 512)
        pygame.init()
        pygame.display.set_caption(
            f"EIDOLON  ·  Project {PROJECT_NUMBER}  ·  {APP_NAME}"
        )
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        self.clock = pygame.time.Clock()

        names = "segoeui,arial,helvetica,dejavusans"
        self.font_small = pygame.font.SysFont(names, 15)
        self.font_med = pygame.font.SysFont(names, 18, bold=True)
        self.font_title = pygame.font.SysFont(names, 68, bold=True)
        self.font_sub = pygame.font.SysFont(names, 22)
        self.font_huge = pygame.font.SysFont(names, 230, bold=True)

        self.audio = AudioEngine(enabled=audio_enabled)
        self.world = FireworksWorld(seed, self.on_world_event)
        self.director = Director(self.world.rng)
        self.draw_rng = random.Random(seed)

        self.sky = build_sky()
        self.skyline = build_skyline()
        self.stars = build_stars()
        self.glow = pygame.Surface((SCREEN_W, SCREEN_H)).convert()
        self.glow.fill((0, 0, 0))
        self.glow_sprite = build_glow_sprite()
        self.flash_cache = {}

        self.kind_keys = {
            pygame.K_1: "peony",
            pygame.K_2: "chrysanthemum",
            pygame.K_3: "ring",
            pygame.K_4: "willow",
            pygame.K_5: "crossette",
            pygame.K_6: "heart",
            pygame.K_7: "double",
        }

        self.running = False
        self.state = "title"
        self.countdown = COUNTDOWN_SECONDS
        self.last_count = None
        self.paused = False
        self.auto = True
        self.bloom = True
        self.trail_index = 1
        self.selected_kind = None
        self.show_hud = True
        self.toast = None
        self.ui_time = 0.0

    # ---------------------------------------------------------
    # Events
    # ---------------------------------------------------------

    def on_world_event(self, name, x, y, power):
        pan = (x / SCREEN_W) * 2.0 - 1.0

        if name == "launch":
            self.audio.play("whoosh", 0.45, pan)
        elif name == "burst":
            if power >= 1.1:
                bank = "boom_l"
            elif power >= 0.92:
                bank = "boom_m"
            else:
                bank = "boom_s"
            delay = 0.05 + (GROUND_Y - y) / GROUND_Y * 0.25
            self.audio.play(bank, 0.55 + 0.35 * min(1.3, power), pan, delay)
        elif name == "crackle":
            delay = 0.2 + (GROUND_Y - y) / GROUND_Y * 0.25
            self.audio.play("crackle", 0.4, pan, delay)
        elif name == "pop":
            self.audio.play("pop", 0.22 * power, pan)

    def notify(self, text, seconds=1.4):
        self.toast = [text, seconds]

    def begin_countdown(self):
        self.state = "countdown"
        self.countdown = COUNTDOWN_SECONDS
        self.last_count = None

    def start_show(self):
        self.state = "show"
        self.paused = False
        self.director.reset()
        self.audio.play("go", 0.8)
        self.world.launch(kind="peony", size=1.1)
        self.notify("LAUNCH", 1.2)

    def on_click(self, pos):
        if self.state != "show" or self.paused:
            return
        self.world.launch(kind=self.selected_kind, target=pos)

    def on_key(self, key):
        if key == pygame.K_ESCAPE:
            self.running = False
            return
        if key == pygame.K_m:
            self.audio.enabled = not self.audio.enabled
            self.notify("Sound " + ("ON" if self.audio.enabled else "OFF"), 0.9)
            return
        if key == pygame.K_LEFTBRACKET:
            self.audio.adjust_volume(-0.05)
            self.notify(f"Volume {int(self.audio.volume * 100)}%", 0.8)
            return
        if key == pygame.K_RIGHTBRACKET:
            self.audio.adjust_volume(0.05)
            self.notify(f"Volume {int(self.audio.volume * 100)}%", 0.8)
            return
        if key == pygame.K_h:
            self.show_hud = not self.show_hud
            return
        if key == pygame.K_SPACE:
            if self.state == "title":
                self.begin_countdown()
            elif self.state == "show":
                self.paused = not self.paused
                self.notify("PAUSED" if self.paused else "RESUMED", 0.9)
            return

        if self.state != "show":
            return

        if key == pygame.K_a:
            self.auto = not self.auto
            self.notify("Auto show " + ("ON" if self.auto else "OFF"), 1.0)
        elif key == pygame.K_f:
            self.director.start_finale()
            self.notify("FINALE", 1.2)
        elif key == pygame.K_c:
            self.world.clear_sky()
            self.glow.fill((0, 0, 0))
            self.notify("Sky cleared", 0.9)
        elif key == pygame.K_r:
            self.world.reset()
            self.director.reset()
            self.glow.fill((0, 0, 0))
            self.notify("Show reset", 0.9)
        elif key == pygame.K_b:
            self.bloom = not self.bloom
            self.notify("Bloom " + ("ON" if self.bloom else "OFF"), 0.9)
        elif key == pygame.K_t:
            self.trail_index = (self.trail_index + 1) % len(TRAIL_LEVELS)
            self.notify("Trails " + TRAIL_LEVELS[self.trail_index][0], 0.9)
        elif key == pygame.K_p:
            self.screenshot()
        elif key == pygame.K_0:
            self.selected_kind = None
            self.notify("Shell: RANDOM", 1.0)
        elif key in self.kind_keys:
            self.selected_kind = self.kind_keys[key]
            self.notify("Shell: " + self.selected_kind.upper(), 1.0)

    def screenshot(self):
        os.makedirs("screenshots", exist_ok=True)
        name = time.strftime("fireworks_%Y%m%d_%H%M%S.png")
        path = os.path.join("screenshots", name)
        pygame.image.save(self.screen, path)
        self.notify("Saved " + path, 1.8)

    # ---------------------------------------------------------
    # Update
    # ---------------------------------------------------------

    def update(self, dt):
        dt = min(dt, 1.0 / 20.0)
        self.ui_time += dt
        self.audio.update(dt)

        if self.toast:
            self.toast[1] -= dt
            if self.toast[1] <= 0.0:
                self.toast = None

        if self.state == "countdown":
            self.countdown -= dt
            number = max(0, math.ceil(self.countdown))
            if number != self.last_count and number > 0:
                self.audio.play("tick", 0.8)
                self.last_count = number
            if self.countdown <= 0.0:
                self.start_show()
        elif self.state == "show" and not self.paused:
            if self.auto:
                self.director.update(dt, self.world)
            self.world.update(dt)

    # ---------------------------------------------------------
    # Drawing
    # ---------------------------------------------------------

    def flash_sprite(self, color):
        sprite = self.flash_cache.get(color)
        if sprite is None:
            sprite = self.glow_sprite.copy()
            sprite.fill(color, special_flags=pygame.BLEND_RGB_MULT)
            self.flash_cache[color] = sprite
        return sprite

    def draw_stars(self):
        t = self.ui_time
        for x, y, base, phase, speed, size in self.stars:
            level = int(base * (0.55 + 0.45 * math.sin(t * speed + phase)))
            level = int(clamp(level, 0, 255))
            color = (level, level, min(255, level + 20))
            self.screen.fill(color, (x, y, size, size))

    def render_glow(self):
        glow = self.glow
        world = self.world
        fade = TRAIL_LEVELS[self.trail_index][1]
        glow.fill((fade, fade, fade), special_flags=pygame.BLEND_RGB_SUB)

        line = pygame.draw.line
        circle = pygame.draw.circle
        rnd = self.draw_rng.random

        for p in world.particles:
            t = p.life / p.max_life
            if t > 1.0:
                t = 1.0
            b = t**0.55 if p.kind == STAR else t
            if p.twinkle and t < 0.65:
                b *= 0.5 + 0.5 * rnd()

            r = int(p.r * b)
            g = int(p.g * b)
            bl = int(p.b * b)
            if t > 0.9:
                r = min(255, r + 110)
                g = min(255, g + 110)
                bl = min(255, bl + 110)

            line(
                glow,
                (r, g, bl),
                (int(p.px), int(p.py)),
                (int(p.x), int(p.y)),
                p.width,
            )

        for rocket in world.rockets:
            pos = (int(rocket.x), int(rocket.y))
            circle(glow, (90, 64, 36), pos, 6)
            circle(glow, (255, 235, 190), pos, 3)

        for flash in world.flashes:
            progress = 1.0 - flash.life / flash.max_life
            size = max(3, int(flash.radius * (0.5 + 0.8 * progress)))
            level = int(255 * (1.0 - progress) ** 1.7)
            if level <= 4:
                continue
            sprite = pygame.transform.scale(
                self.flash_sprite(flash.color), (size * 2, size * 2)
            )
            sprite.fill((level, level, level), special_flags=pygame.BLEND_RGB_MULT)
            glow.blit(
                sprite,
                (int(flash.x) - size, int(flash.y) - size),
                special_flags=pygame.BLEND_RGB_ADD,
            )

    def draw_text(self, font, value, color, pos):
        image = font.render(str(value), True, color)
        self.screen.blit(image, pos)
        return image

    def draw_centered(self, font, value, color, center):
        image = font.render(str(value), True, color)
        self.screen.blit(image, image.get_rect(center=center))

    def draw_panel(self, x, y, width, height, alpha=170):
        panel = pygame.Surface((width, height), pygame.SRCALPHA)
        rect = panel.get_rect()
        pygame.draw.rect(panel, (8, 10, 24, alpha), rect, border_radius=10)
        pygame.draw.rect(
            panel, (60, 70, 120, 160), rect, width=1, border_radius=10
        )
        self.screen.blit(panel, (x, y))

    def draw_hud(self):
        world = self.world
        kind = self.selected_kind.upper() if self.selected_kind else "RANDOM"
        sound = "OFF"
        if not self.audio.available:
            sound = "N/A"
        elif self.audio.enabled:
            sound = f"{int(self.audio.volume * 100)}%"

        lines = [
            (self.font_med, UI_ACCENT, f"PROJECT {PROJECT_NUMBER}  ·  {APP_NAME}"),
            (self.font_small, UI_TEXT, f"Shell  {kind}      Last  {world.last_kind.upper()}"),
            (
                self.font_small,
                UI_TEXT,
                f"Auto {'ON' if self.auto else 'OFF'}   "
                f"Bloom {'ON' if self.bloom else 'OFF'}   "
                f"Trails {TRAIL_LEVELS[self.trail_index][0]}   "
                f"Sound {sound}",
            ),
            (
                self.font_small,
                UI_TEXT,
                f"Rockets {len(world.rockets)}   "
                f"Particles {len(world.particles)}   Peak {world.peak}",
            ),
            (
                self.font_small,
                UI_DIM,
                f"Launched {world.launched}   Bursts {world.bursts}   "
                f"FPS {self.clock.get_fps():.0f}",
            ),
        ]

        images = [font.render(text, True, color) for font, color, text in lines]
        width = max(image.get_width() for image in images) + 28
        height = sum(image.get_height() + 4 for image in images) + 18
        self.draw_panel(16, 16, width, height)

        y = 25
        for image in images:
            self.screen.blit(image, (30, y))
            y += image.get_height() + 4

        hint = (
            "SPACE pause · click launch · 1-7 shell · 0 random · A auto · "
            "F finale · B bloom · T trails · M sound · H hide · ESC quit"
        )
        image = self.font_small.render(hint, True, UI_DIM)
        rect = image.get_rect(center=(SCREEN_W // 2, SCREEN_H - 24))
        self.draw_panel(rect.x - 14, rect.y - 8, rect.width + 28, rect.height + 16, 130)
        self.screen.blit(image, rect)

    def draw_title(self):
        self.draw_centered(
            self.font_title, APP_NAME, UI_TEXT, (SCREEN_W // 2, 250)
        )
        self.draw_centered(
            self.font_sub,
            f"PROJECT {PROJECT_NUMBER}  ·  CHAINED PARTICLE EMITTERS",
            UI_ACCENT,
            (SCREEN_W // 2, 312),
        )
        if int(self.ui_time * 1.6) % 2 == 0:
            self.draw_centered(
                self.font_sub,
                "PRESS SPACE TO LIGHT THE FUSE",
                UI_TEXT,
                (SCREEN_W // 2, 400),
            )

    def draw_countdown(self):
        number = max(1, math.ceil(self.countdown))
        fraction = number - self.countdown
        scale = 1.0 + 0.35 * (1.0 - fraction) ** 2
        image = self.font_huge.render(str(number), True, UI_TEXT)
        size = (
            max(1, int(image.get_width() * scale)),
            max(1, int(image.get_height() * scale)),
        )
        image = pygame.transform.smoothscale(image, size)
        image.set_alpha(int(255 * (1.0 - fraction**3)))
        self.screen.blit(image, image.get_rect(center=(SCREEN_W // 2, 320)))

    def draw_toast(self):
        if not self.toast:
            return
        text, seconds = self.toast
        alpha = int(255 * clamp(seconds / 0.35, 0.0, 1.0))
        image = self.font_med.render(text, True, UI_ACCENT)
        image.set_alpha(alpha)
        rect = image.get_rect(center=(SCREEN_W // 2, SCREEN_H - 70))
        self.draw_panel(rect.x - 16, rect.y - 8, rect.width + 32, rect.height + 16, 150)
        self.screen.blit(image, rect)

    def draw(self):
        screen = self.screen
        world = self.world

        screen.blit(self.sky, (0, 0))
        self.draw_stars()

        if world.sky_flash > 0.01:
            screen.fill(
                scale_color(world.flash_color, world.sky_flash * 0.16),
                special_flags=pygame.BLEND_RGB_ADD,
            )

        if not self.paused:
            self.render_glow()

        if self.bloom:
            small = pygame.transform.smoothscale(
                self.glow, (SCREEN_W // 6, SCREEN_H // 6)
            )
            halo = pygame.transform.smoothscale(small, (SCREEN_W, SCREEN_H))
            screen.blit(halo, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
            screen.blit(halo, (0, 0), special_flags=pygame.BLEND_RGB_ADD)

        screen.blit(self.glow, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
        screen.blit(self.skyline, (0, 0))

        if self.state == "title":
            self.draw_title()
        elif self.state == "countdown":
            self.draw_countdown()
        elif self.state == "show":
            if self.director.finale_left > 0.0 and int(self.ui_time * 3) % 2 == 0:
                self.draw_centered(
                    self.font_med, "FINALE", UI_ACCENT, (SCREEN_W // 2, 40)
                )
            if self.paused:
                self.draw_centered(
                    self.font_title, "PAUSED", UI_TEXT, (SCREEN_W // 2, 300)
                )

        if self.show_hud:
            self.draw_hud()
        self.draw_toast()

    def run(self):
        self.running = True

        while self.running:
            dt = self.clock.tick(FPS) / 1000.0

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN:
                    self.on_key(event.key)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self.on_click(event.pos)

            self.update(dt)
            self.draw()
            pygame.display.flip()

        pygame.quit()


# ============================================================
# SELF-TEST
# ============================================================


def smoke_test():
    print("EIDOLON Project 018 smoke test")

    # 1. Simulation logic, no window required.
    events = {}

    def record(name, x, y, power):
        assert math.isfinite(x) and math.isfinite(y), "non-finite event"
        events[name] = events.get(name, 0) + 1

    world = FireworksWorld(seed=18, on_event=record)
    director = Director(world.rng)
    dt = 1.0 / 60.0

    for index, kind in enumerate(KINDS, start=1):
        world.launch(kind=kind, size=1.0)
        for _ in range(300):
            world.update(dt)
            if world.bursts >= index:
                break
        else:
            raise AssertionError(f"{kind} rocket never exploded")
        world.update(dt)
        assert len(world.particles) > 20, f"{kind} produced too few particles"
        world.clear_sky()

    world.reset()
    events.clear()
    director.start_finale()
    for step in range(60 * 30):
        director.update(dt, world)
        world.update(dt)
        assert len(world.particles) <= MAX_PARTICLES, "particle cap exceeded"
        if step % 60 == 0:
            for p in world.particles:
                assert all(
                    math.isfinite(v) for v in (p.x, p.y, p.vx, p.vy, p.life)
                ), "non-finite particle"

    assert world.bursts >= 12, "too few bursts in 30 seconds"
    assert events.get("launch") == world.launched, "launch events mismatch"
    assert events.get("burst") == world.bursts, "burst events mismatch"
    assert events.get("pop", 0) > 0, "no crackle pops were produced"
    print(
        f"  simulation ok: {world.launched} rockets, {world.bursts} bursts, "
        f"peak {world.peak} particles"
    )

    # 2. Audio synthesis, no mixer required.
    rnd = random.Random(1)
    rate = 22050
    buffers = {
        "whoosh": synth_whoosh(rate, rnd, 0.5),
        "boom": synth_boom(rate, rnd, 1.0),
        "crackle": synth_crackle(rate, rnd),
        "pop": synth_pop(rate, rnd, 1200),
        "tone": synth_tone(rate, 880, 0.1),
    }
    for name, samples in buffers.items():
        assert samples and all(math.isfinite(s) for s in samples), name
        assert max(abs(s) for s in samples) > 0.01, f"{name} is silent"
        assert len(to_pcm(samples, 2)) == len(samples) * 4, name
        assert len(to_pcm(samples, 1)) == len(samples) * 2, name
    print("  audio synthesis ok")

    # 3. Render a few seconds through the real pygame code path.
    try:
        app = App(seed=18, audio_enabled=True)
    except pygame.error as exc:
        print(f"  render check skipped: {exc}")
        print("SMOKE TEST PASSED (without rendering)")
        return 0

    app.begin_countdown()
    for _ in range(60 * 5):
        app.update(dt)
        app.draw()
    assert app.state == "show", "countdown did not start the show"

    for key in (
        pygame.K_a, pygame.K_a, pygame.K_t, pygame.K_b, pygame.K_b,
        pygame.K_5, pygame.K_f, pygame.K_0, pygame.K_h, pygame.K_h,
    ):
        app.on_key(key)
    app.on_click((640, 200))
    for _ in range(60 * 6):
        app.update(dt)
        app.draw()

    app.on_key(pygame.K_SPACE)
    app.update(dt)
    app.draw()
    app.on_key(pygame.K_SPACE)
    pygame.quit()
    print("  rendering ok")
    print("SMOKE TEST PASSED")
    return 0


def main():
    parser = argparse.ArgumentParser(description="EIDOLON Project 018: Fireworks Show")
    parser.add_argument("--smoke-test", action="store_true", help="run a headless self-test")
    parser.add_argument("--seed", type=int, default=None, help="repeatable show")
    parser.add_argument("--no-audio", action="store_true", help="disable sound")
    args = parser.parse_args()

    if args.smoke_test:
        return smoke_test()

    try:
        App(seed=args.seed, audio_enabled=not args.no_audio).run()
    except KeyboardInterrupt:
        pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())