# world-o-techno for the Tildagon badge.
# GPS-driven acid techno, faithfully ported from jarkman's Sonic Pi original.
#
# Hardware: PCM5102A I2S DAC hexpansion (BCK/LRCK/DIN on HS1/HS2/HS3, SCK
# strapped to GND) + optional GPS hexpansion (NMEA over UART on HS pins).
#
# Runs entirely inside the stock Tildagon MicroPython firmware - no custom
# firmware build, no C modules. Audio-rate DSP is @micropython.viper.

import asyncio

if not hasattr(asyncio, 'sleep_ms'):     # CPython badge simulator
    asyncio.sleep_ms = lambda ms: asyncio.sleep(ms / 1000)

import app
from app_components import clear_background, Menu
from events.input import Buttons, BUTTON_TYPES
from system.hexpansion.config import HexpansionConfig

from .sequencer import Sequencer
from .synth import StepRenderer, SR
from .gps_source import MockGps, NmeaGps

# PCM5102A wiring on the DAC hexpansion (HexpansionConfig.pin index):
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
            # Badge simulator: no I2S peripheral. The sim is a pygame app,
            # so play through pygame.mixer if we can; otherwise run silently
            # in real time so the sequencer/UI still work.
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
        self._tasks.append(asyncio.create_task(self._audio_task()))
        if isinstance(self.gps, NmeaGps):
            self._tasks.append(asyncio.create_task(self._gps_task()))

    async def _play_sim(self, buf):
        """Simulator playback: queue one step ahead on a pygame channel."""
        ch = self._pg_channel
        snd = self._pygame.mixer.Sound(buffer=bytes(buf))
        if not ch.get_busy():
            ch.play(snd)
            return
        # wait for the queue slot, then queue for gapless playback
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
                    if swriter is not None:
                        buf = self.renderer.render(step)
                        swriter.write(buf)
                        await swriter.drain()
                    elif self._pg_channel is not None:
                        await self._play_sim(self.renderer.render(step))
                    else:
                        # no audio device at all: keep musical time silently
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

    # ---------------- framework ----------------

    def update(self, delta):
        if self.state == STATE_RUNNING or self.error:
            if self.button_states.get(BUTTON_TYPES["CANCEL"]):
                self.button_states.clear()
                self._stop()
                self.minimise()
        elif self.menu:
            self.menu.update(delta)

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
            ctx.rgb(0, 1, 0.6).font_size = 22
            ctx.move_to(0, -60).text("world-o-techno")
            ctx.font_size = 18
            ctx.rgb(1, 1, 1)
            ctx.move_to(0, -30).text("section %d" % (self.seq.section if self.seq else 0))
            ctx.move_to(0, -8).text("root MIDI %d" % (self.seq.chord_root if self.seq else 0))
            ctx.move_to(0, 18).text("%.5f" % self.gps.lat())
            ctx.move_to(0, 40).text("%.5f" % self.gps.lon())
            if self.sim_mode:
                msg = ("sim audio: pygame" if self._pg_channel
                       else "sim: no audio device")
                ctx.rgb(1, 0.8, 0).move_to(0, 62).text(msg)
        else:
            ctx.rgb(1, 0.8, 0).move_to(0, -20).text("waiting for fix...")
            sats = self.gps.satellites() if self.gps else 0
            ctx.rgb(1, 1, 1).move_to(0, 8).text("satellites: %d" % sats)
        ctx.restore()

    def deinit(self):
        self._stop()


__app_export__ = WorldOTechno
