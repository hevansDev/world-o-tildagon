# world-o-techno badge synth - pure MicroPython, no custom firmware needed.
#
# Strategy (mirrors how SuperCollider actually works):
#   * audio rate  : @micropython.viper integer inner loops (compiled to native
#                   Xtensa code on the ESP32-S3) - saw/pulse osc + SC RLPF
#                   biquad + linearly-ramped gain, mixed straight into an
#                   int16 mono buffer.
#   * control rate: plain Python every BLOCK samples - envelope lookup,
#                   filter coefficient recalculation (SC recalculates RLPF
#                   coefficients at control rate too), slicer LFO, prophet PWM.
#
# Filter is a resonant low-pass (Chamberlin SVF, 2x oversampled) with SC's
# rq = 1/Q convention. A fixed-point direct-form biquad of SC's RLPF was
# tried first and is numerically unstable at the 46 Hz tb303 cutoff floor
# (a0 quantises to zero); the SVF is what hardware 303 clones (e.g. AcidBox)
# use for the same reason. Cutoff is clamped to 7 kHz for SVF stability.
#
# Envelope is SC env_curve=2 (concave exponential), via a 512-entry Q14 table:
#   env(t) = 1 - (e^(2t) - 1) / (e^2 - 1)
#
# tb303 facts honoured (from retro.clj analysis in the porting notes):
#   * rq = 1 - sp_res (res is inverted; default 0.9 -> rq 0.1)
#   * filter freq = midicps(cutoff_min=30) + filt_env * midicps(cutoff)
#   * amplitude env and filter env share the same shape
#   * amp env is applied AFTER the filter (gates the resonance tail)
#   * attack 0 = instant on

import math
from array import array

import sys

# Viper is only available on real MicroPython, where @micropython.viper is
# recognised by the COMPILER (it is not a runtime attribute - hasattr says
# False even when it works), so probe by compiling a tiny function. The
# Tildagon simulator runs CPython, where the decorator IS a runtime lookup
# and annotations are evaluated, so a dummy decorator + ptr names are needed.
_VIPER = False
if sys.implementation.name == 'micropython':
    import micropython
    try:
        exec("@micropython.viper\ndef __vp(x: int) -> int:\n    return x + 1\n")
        _VIPER = True
    except Exception:
        _VIPER = False
if not _VIPER:               # CPython tests / badge simulator: plain-Python
    class _Dummy:            # kernels (slow, but correct - sim has no I2S
        @staticmethod        # audio anyway)
        def viper(f):
            return f
    micropython = _Dummy()

    def ptr16(x):
        # unsigned view == viper ptr16 semantics (kernels sign-extend manually)
        return memoryview(x).cast('H') if isinstance(x, (bytearray, bytes, memoryview)) else x

    def ptr32(x):
        return x             # array('i') already indexes as ints

    ptr8 = ptr16

SR = 22050
BLOCK = 128
ENV_N = 512
_PH1 = (1 << 30) / SR        # phase increment per Hz (30-bit phase)

# ---------------------------------------------------------------------------
# One-time tables (Python floats are fine here, it only runs at init)
# ---------------------------------------------------------------------------

_E2M1 = math.exp(2.0) - 1.0
ENV_TAB = array('h', [0] * ENV_N)          # Q14, 16384 -> 0
for _i in range(ENV_N):
    _t = _i / (ENV_N - 1)
    _v = 1.0 - (math.exp(2.0 * _t) - 1.0) / _E2M1
    ENV_TAB[_i] = int(max(0.0, _v) * 16384)


def midicps(m):
    return 440.0 * (2.0 ** ((m - 69) / 12.0))


CUTOFF_MIN_HZ = midicps(30)                # ~46.25 Hz, tb303 default cutoff_min


def _make_kick():
    """Stand-in for :bd_fat - exponential pitch sweep 160->48 Hz with a click.
    Precomputed once; mixed in with per-step gain (also reused, quieter/louder,
    for :bd_haus / :bd_boom in satellite mode)."""
    dur = 0.20
    n = int(SR * dur)
    buf = bytearray(2 * n)
    phase = 0.0
    for i in range(n):
        t = i / n
        f = 48.0 + 112.0 * math.exp(-t * 11.0)
        phase += 2.0 * math.pi * f / SR
        a = math.exp(-t * 6.5)
        s = math.sin(phase) * a
        if i < 40:                          # transient click
            s += (1.0 - i / 40.0) * 0.6 * (1 if (i & 2) else -1)
        v = int(max(-1.0, min(1.0, s)) * 13000)
        buf[2 * i] = v & 0xFF
        buf[2 * i + 1] = (v >> 8) & 0xFF
    return buf


# ---------------------------------------------------------------------------
# viper audio-rate kernels
# ---------------------------------------------------------------------------
# Fixed point conventions:
#   osc sample     +-4096            (Q12 of full scale)
#   filter coeffs  Q12
#   filter states  int32, clamped to +-131071
#   gain g0/g1     Q12 (env * slicer * amp), ramped linearly across the block
#   mg             Q10 output make-up gain into the int16 mix buffer

@micropython.viper
def _blk_saw(out: ptr16, ob: int, n: int, st: ptr32, cf: ptr32):
    # st: [0]=phase [1]=dphase [2]=lp [3]=bp
    # cf: [0]=f (Q14, for 2xSR)  [1]=damp (Q14, =rq)
    #     [2]=g0 [3]=g1 (Q12)    [4]=mg (Q12)
    ph = int(st[0]); dph = int(st[1])
    # filter states are stored with a +65536 bias: viper ptr32 loads are
    # unsigned, so raw negative values would read back as huge positives
    # on 64-bit ports (unix/sim testing); biased storage is portable.
    lp = int(st[2]) - 65536; bp = int(st[3]) - 65536
    f = int(cf[0]); dm = int(cf[1])
    g0 = int(cf[2]); g1 = int(cf[3]); mg = int(cf[4])
    g = g0 << 8
    dg = 0
    if n > 0:
        dg = ((g1 - g0) << 8) // n
    dq = dph >> 15                          # dt in Q15 phase units
    if dq < 1:
        dq = 1
    i = 0
    while i < n:
        ph = (ph + dph) & 0x3FFFFFFF
        s = (ph >> 17) - 4096                       # saw, +-4096
        # polyBLEP: smooth the wrap discontinuity (kills alias fizz)
        if ph < dph:
            u = ph // dq                            # Q15 in [0,1)
            s -= ((u + u - ((u * u) >> 15) - 32768) * 4096) >> 15
        elif ph > (0x40000000 - dph):
            u = (ph - 0x40000000) // dq             # Q15 in (-1,0)
            s -= ((((u * u) >> 15) + u + u + 32768) * 4096) >> 15
        # Chamberlin SVF, 2x oversampled (stable to ~7 kHz cutoff)
        lp += (f * bp) >> 14
        hp = s - lp - ((dm * bp) >> 14)
        bp += (f * hp) >> 14
        lp += (f * bp) >> 14
        hp = s - lp - ((dm * bp) >> 14)
        bp += (f * hp) >> 14
        if lp > 65535:
            lp = 65535
        elif lp < -65536:
            lp = -65536
        if bp > 65535:
            bp = 65535
        elif bp < -65536:
            bp = -65536
        # SC order: amp env applied AFTER the filter (so the resonance is
        # gated by the note, instead of ringing on after it ends)
        o = (lp * (((g >> 8) * mg) >> 12)) >> 12
        # cubic soft clip: y = 1.5u - u^3/2 (normalised), ceiling at 32768
        if o > 32768:
            o = 32768
        elif o < -32768:
            o = -32768
        a = o >> 3
        o = ((3 * o) >> 1) - ((((a * a) >> 9) * a) >> 13)
        v = int(out[ob + i])
        if v >= 32768:
            v -= 65536
        v += o
        if v > 32767:
            v = 32767
        elif v < -32768:
            v = -32768
        out[ob + i] = v & 0xFFFF
        g += dg
        i += 1
    st[0] = ph
    st[2] = lp + 65536
    st[3] = bp + 65536


@micropython.viper
def _blk_pulse3(out: ptr16, ob: int, n: int, st: ptr32, cf: ptr32):
    # st: [0..5]=phase/dphase x3  [6..7]=sub-octave phase/dphase
    # st: [8..11]=lp/bp x2 (cascaded SVF, 24 dB/oct like Overtone's prophet)
    # cf: [0]=f [1]=damp (Q14)  [2..3]=g0/g1 (Q12)  [4]=mg (Q12)
    # cf: [5..7]=pulse widths, 30-bit phase units ([8]=sub width)
    p0 = int(st[0]); d0 = int(st[1])
    p1 = int(st[2]); d1 = int(st[3])
    p2 = int(st[4]); d2 = int(st[5])
    p3 = int(st[6]); d3 = int(st[7])
    lp = int(st[8]) - 65536; bp = int(st[9]) - 65536   # biased, see _blk_saw
    lq = int(st[10]) - 65536; bq = int(st[11]) - 65536
    f = int(cf[0]); dm = int(cf[1])
    g0 = int(cf[2]); g1 = int(cf[3]); mg = int(cf[4])
    w0 = int(cf[5]); w1 = int(cf[6]); w2 = int(cf[7]); w3 = int(cf[8])
    g = g0 << 8
    dg = 0
    if n > 0:
        dg = ((g1 - g0) << 8) // n
    i = 0
    while i < n:
        p0 = (p0 + d0) & 0x3FFFFFFF
        p1 = (p1 + d1) & 0x3FFFFFFF
        p2 = (p2 + d2) & 0x3FFFFFFF
        p3 = (p3 + d3) & 0x3FFFFFFF
        s = 0
        if p0 < w0:
            s += 1024
        else:
            s -= 1024
        if p1 < w1:
            s += 1024
        else:
            s -= 1024
        if p2 < w2:
            s += 1024
        else:
            s -= 1024
        # sub-octave pulse (SP's prophet includes one; big part of its body)
        if p3 < w3:
            s += 1024
        else:
            s -= 1024
        lp += (f * bp) >> 14
        hp = s - lp - ((dm * bp) >> 14)
        bp += (f * hp) >> 14
        lp += (f * bp) >> 14
        hp = s - lp - ((dm * bp) >> 14)
        bp += (f * hp) >> 14
        if lp > 65535:
            lp = 65535
        elif lp < -65536:
            lp = -65536
        if bp > 65535:
            bp = 65535
        elif bp < -65536:
            bp = -65536
        # second SVF stage, fully damped -> 24 dB/oct without doubling
        # the resonant peak
        lq += (f * bq) >> 14
        hp = lp - lq - bq
        bq += (f * hp) >> 14
        lq += (f * bq) >> 14
        hp = lp - lq - bq
        bq += (f * hp) >> 14
        if lq > 65535:
            lq = 65535
        elif lq < -65536:
            lq = -65536
        if bq > 65535:
            bq = 65535
        elif bq < -65536:
            bq = -65536
        o = (lq * (((g >> 8) * mg) >> 12)) >> 12   # amp env post-filter
        # cubic soft clip: y = 1.5u - u^3/2 (normalised), ceiling at 32768
        if o > 32768:
            o = 32768
        elif o < -32768:
            o = -32768
        a = o >> 3
        o = ((3 * o) >> 1) - ((((a * a) >> 9) * a) >> 13)
        v = int(out[ob + i])
        if v >= 32768:
            v -= 65536
        v += o
        if v > 32767:
            v = 32767
        elif v < -32768:
            v = -32768
        out[ob + i] = v & 0xFFFF
        g += dg
        i += 1
    st[0] = p0
    st[2] = p1
    st[4] = p2
    st[6] = p3
    st[8] = lp + 65536
    st[9] = bp + 65536
    st[10] = lq + 65536
    st[11] = bq + 65536


@micropython.viper
def _blk_lp1(buf: ptr16, n: int, st: ptr32, k: int):
    # in-place one-pole low-pass, k Q15; damps the S3 echo repeats
    y = int(st[0]) - 65536          # biased state, see _blk_saw
    i = 0
    while i < n:
        v = int(buf[i])
        if v >= 32768:
            v -= 65536
        y += ((v - y) * k) >> 15
        buf[i] = y & 0xFFFF
        i += 1
    st[0] = y + 65536


@micropython.viper
def _blk_mix(out: ptr16, ob: int, src: ptr16, sb: int, n: int, g: int):
    # add src into out with Q8 gain, saturating
    i = 0
    while i < n:
        v = int(out[ob + i])
        if v >= 32768:
            v -= 65536
        s = int(src[sb + i])
        if s >= 32768:
            s -= 65536
        v += (s * g) >> 8
        if v > 32767:
            v = 32767
        elif v < -32768:
            v = -32768
        out[ob + i] = v & 0xFFFF
        i += 1



if not _VIPER:
    # In plain Python the ptr annotations are inert, so cast the sample
    # buffers to uint16 views at the call boundary instead.
    _saw_k, _pulse_k, _mix_k = _blk_saw, _blk_pulse3, _blk_mix

    def _blk_saw(out, ob, n, st, cf):
        return _saw_k(ptr16(out), ob, n, st, cf)

    def _blk_pulse3(out, ob, n, st, cf):
        return _pulse_k(ptr16(out), ob, n, st, cf)

    def _blk_mix(out, ob, src, sb, n, g):
        return _mix_k(ptr16(out), ob, ptr16(src), sb, n, g)

    _lp1_k = _blk_lp1

    def _blk_lp1(buf, n, st, k):
        return _lp1_k(ptr16(buf), n, st, k)


# ---------------------------------------------------------------------------
# control-rate glue
# ---------------------------------------------------------------------------

FC_MAX = 7000.0     # SVF (2x oversampled) stability ceiling


def _svf_coefs(fc, rq):
    """Resonant low-pass as a Chamberlin SVF, run at 2xSR inside the kernels.
    damp == rq (rq is 1/Q, exactly SC's reciprocal-of-Q convention).
    Q14 fixed point keeps ~1% coefficient precision even at the 46 Hz
    tb303 cutoff floor, where a direct-form biquad in fixed point falls over.
    """
    if fc < 20.0:
        fc = 20.0
    elif fc > FC_MAX:
        fc = FC_MAX
    if rq < 0.06:
        rq = 0.06
    elif rq > 1.9:
        rq = 1.9
    f = 2.0 * math.sin(math.pi * fc / (2.0 * SR))
    return int(f * 16384), int(rq * 16384)


def _load_drums():
    """Load the real Sonic Pi drum samples (bd_fat/bd_boom/bd_haus.pcm,
    raw int16 mono 22050 Hz, shipped alongside this file), normalised to
    peak 26000 so step amp is a plain musical gain. Falls back to a
    synthesised kick if the files are missing."""
    try:
        base = __file__.rsplit('/', 1)[0]
    except (NameError, AttributeError):
        base = '.'
    drums = {}
    for name in ('fat', 'boom', 'haus'):
        try:
            raw = open(base + '/bd_' + name + '.pcm', 'rb').read()
            buf = bytearray(raw)
            # normalise to peak 26000 (integer scan, init-time only)
            pk = 1
            for i in range(0, len(buf), 2):
                v = buf[i] | (buf[i + 1] << 8)
                if v >= 0x8000:
                    v -= 0x10000
                if v > pk:
                    pk = v
                elif -v > pk:
                    pk = -v
            num = 26000
            for i in range(0, len(buf), 2):
                v = buf[i] | (buf[i + 1] << 8)
                if v >= 0x8000:
                    v -= 0x10000
                v = v * num // pk
                buf[i] = v & 0xFF
                buf[i + 1] = (v >> 8) & 0xFF
            drums[name] = buf
        except OSError:
            drums[name] = _make_kick()
    return drums


class StepRenderer:
    """Renders one sequencer Step into an int16 mono LE buffer at 22050 Hz."""

    TB303_MG = 3000      # make-up gains, tuned so kick and lead balance
    PROPHET_MG = 6200
    KICK_G = 256         # Q8, unity: drums are pre-normalised at load

    def __init__(self):
        self.drums = _load_drums()
        self.k_buf = self.drums['fat']
        self.kick_pos = len(self.k_buf)     # exhausted
        self.kick_gain = 0.0
        self.saw_st = array('i', [0] * 4)
        self.pls_st = array('i', [0] * 12)
        self.cf = array('i', [0] * 10)      # packed per-block coefficients
        self.echo = None                    # S3 pseudo-reverb feedback buffer
        self.echo_lp = array('i', [65536])  # damping filter state (biased)
        self._elp = 65536

    def render(self, step):
        dur, voice, midi, release, cutoff, sp_res, kick_amp, slic = step[:8]
        drum = step[8] if len(step) > 8 else 'fat'
        ns = int(dur * SR + 0.5)
        buf = bytearray(2 * ns)             # zero-filled

        # --- synth voice ----------------------------------------------------
        if voice is not None and release > 0.0:
            self._render_voice(buf, ns, voice, midi, release,
                               cutoff, sp_res, slic)

        # --- S3 pseudo-reverb: with_fx :reverb approximated as a one-step
        # (125 ms) damped feedback echo, prophet voice only (kick is mixed
        # afterwards and stays dry, so it can't flam through the echo) -----
        if voice == 'prophet':
            if self.echo is not None and len(self.echo) == len(buf):
                _blk_mix(buf, 0, self.echo, 0, ns, 80)      # ~0.31 feedback
            e = bytearray(buf)
            self.echo_lp[0] = self._elp
            _blk_lp1(e, ns, self.echo_lp, 13100)            # ~1.8 kHz damping
            self._elp = self.echo_lp[0]
            self.echo = e
        else:
            self.echo = None
            self._elp = 65536

        # --- drum (non-blocking in Sonic Pi: tail carries across steps) ----
        if kick_amp > 0.0:
            self.k_buf = self.drums.get(drum, self.drums['fat'])
            self.kick_pos = 0
            self.kick_gain = kick_amp
        if self.kick_pos < len(self.k_buf) // 2:
            n = min(ns, len(self.k_buf) // 2 - self.kick_pos)
            _blk_mix(buf, 0, self.k_buf, self.kick_pos, n,
                     int(self.KICK_G * self.kick_gain))
            self.kick_pos += n
        return buf

    def _render_voice(self, buf, ns, voice, midi, release, cutoff, sp_res, slic):
        freq = midicps(midi)
        cut_hz = midicps(cutoff)
        if voice != 'tb303':
            # SP's shipped prophet binary is undocumented; empirically its
            # spectrum sits much darker than midicps(cutoff) would suggest.
            # Scale tuned against the model-village reference recording.
            cut_hz *= 0.15
        rq = 1.0 - sp_res
        nrel = min(ns, int(release * SR) + 1)

        if voice == 'tb303':
            st = self.saw_st
            st[0] = 0
            st[1] = int(freq * _PH1)
            st[2] = 65536      # filter states biased, see _blk_saw
            st[3] = 65536
            kernel = _blk_saw
            mg = self.TB303_MG
        else:  # prophet: 3 detuned PWM pulses (approximation of SP's 5)
            st = self.pls_st
            st[0] = st[2] = st[4] = 0
            st[1] = int(freq * 0.9965 * _PH1)
            st[3] = int(freq * _PH1)
            st[5] = int(freq * 1.0035 * _PH1)
            st[6] = 0
            st[7] = int(freq * 0.5 * _PH1)     # sub-octave pulse
            st[8] = 65536      # biased
            st[9] = 65536
            st[10] = 65536
            st[11] = 65536
            kernel = _blk_pulse3
            mg = self.PROPHET_MG

        env_scale = (ENV_N - 1) / nrel
        pos = 0
        e_prev = ENV_TAB[0]
        while pos < nrel:
            n = min(BLOCK, nrel - pos)
            e_next = ENV_TAB[min(ENV_N - 1, int((pos + n) * env_scale))]

            # slicer (section 4): amplitude LFO, mix 0.75, wave sine
            if slic:
                t = pos / SR
                lfo = 0.5 + 0.5 * math.sin(2.0 * math.pi * t / slic)
                sg = 0.25 + 0.75 * lfo
            else:
                sg = 1.0

            # filter env == amp env (same ADSR in the tb303 synthdef)
            fc = CUTOFF_MIN_HZ + (e_prev / 16384.0) * cut_hz
            f, damp = _svf_coefs(fc, rq)

            cf = self.cf
            cf[0] = f
            cf[1] = damp
            cf[2] = int((e_prev >> 2) * sg)     # Q14 env -> Q12 gain
            cf[3] = int((e_next >> 2) * sg)
            cf[4] = mg
            if voice != 'tb303':
                t = pos / SR
                for k in range(3):
                    cf[5 + k] = int((0.5 + 0.35 * math.sin(
                        2.0 * math.pi * (0.4 * t + k / 3.0))) * (1 << 30))
                cf[8] = 1 << 29                    # sub: fixed 50% width
            kernel(buf, pos, n, st, cf)

            e_prev = e_next
            pos += n
