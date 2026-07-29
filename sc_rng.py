# Sorry for the biblically accurate rng stuff, this is a direct port of SC's rng code (to the best of my ability).
# I do not understand how it works, good luck and godspeed.


def _sc_hash(x):
    """Jenkins hash matching SC's Hash() function."""
    x = int(x) & 0xFFFFFFFF
    x = (x + (~(x << 15))) & 0xFFFFFFFF
    x ^= (x >> 10)
    x = (x + (x << 3)) & 0xFFFFFFFF
    x ^= (x >> 6)
    x = (x + (~(x << 11))) & 0xFFFFFFFF
    x ^= (x >> 16)
    return x & 0xFFFFFFFF


class SCRng:
    def __init__(self, seed):
        seed = int(seed) & 0xFFFFFFFF
        self.s1 = max(2, _sc_hash(seed))
        self.s2 = max(8, _sc_hash(_sc_hash(seed)))
        self.s3 = max(16, _sc_hash(_sc_hash(_sc_hash(seed))))

    def _trand(self):
        self.s1 = (((self.s1 & 0xFFFFFFFE) << 12) ^ (((self.s1 << 13) ^ self.s1) >> 19)) & 0xFFFFFFFF
        self.s2 = (((self.s2 & 0xFFFFFFF8) << 4) ^ (((self.s2 << 2) ^ self.s2) >> 25)) & 0xFFFFFFFF
        self.s3 = (((self.s3 & 0xFFFFFFF0) << 17) ^ (((self.s3 << 3) ^ self.s3) >> 11)) & 0xFFFFFFFF
        return (self.s1 ^ self.s2 ^ self.s3) & 0xFFFFFFFF

    def frand(self):
        return self._trand() * 2.3283064365e-10

    def irand(self, lo, hi):
        return int(self.frand() * (hi - lo + 1)) + lo

    def rand(self, lo, hi):
        return self.frand() * (hi - lo) + lo

    def choose(self, lst):
        return lst[int(self.frand() * len(lst))]
