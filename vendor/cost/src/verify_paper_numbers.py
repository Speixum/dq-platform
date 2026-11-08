# -*- coding: utf-8 -*-
"""Check every number quoted in the manuscript table against the measured result files.

Rule of the project: no number in the paper may be typed by hand without a run behind it.
This script parses the version table of a manuscript copy and compares each cell with
results/versions/table_final.csv. Any mismatch is printed and the exit code is 1.

The manuscript itself is not published in this repository, so point the script at your own
copy of the draft:

    python src/verify_paper_numbers.py path/to/draft.md
    python src/verify_paper_numbers.py            # falls back to paper/draft_v1.md if present
"""
import csv
import os
import re
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ROOT = ROOT
MD = os.path.join(ROOT, "paper", "draft_v1.md")
if len(sys.argv) > 1:
    MD = sys.argv[1]
CSV = os.path.join(ROOT, "results", "versions", "table_final.csv")


def main():
    if not os.path.exists(CSV):
        print("missing", CSV)
        return 1
    if not os.path.exists(MD):
        print("manuscript not found:", MD)
        print("this repository ships results only; pass the path to your own copy of the draft,")
        print("e.g.  python src/verify_paper_numbers.py ../paper/draft_v1.md")
        return 0
    ref = {}
    with open(CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ref[row["version"].strip()] = row

    text = open(MD, encoding="utf-8").read()
    rows = [ln for ln in text.splitlines() if re.match(r"^\|\s*V\d\d\s*\|", ln)]
    print("manuscript rows:", len(rows), "| reference versions:", len(ref))
    bad = 0
    seen = set()
    for ln in rows:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        vid = cells[0]
        seen.add(vid)
        if vid not in ref:
            print("  %s not in reference" % vid); bad += 1; continue
        r = ref[vid]
        if len(cells) == 7:      # main table: version | corruption | n_train | Q1 | RMA | acc | drop
            q1_md, rma_md, acc_md, drop_md = cells[3], cells[4], cells[5], cells[6]
        elif len(cells) == 6:    # cumulative table: version | defects | Q1 | RMA | acc | drop
            q1_md, rma_md, acc_md, drop_md = cells[2], cells[3], cells[4], cells[5]
        else:
            print("  cannot parse row:", ln); bad += 1; continue
        want = [("Q1", q1_md, "%.3f" % float(r["Q1"])),
                ("RMA", rma_md, "%.3f" % float(r["RMA"])),
                ("acc", acc_md, "%.2f" % float(r["acc_pct"]))]
        for name, got, expect in want:
            if got != expect:
                print("  MISMATCH %s %s: manuscript=%s measured=%s" % (vid, name, got, expect))
                bad += 1
        if abs(float(drop_md) - float(r["drop_pp"])) > 0.011:
            print("  MISMATCH %s drop: manuscript=%s measured=%s" % (vid, drop_md, r["drop_pp"]))
            bad += 1
    missing = [k for k in ref if k not in seen]
    if missing:
        print("  versions measured but not in the table:", missing)
    print("rows checked:", len(seen), "mismatches:", bad)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
