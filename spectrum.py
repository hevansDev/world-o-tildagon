# sinclair spectrum font + renderer by pikesley, lifted (with thanks!) from
# https://codeberg.org/pikesley/tildagon-badge-fest - the man is responsible
# for 12.8% of the app store, show some respect
from math import cos, radians, sin
from random import randint, random


def assign_angles(length, angle):
    """Assign spread of angles."""
    start_angle = angle * ((length - 1) / 2)

    return [start_angle - (i * angle) for i in range(length)]


def assign_internal_offsets(length, scale):
    """Assign internal offsets."""
    raw = [scale * i * 8 for i in range(length)]
    return [x - (scale * 8 * ((length - 1) / 2)) for x in raw]


class Phrase:
    """Write letters 'n' shit, yo."""

    def __init__(self, params):
        """Construct."""
        self.text = params.get("text")
        self.scale = params.get("scale")
        self.y_offset = params.get("y-offset", 0)
        self.x_offset = params.get("x-offset", 0)
        self.colour = params.get("colour")
        self.opacity = params.get("opacity", 1)
        self.twitch_amount = params.get("twitch-amount", 0)
        self.total_angle = params.get("total-angle", None)
        if self.total_angle and self.y_offset < 0:
            self.total_angle = 0 - self.total_angle

        self.internal_offsets = None
        self.angles = None

        if self.total_angle:
            self.angle = self.total_angle / max(1, len(self.text) - 1)
            self.angles = assign_angles(len(self.text), self.angle)

        else:
            self.internal_offsets = assign_internal_offsets(len(self.text), self.scale)

        self.x_position = 0

    def write(self, app):
        """Letters."""
        for index, letter in enumerate(self.text):
            params = {
                "char": letter,
                "scale": self.scale,
                "y-offset": self.y_offset,
                "colour": self.colour,
                "opacity": self.opacity,
                "twitch-amount": self.twitch_amount,
                "x-position": self.x_position,
            }

            if self.angles:
                params["angle"] = self.angles[index]
            if self.internal_offsets:
                params["x-offset"] = self.internal_offsets[index]

            app.overlays.append(Character(params))


class Character:
    """A character."""

    def __init__(self, params=None):
        """Construct."""
        params = params if params else {}
        self.char = params.get("char")
        self.scale = params.get("scale")
        self.angle = params.get("angle", 0)
        self.opacity = params.get("opacity", 1)
        self.colour = list(params.get("colour")) + [self.opacity]
        self.y_offset = params.get("y-offset")
        self.x_offset = params.get("x-offset", 0)
        self.x_position = params.get("x-position", 0)
        self.twitch_amount = params.get("twitch-amount", 0)
        self.data = font[self.char]

    def draw(self, ctx):
        """Draw."""
        ctx.rgba(*self.colour)
        ctx.translate(self.x_offset + self.x_position, 0)

        ctx.translate(
            sin(radians(self.angle)) * -self.y_offset,
            cos(radians(self.angle)) * self.y_offset,
        )
        ctx.rotate(radians(self.angle))

        start_x = (
            0
            - (8 * self.scale / 2)
            + (random() < self.twitch_amount and (randint(0, 1) * 2) - 1)
        )
        start_y = (
            0
            - (8 * self.scale / 2)
            + (random() < self.twitch_amount and (randint(0, 1) * 2) - 1)
        )
        for item in self.data:
            left = item[0] * self.scale
            width = item[2] * self.scale
            top = item[1] * self.scale
            height = self.scale

            ctx.rectangle(
                start_x + left,
                start_y + top,
                width,
                height,
            )

            ctx.fill()


compressed_font = (
    ("A", "121131146151161214621631651661"),
    ("B", "115121135141151165621641651"),
    ("C", "121131141151214264621651"),
    ("D", "114121131141151164521551631641"),
    ("E", "116121135141151166"),
    ("F", "116121135141151161"),
    ("G", "121131141151214264443621651"),
    ("H", "111121136141151161611621641651661"),
    ("I", "215265421431441451"),
    ("J", "141151264611621631641651"),
    ("K", "111121133141151161421441511551661"),
    ("L", "111121131141151166"),
    ("M", "111122131141151161332522611631641651661"),
    ("N", "111122131141151161331441552611621631641661"),
    ("O", "121131141151214264621631641651"),
    ("P", "115121131145151161621631"),
    ("Q", "121131141151214264341451621631641651"),
    ("R", "115121131145151161551621631661"),
    ("S", "121151214234264641651"),
    ("T", "017321331341351361"),
    ("U", "111121131141151264611621631641651"),
    ("V", "111121131141251362551611621631641"),
    ("W", "111121131141151261352561611621631641651"),
    ("X", "111161221251332342521551611661"),
    ("Y", "011121231341351361431521611"),
    ("Z", "116166251341431521"),
    ("a", "151223244264531551"),
    ("b", "211221234241251264641651"),
    ("c", "231241251323363"),
    ("d", "141151234264511521541551"),
    ("e", "131144151223264531"),
    ("f", "321332341351361412"),
    ("g", "131141224254273531541561"),
    ("h", "111121134141151161541551561"),
    ("i", "232263311341351"),
    ("j", "261372511531541551561"),
    ("k", "211221232242251261421451561"),
    ("l", "311321331341351462"),
    ("m", "122131141151161331341351361421531541551561"),
    ("n", "124131141151161531541551561"),
    ("o", "131141151223263531541551"),
    ("p", "124131141154161171531541"),
    ("q", "131141224254531541561572"),
    ("r", "231241251261323"),
    ("s", "131164223243551"),
    ("t", "223311331341351462"),
    ("u", "121131141151263521531541551"),
    ("v", "121131241251361441451521531"),
    ("w", "121131141151261331341351461521531541551"),
    ("x", "121161231251341431451521561"),
    ("y", "121131141254273521531541561"),
    ("z", "125165251341431"),
    ("0", "121131141152214264341431522631641651"),
    ("1", "221265312421431441451"),
    ("2", "121151166214244621631"),
    ("3", "121151214264432621641651"),
    ("4", "141156231322411431441461"),
    ("5", "116121135151264641651"),
    ("6", "121135141151214264641651"),
    ("7", "116351361441531621"),
    ("8", "121141151214234264621641651"),
    ("9", "121131214245264621631651"),
    (" ", ""),
    ("!", "311321331341361"),
    ('"', "211221511521"),
    ("#", "126156211231241261511531541561"),
    ("$", "225231245265411431451471651"),
    ("%", "112122161251341431521552562611"),
    ("&", "151221241263311331421441551641661"),
    ("'", "321411"),
    ("(", "421431441451511561"),
    (")", "211261321331341351"),
    ("*", "245321361431451521561"),
    ("+", "245421431451461"),
    (",", "371451461"),
    ("-", "245"),
    (".", "352362"),
    ("/", "261351441531621"),
    (":", "331361"),
    (";", "271321351361"),
    ("<", "341431451521561"),
    ("=", "235255"),
    (">", "321361431451541"),
    ("?", "121214441461531621"),
    ("@", "121131141151214264331344421532621"),
    ("[", "413421431441451463"),
    ("\\", "121231341451561"),
    ("]", "113163321331341351"),
    ("^", "131223311331341351361531"),
    ("_", "078"),
    ("{", "232413421441451463"),
    ("|", "411421431441451461"),
    ("}", "113163321341351432"),
    ("~", "221311421511"),
    ("£", "134166221241251313621"),
    ("©", "021031041051111161204231241274322352611661721731741751"),
)

font = {}
for key, data in compressed_font:
    try:
        font[key] = [[int(i) for i in data[x : x + 3]] for x in range(0, len(data), 3)]
    except ValueError:
        font[key] = []
