"""Reduce an exported archive to arrays, one row per snapshot file.

python scripts/compact_archive.py --archive DIR --backend ibm_fez --out DIR/ibm_fez.npz
"""

import argparse
from pathlib import Path

from noise_refresh.archive import compact_archive

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--archive", type=Path, required=True)
parser.add_argument("--backend", default="ibm_fez")
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
compact = compact_archive(args.archive, args.backend)
compact.save(args.out)
shape = f"{len(compact.stamps)} files, {compact.qubit.shape[1]} qubits, {len(compact.gate_keys)} gates"
print(f"{shape} -> {args.out}")
