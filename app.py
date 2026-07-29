import asyncio
import math

if not hasattr(asyncio, 'sleep_ms'):     # CPython badge simulator
    asyncio.sleep_ms = lambda ms: asyncio.sleep(ms / 1000)

import app
from app_components import clear_background, Menu
from events.input import Buttons, BUTTON_TYPES
from system.hexpansion.config import HexpansionConfig

from .sequencer import Sequencer
from .synth import StepRenderer, SR
from .gps_source import MockGps, NmeaGps
from .spectrum import Phrase

# badge only bits, sim doesnt have these
try:
    import imu
except ImportError:
    imu = None
try:
    from tildagonos import tildagonos
except ImportError:
    tildagonos = None
try:
    from system.eventbus import eventbus
    from system.patterndisplay.events import PatternDisable, PatternEnable
except ImportError:
    eventbus = None

# speccy palette
CYAN = [0, 1, 1]
MAGENTA = [1, 0, 1]
YELLOW = [1, 1, 0]
WHITE = [1, 1, 1]

DAC_BCK_PIN = 0    # HS1 -> BCK
DAC_LRCK_PIN = 1   # HS2 -> LCK / LRCK / WS
DAC_DIN_PIN = 2    # HS3 -> DIN
I2S_ID = 1
I2S_IBUF = 16384   # ~370 ms of headroom at 22050 Hz mono

STATE_DAC_MENU = 0
STATE_GPS_MENU = 1
STATE_RUNNING = 2

_PORTS = ["1", "2", "3", "4", "5", "6"]
_GPS_ITEMS = ["Test coords (no GPS)"] + ["GPS on port " + p for p in _PORTS]


class WorldOTechno(app.App):
    def __init__(self):
        super().__init__()
        self.button_states = Buttons(self)
        self.state = STATE_DAC_MENU
        self.menu = Menu(
            self,
            ["DAC on port " + p for p in _PORTS],
            select_handler=self._dac_selected,
            back_handler=self.minimise,
        )
        self.dac_port = None
        self.gps = None
        self.seq = None
        self.renderer = None
        self.i2s = None
        self._tasks = []
        self.running = False
        self.sim_mode = False
        self._pg_channel = None
        self.error = None
        self._theta = 0.0          # ring rotation from badge tilt
        self.level = 0.0           # audio level for the leds

    # ---------------- menus ----------------

    def _dac_selected(self, item, idx):
        self.dac_port = idx + 1
        self.menu = Menu(
            self,
            _GPS_ITEMS,
            select_handler=self._gps_selected,
            back_handler=self.minimise,
        )
        self.state = STATE_GPS_MENU

    def _gps_selected(self, item, idx):
        try:
            if idx == 0:
                self.gps = MockGps()
            else:
                self.gps = NmeaGps(HexpansionConfig(idx))
            self._start_audio()
            self.state = STATE_RUNNING
        except Exception as e:
            self.error = repr(e)
        self.menu = None

    # ---------------- audio ----------------

    def _start_audio(self):
        try:
            from machine import I2S
        except ImportError:
            I2S = None
        self._pg_channel = None
        if I2S is None or not hasattr(I2S, 'TX'):
            # sim has no I2S but it is pygame, so play thru pygame.mixer
            self.sim_mode = True
            self.i2s = None
            try:
                import pygame
                if pygame.mixer.get_init() != (SR, -16, 1):
                    pygame.mixer.quit()
                    pygame.mixer.init(frequency=SR, size=-16, channels=1,
                                      buffer=1024)
                self._pygame = pygame
                self._pg_channel = pygame.mixer.Channel(0)
            except Exception:
                self._pg_channel = None
        else:
            self.sim_mode = False
            cfg = HexpansionConfig(self.dac_port)
            self.i2s = I2S(
                I2S_ID,
                sck=cfg.pin[DAC_BCK_PIN],
                ws=cfg.pin[DAC_LRCK_PIN],
                sd=cfg.pin[DAC_DIN_PIN],
                mode=I2S.TX,
                bits=16,
                format=I2S.MONO,
                rate=SR,
                ibuf=I2S_IBUF,
            )
        self.renderer = StepRenderer()
        self.seq = Sequencer(self.gps)
        self.running = True
        if eventbus:
            eventbus.emit(PatternDisable())   # our leds now
        self._tasks.append(asyncio.create_task(self._audio_task()))
        if isinstance(self.gps, NmeaGps):
            self._tasks.append(asyncio.create_task(self._gps_task()))

    async def _play_sim(self, buf):
        """sim playback, queue one step ahead for gapless audio"""
        ch = self._pg_channel
        snd = self._pygame.mixer.Sound(buffer=bytes(buf))
        if not ch.get_busy():
            ch.play(snd)
            return
        while ch.get_queue() is not None:
            await asyncio.sleep_ms(5)
        ch.queue(snd)

    async def _audio_task(self):
        swriter = None if self.sim_mode else asyncio.StreamWriter(self.i2s, {})
        try:
            while self.running:
                if self.gps.has_fix():
                    steps = self.seq.cycle()
                else:
                    steps = self.seq.satellite_pattern()
                for step in steps:
                    if not self.running:
                        return
                    buf = None
                    if swriter is not None or self._pg_channel is not None:
                        buf = self.renderer.render(step)
                        p = 0
                        for i in range(0, len(buf) - 1, 512):
                            v = buf[i] | (buf[i + 1] << 8)
                            if v >= 32768:
                                v -= 65536
                            if v > p:
                                p = v
                            elif -v > p:
                                p = -v
                        if p / 32768 > self.level:
                            self.level = p / 32768
                    if swriter is not None:
                        swriter.write(buf)
                        await swriter.drain()
                    elif self._pg_channel is not None:
                        await self._play_sim(buf)
                    else:
                        await asyncio.sleep_ms(int(step[0] * 1000))
                await asyncio.sleep_ms(0)
        except Exception as e:
            self.error = repr(e)
            self.running = False

    async def _gps_task(self):
        while self.running:
            try:
                self.gps.poll()
            except Exception:
                pass
            await asyncio.sleep_ms(200)

    def _stop(self):
        self.running = False
        for t in self._tasks:
            try:
                t.cancel()
            except Exception:
                pass
        self._tasks = []
        if self.i2s:
            try:
                self.i2s.deinit()
            except Exception:
                pass
            self.i2s = None
        if self._pg_channel:
            try:
                self._pg_channel.stop()
            except Exception:
                pass
            self._pg_channel = None
        if tildagonos:
            try:
                for i in range(1, 13):
                    tildagonos.leds[i] = (0, 0, 0)
                tildagonos.leds.write()
            except Exception:
                pass
        if eventbus:
            eventbus.emit(PatternEnable())    # give the rainbow back

    # ---------------- framework ----------------

    def update(self, delta):
        if self.state == STATE_RUNNING or self.error:
            if self.button_states.get(BUTTON_TYPES["CANCEL"]):
                self.button_states.clear()
                self._stop()
                self.minimise()
        elif self.menu:
            self.menu.update(delta)
        if self.state != STATE_RUNNING:
            return
        # ring follows badge tilt, beeline style. gravity vector gives us
        # the down direction when the badges held up
        if imu:
            try:
                ax, ay, az = imu.acc_read()
                if ax * ax + ay * ay > 2.0:   # dead zone when flat on a table
                    tgt = math.atan2(ax, ay)
                    d = (tgt - self._theta + math.pi) % (2 * math.pi) - math.pi
                    self._theta += 0.15 * d
            except Exception:
                pass
        # leds pulse with the music, alternting speccy colours
        if tildagonos and self.running:
            try:
                b = self.level
                for i in range(1, 13):
                    c = MAGENTA if i % 2 else CYAN
                    tildagonos.leds[i] = (int(c[0] * 255 * b),
                                          int(c[1] * 255 * b),
                                          int(c[2] * 255 * b))
                tildagonos.leds.write()
            except Exception:
                pass
        self.level *= 0.82

    def _write_phrase(self, ctx, params, bold=False):
        # pikesleys Phrase wants an app with .overlays, give it a decoy.
        # bold draws everything 4x with a small offset to fatten the strokes
        class _O:
            pass
        o = _O()
        o.overlays = []
        Phrase(params).write(o)
        d = params.get("scale", 1) * 0.6
        offs = ((0, 0), (d, 0), (0, d), (d, d)) if bold else ((0, 0),)
        for c in o.overlays:
            for ox, oy in offs:
                ctx.save()
                ctx.translate(ox, oy)
                c.draw(ctx)
                ctx.restore()

    def draw(self, ctx):
        clear_background(ctx)
        if self.menu and self.state != STATE_RUNNING:
            self.menu.draw(ctx)
            return
        ctx.save()
        ctx.text_align = ctx.CENTER
        ctx.font_size = 18
        if self.error:
            ctx.rgb(1, 0.3, 0.3).move_to(0, -20).text("Error:")
            ctx.move_to(0, 0).text(self.error[:36])
            ctx.rgb(1, 1, 1).move_to(0, 40).text("CANCEL to exit")
        elif self.gps and self.gps.has_fix():
            # coords round the edge in a small plain font, rotates with the
            # badge. one char at a time, each rotated to face the middle
            txt = "%.5f  %.5f" % (self.gps.lat(), self.gps.lon())
            total = math.radians(300)
            ctx.save()
            ctx.rotate(self._theta)
            ctx.font_size = 10
            ctx.rgb(*CYAN)
            n = len(txt)
            for i, ch in enumerate(txt):
                a = -total / 2 + total * i / (n - 1)
                ctx.save()
                ctx.rotate(a)
                ctx.move_to(0, -112)   # right at the rim, clear of the title
                ctx.text(ch)
                ctx.restore()
            ctx.restore()
            # big chunky pikesley style title
            self._write_phrase(ctx, {"text": "world", "scale": 3.5,
                                     "y-offset": -48, "colour": MAGENTA}, bold=True)
            self._write_phrase(ctx, {"text": "o", "scale": 3.5,
                                     "y-offset": 0, "colour": YELLOW}, bold=True)
            self._write_phrase(ctx, {"text": "techno", "scale": 3.5,
                                     "y-offset": 48, "colour": CYAN}, bold=True)
        else:
            ctx.rgb(1, 0.8, 0).move_to(0, -20).text("waiting for fix...")
            sats = self.gps.satellites() if self.gps else 0
            ctx.rgb(1, 1, 1).move_to(0, 8).text("satellites: %d" % sats)
        ctx.restore()

    def deinit(self):
        self._stop()


__app_export__ = WorldOTechno