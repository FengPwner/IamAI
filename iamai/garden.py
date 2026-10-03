"""A deterministic ASCII garden.

Same seed + same round == same garden. That is the whole point: the garden is not
random decoration, it is a *function of time*. Every round of the writer advances
it by one tick, so the committed frames are a replayable record of how long this
thing has been running.

No third-party deps, no RNG you have to seed by hand, no floating point drift --
a small integer LCG keeps a frame reproducible on any machine.
"""

from __future__ import annotations

from dataclasses import dataclass

PLANTS = {
    0: ".",  # bare soil
    1: ",",  # sprout
    2: "'",  # shoot
    3: "Y",  # leafing
    4: "&",  # bushy
    5: "8",  # in flower
    6: "*",  # seeding
    7: "@",  # gone to seed, still pretty
}
MAX_STAGE = max(PLANTS)


class LCG:
    """Old and dumb and exactly reproducible: x = (a*x + c) mod m."""

    a, c, m = 1103515245, 12345, 1 << 31

    def __init__(self, seed: int):
        self.state = int(seed) & (self.m - 1)

    def next(self) -> int:
        self.state = (self.a * self.state + self.c) % self.m
        return self.state

    def below(self, n: int) -> int:
        return self.next() % max(n, 1)


@dataclass(frozen=True)
class Plot:
    x: int
    y: int
    planted_at: int  # round it appeared, -1 = never planted
    growth: int  # ticks per stage

    def stage(self, round_no: int) -> int:
        if self.planted_at < 0 or round_no < self.planted_at:
            return 0
        return min(MAX_STAGE, (round_no - self.planted_at) // max(self.growth, 1))

    def glyph(self, round_no: int) -> str:
        return PLANTS[self.stage(round_no)]


class Garden:
    """A rectangular plot of plants, seeded once, advanced by whole rounds."""

    def __init__(self, seed: int = 20261003, width: int = 48, height: int = 10):
        if width < 1 or height < 1:
            raise ValueError("a garden needs at least one square metre")
        self.seed = int(seed)
        self.width = int(width)
        self.height = int(height)
        self.plots: list[Plot] = []
        self._sow()

    def _sow(self) -> None:
        rng = LCG(self.seed)
        total = self.width * self.height
        density = 25 + rng.below(20)  # percent of squares that ever get planted
        for index in range(total):
            x, y = index % self.width, index // self.width
            will_grow = rng.below(100) < density
            self.plots.append(
                Plot(
                    x=x,
                    y=y,
                    planted_at=rng.below(40) if will_grow else -1,
                    growth=1 + rng.below(4),
                )
            )

    def frame(self, round_no: int) -> str:
        rows = []
        for y in range(self.height):
            cells = [
                self.plots[y * self.width + x].glyph(round_no) for x in range(self.width)
            ]
            rows.append("".join(cells))
        return "\n".join(rows)

    def bloom(self, round_no: int) -> float:
        """Fraction of planted squares that have reached flowering stage."""

        planted = [p for p in self.plots if p.planted_at >= 0]
        if not planted:
            return 0.0
        blooming = sum(1 for p in planted if p.stage(round_no) >= 4)
        return round(blooming / len(planted), 3)

    def report(self, round_no: int) -> str:
        planted = sum(1 for p in self.plots if p.planted_at >= 0)
        return (
            f"round {round_no:>4}  "
            f"bloom {self.bloom(round_no) * 100:5.1f}%  "
            f"plants {planted:>4}/{self.width * self.height}"
        )


def render_frames(seed: int, first: int, last: int, **kw) -> str:
    """Stack the frames from `first` to `last` as a fenced block for a commit."""

    garden = Garden(seed=seed, **kw)
    out = []
    for round_no in range(first, last + 1):
        out.append(garden.report(round_no))
        out.append(garden.frame(round_no))
        out.append("")
    return "\n".join(out).rstrip() + "\n"
