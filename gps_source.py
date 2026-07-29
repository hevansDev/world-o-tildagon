# gps sources. NmeaGps is a minimal GGA/RMC parser over UART, if you have
# working gps code already just wrap it in the same interface.
#
# next_cycle_ticks() is for syncing badges over gps time: timestamps timed
# NMEA sentances and keeps the MIN (ticks - utc) offset - delays only ever
# add so the minimum is closest to the truth. identical hexpansions share
# the modules fixed sentence lag so it cancels between badges

TEST_LAT = 52.0417343     # Model village at EMF camp 2026
TEST_LON = -2.3758267

GPS_RX_PIN_IDX = 0
GPS_TX_PIN_IDX = 1
GPS_BAUD = 9600


class MockGps:
    def __init__(self, lat=TEST_LAT, lon=TEST_LON):
        self._lat = lat
        self._lon = lon

    def has_fix(self):
        return True

    def lat(self):
        return self._lat

    def lon(self):
        return self._lon

    def speed(self):
        return 0.0

    def satellites(self):
        return 9


class NmeaGps:
    def __init__(self, hexpansion_config, uart_id=1):
        from machine import UART
        self.uart = UART(
            uart_id,
            baudrate=GPS_BAUD,
            tx=hexpansion_config.pin[GPS_TX_PIN_IDX],
            rx=hexpansion_config.pin[GPS_RX_PIN_IDX],
        )
        self._lat = 0.0
        self._lon = 0.0
        self._speed = 0.0
        self._sats = 0
        self._fix = False
        self._buf = b""


    def poll(self):
        """Call regularly (e.g. from an asyncio task)."""
        data = self.uart.read()
        if not data:
            return
        self._buf += data
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            self._parse(line.strip())
        if len(self._buf) > 512:            # runaway garbage guard
            self._buf = b""

    def _parse(self, line):
        try:
            line = line.decode()
        except Exception:
            return
        if not line.startswith("$"):
            return
        parts = line.split("*")[0].split(",")
        tag = parts[0][-3:]
        try:
            if tag == "GGA" and len(parts) >= 8:
                # $..GGA,time,lat,N,lon,E,fixq,sats,...
                fixq = int(parts[6] or 0)
                self._sats = int(parts[7] or 0)
                if fixq > 0 and parts[2] and parts[4]:
                    self._lat = self._dm2deg(parts[2], parts[3])
                    self._lon = self._dm2deg(parts[4], parts[5])
                    self._fix = True
                else:
                    self._fix = False
            elif tag == "RMC" and len(parts) >= 8:
                # $..RMC,time,status,lat,N,lon,E,speed_knots,...
                if parts[2] == "A" and parts[3] and parts[5]:
                    self._lat = self._dm2deg(parts[3], parts[4])
                    self._lon = self._dm2deg(parts[5], parts[6])
                    self._fix = True
                if parts[7]:
                    self._speed = float(parts[7]) * 0.514444
        except (ValueError, IndexError):
            pass

    @staticmethod
    def _dm2deg(dm, hemi):
        v = float(dm)
        deg = int(v / 100)
        deg += (v - deg * 100) / 60.0
        if hemi in ("S", "W"):
            deg = -deg
        return deg


    def has_fix(self):
        return self._fix

    def lat(self):
        return self._lat

    def lon(self):
        return self._lon

    def speed(self):
        return self._speed

    def satellites(self):
        return self._sats
