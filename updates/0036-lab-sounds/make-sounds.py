#!/usr/bin/env python3
"""Makes the lab's own sounds (update 0036) from code, so there are no
recordings and no licences to worry about. Not installed on the laptops;
rerun only to change a sound:  python3 -I make-sounds.py
Writes 16-bit mono WAV files to files/usr/local/share/lab-sounds/."""

import math
import os
import random
import struct
import wave

RATE = 22050
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "files", "usr", "local", "share", "lab-sounds")


def write(name, samples):
    peak = max(1e-9, max(abs(s) for s in samples))
    data = b"".join(struct.pack("<h", int(32000 * 0.9 * s / peak)) for s in samples)
    with wave.open(os.path.join(OUT, name + ".wav"), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(data)


def tick():
    """A clock tick: a short woody click."""
    rng = random.Random(1)
    n = int(0.06 * RATE)
    out = []
    for i in range(n):
        t = i / RATE
        env = math.exp(-t * 90)
        out.append(env * (0.6 * math.sin(2 * math.pi * 1900 * t) + 0.3 * math.sin(2 * math.pi * 3100 * t)
                          + 0.25 * (rng.random() * 2 - 1)))
    return out


def note(freq, length, start_env=0.01, decay=2.5):
    out = []
    for i in range(int(length * RATE)):
        t = i / RATE
        env = min(1, t / start_env) * math.exp(-t * decay)
        vibrato = 1 + 0.004 * math.sin(2 * math.pi * 5.5 * t) * min(1, t * 3)
        s = sum(a * math.sin(2 * math.pi * freq * k * vibrato * t) for k, a in ((1, 1), (2, 0.5), (3, 0.35), (4, 0.2)))
        out.append(env * s)
    return out


def mix(parts, total):
    out = [0.0] * int(total * RATE)
    for start, samples in parts:
        offset = int(start * RATE)
        for i, s in enumerate(samples):
            if offset + i < len(out):
                out[offset + i] += s
    return out


def tada():
    """Ta-da!: two short notes, then a big major chord."""
    c, e, g, c2 = 523.25, 659.25, 783.99, 1046.5
    parts = [(0.0, note(g, 0.16, decay=8)), (0.17, note(g, 0.16, decay=8))]
    for f in (c, e, g, c2):
        parts.append((0.36, note(f, 1.4, decay=1.6)))
    return mix(parts, 1.8)


def applause():
    """A crowd clapping for about 3 seconds, fading out."""
    rng = random.Random(7)
    total = 3.2
    out = [0.0] * int(total * RATE)
    for _ in range(900):
        start = rng.random() * (total - 0.1)
        loud = (0.4 + 0.6 * rng.random()) * (1 if start < 2.0 else max(0, (total - start) / (total - 2.0)))
        tone = rng.uniform(0.3, 0.8)          # low-pass amount: each clapper sounds a bit different
        last = 0.0
        offset = int(start * RATE)
        for i in range(int(0.03 * RATE)):
            if offset + i >= len(out):
                break
            raw = rng.random() * 2 - 1
            last = last + tone * (raw - last)
            out[offset + i] += loud * math.exp(-i / RATE * 160) * last
    return out


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    write("tick", tick())
    write("tada", tada())
    write("applause", applause())
    print("wrote", ", ".join(sorted(os.listdir(OUT))))
