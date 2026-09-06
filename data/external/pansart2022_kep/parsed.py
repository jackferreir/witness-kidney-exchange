"""Standalone sanity-check parser for the Pansart et al. 2022 kidney-
exchange benchmark instances (see SOURCE.txt for provenance/license).

This is pure data plumbing: it reads `Pansart2022.zip`'s member `.txt` files
directly (never extracted permanently to disk) and reports the declared
header values (P, N, K, L) against the ACTUAL shape of the medical-benefit
matrix that follows them, plus basic structural stats (density, diagonal
check). It does NOT touch anything under witness/ and does NOT build a
`KidneyMarket` -- that conversion, including the declared synthetic
hospital-ownership partition this format has no notion of at all, lives
separately in `witness/kidney_real_data.py` (see that module's docstring
for why the split matters, per data/external/README.md's own discipline).

FILE FORMAT (from ORIGINAL_DATA_README.md, this project's own translation
of the French comments -- verified against the actual file content, not
assumed): alternating comment-then-value lines for P (patient-donor pair
count), N (altruistic donor count), K (max cycle length), L (max chain
length), then an (N+P) x P matrix of medical-benefit integers, tab-
separated, one row per line. Row i (0-indexed) is: an altruistic donor's
row if i < N, else patient-donor pair (i - N)'s donor row. Column j is
always patient-donor pair j's recipient. Entry -1 means infeasible.

Usage:
    python3 parsed.py [path/to/Pansart2022.zip]
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from typing import Any

DEFAULT_ZIP = Path(__file__).parent / "Pansart2022.zip"

#: Every member of the zip that is one of the actual instance files (not the
#: nested `Instances_Pansart2022.zip`, not the bare directory entry).
_INSTANCE_PREFIX = "Pansart2022/KEP_"


def list_instances(zip_path: Path) -> "list[str]":
    with zipfile.ZipFile(zip_path) as zf:
        return sorted(
            n for n in zf.namelist() if n.startswith(_INSTANCE_PREFIX) and n.endswith(".txt")
        )


def parse_instance(zip_path: Path, member: str) -> "dict[str, Any]":
    """Parse one instance file's header + matrix, and report whether the
    ACTUAL matrix shape matches the DECLARED header values -- the single
    most important structural check this file can make, since a silently
    truncated or wrong download would show up here first."""
    with zipfile.ZipFile(zip_path) as zf:
        text = zf.read(member).decode("utf-8")
    lines = text.splitlines()

    values: "list[int]" = []
    matrix_start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        if stripped == "":
            continue
        if len(values) < 4:
            values.append(int(stripped))
            continue
        matrix_start = i
        break

    if len(values) != 4 or matrix_start is None:
        raise ValueError(f"{member}: could not locate all 4 header values before the matrix")
    p, n, k, l = values

    matrix_lines = [ln for ln in lines[matrix_start:] if ln.strip() != ""]
    matrix = [[int(x) for x in ln.strip().split("\t")] for ln in matrix_lines]

    n_rows_actual = len(matrix)
    n_cols_actual = {len(row) for row in matrix}
    shape_ok = (
        n_rows_actual == n + p
        and n_cols_actual == {p}
    )

    diagonal_all_infeasible = True
    if shape_ok:
        for i in range(p):
            if matrix[n + i][i] != -1:
                diagonal_all_infeasible = False
                break

    n_entries = n_rows_actual * (list(n_cols_actual)[0] if len(n_cols_actual) == 1 else 0)
    n_feasible = sum(1 for row in matrix for x in row if x != -1)

    return {
        "member": member,
        "declared_p": p,
        "declared_n": n,
        "declared_k": k,
        "declared_l": l,
        "actual_matrix_rows": n_rows_actual,
        "actual_matrix_cols": sorted(n_cols_actual),
        "shape_matches_header": shape_ok,
        "diagonal_all_infeasible": diagonal_all_infeasible,
        "n_matrix_entries": n_entries,
        "n_feasible_entries": n_feasible,
        "feasible_density": n_feasible / n_entries if n_entries else None,
        "matrix": matrix,
    }


def pp_pair_submatrix(parsed: "dict[str, Any]") -> "list[list[int]]":
    """Just the P x P patient-donor-pair-to-patient-donor-pair submatrix
    (drops the N altruistic-donor rows entirely) -- this project's model
    has no altruistic donors or chains at all (see `witness.kidney`'s module
    docstring), so this is the only part of the file our model can use."""
    n, p = parsed["declared_n"], parsed["declared_p"]
    return [row[:p] for row in parsed["matrix"][n : n + p]]


def main(argv: "list[str]") -> int:
    zip_path = Path(argv[1]) if len(argv) > 1 else DEFAULT_ZIP
    if not zip_path.exists():
        print(f"error: {zip_path} not found. See SOURCE.txt for the download URL.", file=sys.stderr)
        return 1

    instances = list_instances(zip_path)
    print(f"zip: {zip_path}")
    print(f"instance files found: {len(instances)}")

    # Summarize one representative (smallest N, replicate 0, L=3) instance
    # per distinct P value -- enough to sanity-check the format across the
    # full size range without parsing all 272 files on every invocation.
    seen_p: "set[int]" = set()
    for member in instances:
        # e.g. "Pansart2022/KEP_p50_n3_k3_l3_0.txt"
        name = member.rsplit("/", 1)[-1]
        parts = name[len("KEP_") : -len(".txt")].split("_")
        p_val = int(parts[0][1:])
        if p_val in seen_p:
            continue
        if not (parts[3] == "l3" and name.endswith("_0.txt")):
            continue
        seen_p.add(p_val)

        parsed = parse_instance(zip_path, member)
        print(f"\n{member}")
        print(
            f"  declared P={parsed['declared_p']} N={parsed['declared_n']} "
            f"K={parsed['declared_k']} L={parsed['declared_l']}"
        )
        print(
            f"  actual matrix shape: {parsed['actual_matrix_rows']} rows x "
            f"{parsed['actual_matrix_cols']} cols -- header match: {parsed['shape_matches_header']}"
        )
        print(f"  diagonal (pair i's own donor->own recipient) all infeasible: {parsed['diagonal_all_infeasible']}")
        print(f"  feasible entries: {parsed['n_feasible_entries']} / {parsed['n_matrix_entries']} "
              f"({parsed['feasible_density']:.4%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
