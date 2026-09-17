"""Resumability check for `scripts/kidney_tiebreak_robustness.py`, per its own
mandatory contract (module docstring's RESUMABILITY section): the user's
machine may sleep or the process may be killed mid-run, so the script must
write each witness's full result to `per_witness.jsonl` immediately (flush +
fsync) after computing it, and skip already-present `witness_id`s on the next
run. This is a REAL demonstration -- actually SIGTERM the running process
partway through a batch and rerun the identical command -- not just a claim
that the code looks resumable.
"""

from __future__ import annotations

import json
import os
import random
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PROJECT_ROOT / "scripts" / "kidney_tiebreak_robustness.py"

sys.path.insert(0, str(PROJECT_ROOT))

from witness.kidney import KidneyConfig, KidneyMarket, KidneyProfile  # noqa: E402
from witness.search_kidney import find_hospital_manipulation  # noqa: E402

N_WITNESSES = 10
KILL_AFTER_N_COMPLETED = 3


def _random_market(seed: int, n_pairs: int, n_hospitals: int, edge_prob: float) -> KidneyMarket:
    rng = random.Random(seed)
    pairs = tuple(f"p{i}" for i in range(1, n_pairs + 1))
    hospitals = tuple(f"h{i}" for i in range(1, n_hospitals + 1))
    hospital_of = {p: hospitals[i % n_hospitals] for i, p in enumerate(pairs)}
    edges = set()
    for u in pairs:
        for v in pairs:
            if u != v and rng.random() < edge_prob:
                edges.add((u, v))
    return KidneyMarket(pairs=pairs, hospital_of=hospital_of, hospitals=hospitals, edges=frozenset(edges))


def _find_synthetic_witnesses(n: int) -> "list[dict]":
    """`n` GENUINE hospital-withholding manipulations (false_utility >
    truthful_utility, exactly like a real search_kidney witness -- not a
    hand-rigged utility pair), found the same way the real sweep finds them:
    `witness.search_kidney.find_hospital_manipulation` over small random
    markets. Small enough (10 pairs, 3 hospitals) that each takes well under
    a second to process, but real enough that the sanity check inside
    `process_witness` passes on its own terms. Each market/seed combination
    naturally gets its own `witness_id` (content-hashed), so no manual
    id-uniqueness bookkeeping is needed."""
    config = KidneyConfig(tiebreak_policy="max_cardinality_ilp", max_cycle_length=3, max_ilp_seconds=5.0)
    found: "list[dict]" = []
    seed = 0
    while len(found) < n and seed < 2000:
        market = _random_market(seed, n_pairs=10, n_hospitals=3, edge_prob=0.18)
        profile = KidneyProfile.truthful(market)
        for h in market.hospitals:
            if len(market.pairs_of(h)) < 3:
                continue
            w = find_hospital_manipulation(market, profile, h, config)
            if w is not None:
                found.append(w.to_dict())
                break
        seed += 1
    assert len(found) == n, f"only found {len(found)}/{n} synthetic manipulations by seed {seed}"
    return found


def _read_jsonl(path: Path):
    records = []
    if not path.exists():
        return records
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))  # must NOT raise -- a torn write would break this
    return records


class KillAndResumeIsLosslessAndNonDuplicating(unittest.TestCase):
    def test_sigterm_partway_then_rerun_covers_every_witness_exactly_once(self):
        witnesses = _find_synthetic_witnesses(N_WITNESSES)
        expected_ids = {w["witness_id"] for w in witnesses}
        self.assertEqual(len(expected_ids), N_WITNESSES, "witness fixtures must have distinct ids")

        with tempfile.TemporaryDirectory() as td:
            witness_file = Path(td) / "witnesses.jsonl"
            out_dir = Path(td) / "out"
            with open(witness_file, "w") as f:
                for w in witnesses:
                    f.write(json.dumps(w) + "\n")

            cmd = [
                sys.executable, str(SCRIPT), str(witness_file),
                "--out-dir", str(out_dir), "--max-ilp-seconds", "10",
            ]
            per_witness_path = out_dir / "per_witness.jsonl"

            # Individual synthetic witnesses solve in tens of milliseconds, far
            # too fast to reliably catch mid-run via wall-clock polling (that
            # raced and lost: the whole batch could finish inside one 50ms
            # sleep tick). Instead, read the script's own stderr progress log
            # LINE BY LINE (each "-> VERDICT" line is printed only AFTER that
            # witness's record has been written+flushed+fsync'd -- see the
            # script's `_run`) and send SIGTERM the instant we've observed
            # exactly KILL_AFTER_N_COMPLETED completions. This is event-driven,
            # not time-based, so it isn't a race against solve speed.
            proc = subprocess.Popen(
                cmd, cwd=str(PROJECT_ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, bufsize=1, env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            try:
                n_completed = 0
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    line = proc.stderr.readline()
                    if line == "":
                        break  # EOF -- process exited on its own
                    if "] processing " in line:
                        continue
                    if line.lstrip().startswith("[kidney_tiebreak_robustness]   ->"):
                        n_completed += 1
                        if n_completed >= KILL_AFTER_N_COMPLETED:
                            proc.send_signal(signal.SIGTERM)
                            break

                self.assertGreaterEqual(
                    n_completed, KILL_AFTER_N_COMPLETED,
                    "process exited on its own before reaching the kill point -- widen N_WITNESSES",
                )
                proc.wait(timeout=15)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=15)

            partial_records = _read_jsonl(per_witness_path)
            partial_ids = [r["witness_id"] for r in partial_records]
            self.assertGreaterEqual(len(partial_ids), KILL_AFTER_N_COMPLETED)
            self.assertLess(len(partial_ids), N_WITNESSES, "killed too late to test resumption meaningfully")
            self.assertEqual(len(partial_ids), len(set(partial_ids)), "duplicate witness_id written before the kill")
            self.assertTrue(set(partial_ids).issubset(expected_ids))

            # Rerun the IDENTICAL command -- must pick up exactly where it left off.
            proc2 = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=180)
            self.assertEqual(proc2.returncode, 0, msg=f"stdout={proc2.stdout}\nstderr={proc2.stderr}")

            # The resumed run's own log must show it skipped the already-done
            # witnesses (not just that the final file happens to be complete) --
            # this is the check that it didn't RE-SOLVE them. Count "processing"
            # log lines directly (rather than searching for each wid[:12] as a
            # substring) since these witness_ids are content-hashes that can
            # legitimately share a long common prefix with each other.
            self.assertIn(f"{len(partial_ids)} witness(es) already done", proc2.stderr)
            n_newly_processed = proc2.stderr.count("] processing ")
            self.assertEqual(
                n_newly_processed, N_WITNESSES - len(partial_ids),
                msg=f"resumed run should process exactly the {N_WITNESSES - len(partial_ids)} not-yet-done "
                    f"witnesses, not re-solve any of the {len(partial_ids)} already done; stderr={proc2.stderr}",
            )

            final_records = _read_jsonl(per_witness_path)
            final_ids = [r["witness_id"] for r in final_records]
            self.assertEqual(set(final_ids), expected_ids, "resumed run did not cover every witness")
            self.assertEqual(len(final_ids), len(set(final_ids)), "resumed run produced a duplicate witness entry")

            # Every witness must have reached a real verdict (not stuck UNDETERMINED
            # from an unreasonably tight time limit on these tiny fixtures).
            verdicts = {r["witness_id"]: r["verdict"] for r in final_records}
            for wid in expected_ids:
                self.assertIn(verdicts[wid], ("STRONG_ROBUST", "WEAK", "NEVER_ROBUST"), msg=(wid, verdicts[wid]))


if __name__ == "__main__":
    unittest.main()
