
from .sc_rng import SCRng

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

        self.section = 1
        for i in range(4):
            for _bar in range(4):
                la, lo = self._pos()
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

        self.section = 4
        for _b in range(4):
            la, lo = self._pos()
            rng = SCRng(lo % 9562447)
            root = choose_chord_root(lo % 656753)
            self.chord_root = root
            notes = major(root)
            rel = location_release(0.1, la, lo)
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
