# world-o-techno sequencer - faithful port of world-o-techno.rb (Sonic Pi v2.6)
# by jarkman (Richard Sewell), hacked around by RS & JHR.
#
# Pure Python, no imports beyond sc_rng - identical behaviour under CPython
# (sim / unit tests) and MicroPython (badge).
#
# Yields Step tuples:
#   (dur_s, voice, midi_note, release_s, cutoff_midi, sp_res, kick_amp, slicer_period)
#     voice          'tb303' | 'prophet' | None (kick-only step)
#     midi_note      MIDI note number or None
#     release_s      Sonic Pi release (attack is always 0)
#     cutoff_midi    Sonic Pi cutoff (MIDI, may be float in section 4)
#     sp_res         Sonic Pi res param (rq = 1 - sp_res in the synth)
#     kick_amp       0.0 = no kick this step, else relative kick gain
#     slicer_period  0 = no slicer, else slicer LFO period in seconds (mix 0.75)

from .sc_rng import SCRng

# in pitch order to give a systematic variation as you move
# :a1 :c1 :e1 :a2 :c2 :e2 :a3 :c3 :e3 :a4 :c4 :e4  (Sonic Pi octave numbering)
CHORD_MIDI_ROOTS = [
    33, 24, 28,   # a1, c1, e1
    45, 36, 40,   # a2, c2, e2
    57, 48, 52,   # a3, c3, e3
    69, 60, 64,   # a4, c4, e4
]

STEP = 0.125          # sleep 0.125 in the original
STEP_SLOW = 0.25      # section 4


def choose_chord_root(chooser):
    # Ruby: i = (chooser/5) % chords.size   (integer division)
    return CHORD_MIDI_ROOTS[(int(chooser) // 5) % len(CHORD_MIDI_ROOTS)]


def minor(root):
    return [root, root + 3, root + 7]


def major(root):
    return [root, root + 4, root + 7]


def lat_int(lat):
    return round(abs(lat) * 300000)


def lon_int(lon):
    return round(abs(lon) * 300000)


def location_release(r, la, lo):
    # Ruby integer division: ((la+lo)%30)/30 == 0 always, so factor is 0.5.
    # Kept written out faithfully anyway.
    factor = (la + lo) % 30
    factor = (factor // 30) + 0.5
    return r * factor


class Sequencer:
    """Streams the four-section tune, re-reading GPS at every bar (like the
    original, so you hear motion as soon as possible). If fix is lost between
    sections the cycle ends early and the caller drops back to satellite mode.
    """

    def __init__(self, gps):
        self.gps = gps
        self.section = 0      # for the UI
        self.chord_root = 0   # for the UI

    def _pos(self):
        return lat_int(self.gps.lat()), lon_int(self.gps.lon())

    def cycle(self):
        gps = self.gps

        # ---- Section 1: 4 x (4 bars x 4 notes), :tb303, minor -------------
        self.section = 1
        for i in range(4):
            for _bar in range(4):
                la, lo = self._pos()
                # use_random_seed long (lonInt%100) is set in the original but
                # overwritten before any rand is consumed - no effect.
                root = choose_chord_root(lo % 656753)
                self.chord_root = root
                rng = SCRng(lo % 257867)
                notes = minor(root)
                rel = location_release(0.1, la, lo)
                for k in range(4):
                    n = rng.choose(notes)
                    cut = rng.irand(50, 90) + i * 10
                    yield (STEP, 'tb303', n, rel, cut, 0.9,
                           1.0 if k == 0 else 0.0, 0)

        if not gps.has_fix():
            return

        # ---- Section 2: 8 bars, :tb303, res follows speed ------------------
        self.section = 2
        for i in range(8):
            la, lo = self._pos()
            rng = SCRng(la % 1412041)
            root = choose_chord_root(lo % 656753)
            self.chord_root = root
            notes = minor(root)
            rel = location_release(0.05, la, lo)
            gspeed = gps.speed() % 1.0
            for k in range(4):
                n = rng.choose(notes)
                cut = rng.irand(70, 98) + i
                yield (STEP, 'tb303', n, rel, cut, gspeed,
                       1.0 if k == 0 else 0.0, 0)

        if not gps.has_fix():
            return

        # ---- Section 3: 8 bars, :prophet, chord from LATITUDE ---------------
        # (with_fx :reverb in the original - not implemented yet)
        self.section = 3
        for _m in range(8):
            la, lo = self._pos()
            rng = SCRng((lo + la) % 2256197)
            root = choose_chord_root(la % 656753)
            self.chord_root = root
            notes = minor(root)
            rel = location_release(0.08, la, lo)
            for k in range(4):
                n = rng.choose(notes)
                cut = rng.irand(110, 130)
                yield (STEP, 'prophet', n, rel, cut, 0.7,
                       1.0 if k == 0 else 0.0, 0)

        if not gps.has_fix():
            return

        # ---- Section 4: 4 bars, :tb303, MAJOR, slicer, sleep 0.25 -----------
        self.section = 4
        for _b in range(4):
            la, lo = self._pos()
            rng = SCRng(lo % 9562447)
            root = choose_chord_root(lo % 656753)
            self.chord_root = root
            notes = major(root)
            rel = location_release(0.1, la, lo)
            # slat = latInt.modulo(1) + 0.1 -> latInt is an integer, so 0.1
            slicer_period = (la % 1) + 0.1
            for k in range(4):
                n = rng.choose(notes)
                cut = rng.rand(50, 100)          # float rrand here
                yield (STEP_SLOW, 'tb303', n, rel, cut, 0.9,
                       1.0 if k == 0 else 0.0, slicer_period)

    def satellite_pattern(self):
        """playSatelliteCount: 4 half-second thumps so you can hear
        acquisition progress. Boom first, then fat per satellite, haus quiet."""
        self.section = 0
        for i in range(4):
            c = self.gps.satellites()
            if i == 0:
                drum, amp = 'boom', 1.2        # :bd_boom, amp 10
            elif i <= c:
                drum, amp = 'fat', 1.0         # :bd_fat, amp 6
            else:
                drum, amp = 'haus', 0.25       # :bd_haus, amp 1
            yield (0.5, None, None, 0.0, 0, 0.0, amp, 0, drum)
