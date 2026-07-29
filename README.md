# world-o-tildagon

[world-o-techno](https://github.com/jarkman/world-o-techno) by jarkman,
ported to run natively on the [Tildagon](https://tildagon.badge.emfcamp.org/).

For what world-o-techno *is* and how the music works, see jarkman's repo.
For the DAC hexpansion wiring see [Andrea Campanella's BadgeRadio I2S notes](https://github.com/andreacampanella/BadgeRadio/blob/main/I2S_README.md) I used the same hookup for this project.

## Install

```
mpremote cp -r . :/apps/world_o_techno
```

Launch from the badge menu, pick the DAC port, then a GPS port (or "Test
coords" (currently hardcoded to co-ords for model village at 2026 emf) for testing without a GPS hexpansion).

| file | what |
|---|---|
| `sequencer.py` + `sc_rng.py` | exact port of the Sonic Pi algorithm + SuperCollider's RNG. Don't change these without checking against the verified values (test coords `-2.3757386` must produce seed 196988 → notes 87, 72, 69, 70) |
| `synth.py` | all the sound. viper kernels for audio rate, python for control rate. |
| `gps_source.py` | mock + NMEA gps. anything with `has_fix/lat/lon/speed/satellites` drops in |
| `app.py` | badge app shell, menus, I2S out |
| `bd_*.pcm` | Sonic Pi drum samples, 22050 s16le mono |

## Contributing

Please feel free to raise issues and PRs. Couple of things to be aware of:

- viper kernels: 32 bit ints only, no literals over `0x3FFFFFFF`, ptr32
  loads are unsigned (thats why filter state is stored +65536).
- everything must run identically under CPython (the badge simulator),
  the kernels have plain python fallbacks, keep them in sync. The renders
  are deterministic so a byte compare between the two is the best test.

## Thanks

- [jarkman](https://github.com/jarkman/world-o-techno) whose project this is!
- [Andrea Campanella](https://github.com/andreacampanella/BadgeRadio) from whom I heavily referenced for
  Tildagon I2S groundwork
- [Sonic Pi](https://sonic-pi.net/) for the drum samples
- [Pikesley](https://codeberg.org/pikesley/tildagon-badge-fest/src/branch/main/common/spectrum.py) Sinclair Spectrum font
