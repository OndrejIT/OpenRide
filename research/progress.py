"""Progress files for long jobs; run as a script to print a status table."""

import time
from pathlib import Path

DIR = Path(__file__).parent / "data" / "progress"


class Progress:
    def __init__(self, name: str, total: float, done: float = 0.0):
        DIR.mkdir(parents=True, exist_ok=True)
        self.path, self.total, self.start, self.done0, self.last = DIR / f"{name}.txt", total, time.time(), done, 0.0
        self.update(done, force=True)

    def update(self, done: float, force: bool = False):
        now = time.time()
        if force or now - self.last > 5:
            self.path.write_text(f"{self.start} {self.done0} {done} {self.total}\n")
            self.last = now


if __name__ == "__main__":
    print(f"{'úloha':<10} {'hotovo':>14} {'%':>6} {'zbývá':>8}")
    for p in sorted(DIR.glob("*.txt")):
        start, done0, done, total = map(float, p.read_text().split())
        rate = (done - done0) / max(time.time() - start, 1e-9)
        eta = "hotovo" if done >= total else (f"{(total - done) / rate / 60:.0f} min" if rate > 0 else "?")
        print(f"{p.stem:<10} {done:>6.0f}/{total:<6.0f}s {100 * done / total:>5.1f} {eta:>8}")
