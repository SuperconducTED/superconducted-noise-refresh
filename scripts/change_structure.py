r"""How calibration changes arrive: per family, how often and how much of the family at once.

python scripts/change_structure.py --archive DIR --compact DIR/ibm_fez.npz \
    --out results/x/change_structure.json
"""

import argparse
from dataclasses import asdict
from pathlib import Path

import numpy as np
from _common import provenance, write

from noise_refresh.archive import Compact
from noise_refresh.changes import family_views, quiet_round_share, summarize_family

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--archive", type=Path, default=None, help="only read for its REF file")
parser.add_argument("--compact", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()

compact = Compact.load(args.compact)
hours = compact.hours
quiet = quiet_round_share(compact)
print(
    f"{len(compact.stamps)} files over {(hours[-1] - hours[0]) / 24:.1f} days, "
    f"median gap {np.median(np.diff(hours)):.2f} h"
)
print(f"rounds in which nothing changed: {quiet:.3f}\n")
print(
    f"{'family':12s} {'changed rounds':>16s} {'median share':>13s} {'>95%':>6s} {'<5%':>5s}   "
    "share of components moving more than 1% / 5% / 10% / 25% / 50%"
)
summaries = []
for family, view in family_views(compact).items():
    s = summarize_family(family, view)
    summaries.append(asdict(s))
    exceed = " / ".join(f"{v:.3f}" for v in s.exceed_share.values())
    print(
        f"{family:12s} {s.rounds_changed:>7d} of {s.rounds:<5d} {s.median_fraction_when_changed:>13.3f} "
        f"{s.rounds_changed_above_95pct:>6d} {s.rounds_changed_below_5pct:>5d}   {exceed}"
    )
for s in summaries:
    s["exceed_share"] = {str(k): v for k, v in s["exceed_share"].items()}
write(
    args.out,
    {
        "provenance": provenance(args.archive),
        "files": len(compact.stamps),
        "first": compact.stamps[0],
        "last": compact.stamps[-1],
        "quiet_round_share": quiet,
        "families": summaries,
    },
)
