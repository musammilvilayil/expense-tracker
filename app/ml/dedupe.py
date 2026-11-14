"""Duplicate detection for imported transactions.

Goal: uploading 3 months and later a 6-month statement that contains those
same 3 months must add only the new months, and re-uploading a file must add
nothing. Two genuine same-day purchases of the same amount must both survive.

Approach: one-to-one matching. Each incoming row may "consume" at most one
existing row with the same date, amount and type whose description matches
(same words, or at least one shared merchant word, ignoring bank noise like
UPI/NEFT). Consumed rows are duplicates, everything else is new.
"""
from collections import defaultdict

from .preprocess import normalize_merchant


def _tokens(text):
    return {t for t in normalize_merchant(text).split() if len(t) > 1}


def _key(row):
    return (row["date"], round(float(row["amount"]), 2), row["type"])


def find_duplicates(incoming, existing):
    """Return a list aligned with `incoming`: matched existing row (dict) or None."""
    pool = defaultdict(list)
    for e in existing:
        pool[_key(e)].append({"row": e, "tokens": _tokens(e["description"]),
                              "norm": normalize_merchant(e["description"]), "used": False})
    out = []
    for r in incoming:
        cands = [c for c in pool.get(_key(r), []) if not c["used"]]
        rt, rn = _tokens(r["description"]), normalize_merchant(r["description"])
        pick = next((c for c in cands if c["norm"] == rn), None)                      # exact words
        if pick is None:
            pick = next((c for c in cands if rt & c["tokens"]), None)                 # shared merchant word
        if pick is None and cands and not rt:                                          # nothing to compare
            pick = next((c for c in cands if not c["tokens"]), None)
        if pick is not None:
            pick["used"] = True
            out.append(pick["row"])
        else:
            out.append(None)
    return out
