# world-o-tildagon

GPS-driven acid techno on the Tildagon. A port of [world-o-techno](https://github.com/jarkman/world-o-techno)
by @jarkman.

## What's in the box

| file | what |
|---|---|
| `app.py` | Tildagon app: port menus, asyncio audio + GPS tasks, status UI |
| `sequencer.py` | Faithful port of the Sonic Pi algorithm (all four sections, satellite-count mode) |
| `sc_rng.py` | SuperCollider-compatible RNG (verified: seed 196988 → C5/87, E5/72, A4/69, C5/70) |
| `synth.py` | Audio engine: `@micropython.viper` inner loops + Python control rate |
| `bd_*.pcm` | Real Sonic Pi drum samples, 22050 Hz raw int16 mono |
| `gps_source.py` | Mock GPS (model-village test coords) + minimal NMEA/UART reader |

## Hardware / wiring (PCM5102A GY-PCM5102 board)

Plug the DAC hexpansion into any port. `HexpansionConfig.pin[0..3]` = HS1..HS4.

| PCM5102A pin | hexpansion pin | notes |
|---|---|---|
| VIN | 3V3 | board has its own regulator/filtering |
| GND | GND | |
| BCK | HS1 | bit clock |
| LCK / LRCK | HS2 | word select |
| DIN | HS3 | data |
| **SCK** | **GND** | **required** — grounding SCK makes the PCM5102A generate its master clock from BCK via internal PLL |

On the back of the GY board, check the solder bridges: `3 (XSMT)` must be
bridged **H**, `4 (FMT)` bridged **L** (I2S). Most boards ship this way; if you
get silence with everything else right, check these first.

GPS hexpansion: NMEA at 9600 baud over UART. `gps_source.py` assumes GPS-TX →
HS1 (badge RX) — flip `GPS_RX_PIN_IDX`/`GPS_TX_PIN_IDX` at the top of the file
if you see no sentences. If you already have working GPS code, anything that
implements `has_fix() / lat() / lon() / speed() / satellites()` drops straight in.

## Install

```bash
mpremote cp -r world_o_techno :/apps/world_o_techno
```

Launch from the badge menu, pick the DAC port, then pick "Test coords" or the
GPS port. CANCEL stops audio and exits. With no fix you get the original's
satellite-count thumps; with a fix, the four-section tune, re-reading position
every bar so you hear motion as soon as possible.

## Running in the badge simulator

The app imports and runs in the Tildagon simulator (CPython): the viper
kernels fall back to plain-Python equivalents (verified byte-identical
output). The sim has no I2S peripheral, but it is a pygame app, so audio is
routed through `pygame.mixer` instead — you get real sound on your laptop
(screen shows "sim audio: pygame"). If the mixer can't start it degrades to
silent real-time mode ("sim: no audio device") with the sequencer and UI
still live. Pick any DAC port, then "Test coords".

## How it works (and why)

Everything runs at two rates, the same split SuperCollider itself uses:

- **Audio rate** — viper (compiled-to-native) integer kernels: saw / 3×PWM-pulse
  oscillators, a 2×-oversampled Chamberlin SVF resonant low-pass, ramped gain,
  cubic soft-clip, mix into an int16 mono buffer. Renders a full 20 s cycle in
  ~10 ms on the unix port; the ESP32-S3 is roughly 100× slower, still ~20×
  real time.
- **Control rate** (every 128 samples) — plain Python: curve-2 envelope lookup
  (`1 − (e^{2t}−1)/(e²−1)`, the SC `env_curve: 2` shape), filter coefficient
  recalc from `cutoff_min(46 Hz) + env × midicps(cutoff)`, `rq = 1 − res`,
  slicer LFO, prophet PWM.

Output goes to `machine.I2S` (16-bit mono, 22050 Hz) through
`asyncio.StreamWriter`, so the UI stays responsive while a 16 KB DMA buffer
(~370 ms) absorbs GC pauses. The renderer stays one step ahead of playback.

A note on the filter: a fixed-point port of SC's exact RLPF biquad was tried
first and is numerically unstable at the 46 Hz cutoff floor (`a0` quantises to
zero in Q12/Q14). The SVF has good low-frequency coefficient behaviour in fixed
point — it's what ESP32 hardware 303 clones like AcidBox use for the same
reason.

A note on viper portability: `ptr32` loads are **unsigned**, so the filter
states are stored with a +65536 bias to keep them non-negative. On the 32-bit
badge the raw bits would happen to work anyway, but on 64-bit MicroPython
ports (and in testing) unbiased negative state reads back as a huge positive
and the filter explodes. The viper and plain-Python kernel paths are verified
byte-identical.

## Known deviations from Sonic Pi

- Filter is an SVF, not SC's shipped (and unreproducible — see porting notes)
  tb303 binary; cutoff clamps at 7 kHz for stability (vs. sim's 80 Hz floor
  problem — the low end is now correct).
- `:prophet` is 3 detuned PWM pulses, not 5.
- Section 3's `with_fx :reverb` and true per-sample envelopes are not
  implemented (envelope/coefficients update every 5.8 ms).
- Drums are the **real Sonic Pi samples** (`bd_fat.pcm`, `bd_boom.pcm`,
  `bd_haus.pcm` — resampled to 22050 Hz raw int16, shipped in the app folder
  and loaded at startup, normalised to a common peak). If the files are
  missing it falls back to a synthesised kick.
- The saw oscillator is polyBLEP band-limited to keep alias fizz out of the
  top end; the 3-osc prophet pulses are naive (their aliasing is masked by
  detune and PWM).
- Resonant peaks drive into a cubic soft-clip rather than SC's headroom —
  measured <2% of samples at the ceiling, which reads as drive, not distortion.

Sequencer, chord selection, seeds, SC RNG, `locationRelease` (including the
Ruby integer-division quirk) and section structure are exact — verified against
the values in the porting notes at the model-village test coordinates.
