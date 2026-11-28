"""Entry point for font builds. Runs in a Python that has fontTools (see toolchain.py),
so nothing here imports fontlab.

  run.py < jobs     one JSON object per line:
                    {"out": path, "src": path, "variable": path or null, "method": "instance"
                     or "graft", "axes": {tag: value}, "wght": number, "darken": [xem, yem] or null,
                     "instance_out": path or null}

With "variable", src is rebuilt at wght first (weights.at_weight). With "instance_out",
that face is also saved there before darkening (fontlab caches it, so the next darkening
at the same weight starts from it). With "darken", the result is emboldened
(darken.darken). Jobs run in parallel.
"""

import json
import sys
from concurrent.futures import ProcessPoolExecutor

from fontTools.ttLib import TTFont

import darken
import weights


def build(job):
    if job.get("variable"):
        f = weights.at_weight(job["src"], job["variable"], job["method"], job.get("axes", {}), job["wght"])
        if job.get("instance_out"):
            f.save(job["instance_out"])
    else:
        f = TTFont(job["src"])
    if job.get("darken"):
        darken.darken(f, *job["darken"])
    f.save(job["out"])


def main(argv):
    if argv:
        sys.exit(__doc__)
    jobs = [json.loads(line) for line in sys.stdin if line.strip()]
    with ProcessPoolExecutor() as pool:
        list(pool.map(build, jobs))


if __name__ == "__main__":
    main(sys.argv[1:])
