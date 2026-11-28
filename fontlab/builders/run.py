"""Entry point for font builds. Runs in a Python that has fontTools (see toolchain.py),
so nothing here imports fontlab. Commands:

  run.py darken                       jobs on stdin, one per line: SRC<TAB>DST<TAB>XEM<TAB>YEM
  run.py inter RELEASE_DIR OUT W...
  run.py adwaita SYSTEM_DIR OUT W...
  run.py roboto REGULAR_VF ITALIC_VF OUT W...
  run.py static-family REGULAR_VF ITALIC_VF FAMILY PS_PREFIX OUT W...
  run.py jetbrains-mono BASE_REGULAR BASE_ITALIC VARIABLE_DIR OUT W...
  run.py sf-pro-text VARIABLE_DIR STATIC_DIR OUT W...
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
    nfixed = {"inter": 2, "adwaita": 2, "roboto": 3, "static-family": 5,
              "jetbrains-mono": 4, "sf-pro-text": 3}[cmd]
    fixed, ws = args[:nfixed], [int(w) for w in args[nfixed:]]
    builder = {"inter": weights.inter, "adwaita": weights.adwaita,
               "roboto": weights.roboto, "static-family": weights.static_family,
               "jetbrains-mono": weights.jetbrains_mono, "sf-pro-text": weights.sf_pro_text}[cmd]
    builder(*fixed, ws)


if __name__ == "__main__":
    main(sys.argv[1:])
