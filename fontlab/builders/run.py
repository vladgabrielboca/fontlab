"""Entry point for font builds. Runs in a Python that has fontTools (see toolchain.py),
so nothing here imports fontlab. Commands:

  run.py darken                       jobs on stdin, one per line: SRC<TAB>DST<TAB>XEM<TAB>YEM
  run.py inter RELEASE_DIR OUT W...
  run.py jetbrains-mono BASE_REGULAR BASE_ITALIC VARIABLE_DIR OUT W...
"""

import sys
from concurrent.futures import ProcessPoolExecutor

import darken
import weights


def main(argv):
    cmd, args = argv[0], argv[1:]
    if cmd == "darken":
        jobs = [line.rstrip("\n").split("\t") for line in sys.stdin if line.strip()]
        with ProcessPoolExecutor() as pool:
            for f in [pool.submit(darken.darken, s, d, float(x), float(y)) for s, d, x, y in jobs]:
                f.result()
        return
    nfixed = {"inter": 2, "jetbrains-mono": 4}[cmd]
    fixed, ws = args[:nfixed], [int(w) for w in args[nfixed:]]
    builder = {"inter": weights.inter, "jetbrains-mono": weights.jetbrains_mono}[cmd]
    builder(*fixed, ws)


if __name__ == "__main__":
    main(sys.argv[1:])
