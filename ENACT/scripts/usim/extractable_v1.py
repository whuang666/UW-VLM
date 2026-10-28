"""extractable_permutation_v1 -- secondary metric for the USIM ordering questions.

The primary metric stays ``usim_strict_v0.3`` (whole-string parse).  This module adds an
*independent* secondary metric that asks a narrower question: can a single
valid permutation be recovered from an answer that finished normally?

Rules to freeze before final test evaluation; existing dev analyses remain post-hoc:

1. Only answers that returned successfully **and** finished with ``finish_reason == "stop"``
   are eligible.  Truncated (``length``), missing or failed responses score 0.
2. The whole answer must contain **exactly one** bracketed list, and that list must be at
   the **end** of the answer (trailing whitespace allowed, nothing else after it).
3. That list must satisfy the same integer / length / permutation requirements as the
   strict parser.
4. Multiple candidate lists, truncation, missing or failed answers score 0.
5. Extraction never reads the ground truth; gt is only used afterwards, to score a
   successfully extracted permutation.
6. Every condition uses this same rule and every question stays in the denominator.

Reported numbers are counts and rates, not "perception".  A pass here does not turn a
failed budget gate into a pass: the gate's own criteria are unchanged.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

VERSION = "extractable_permutation_v1"

# A bracketed run without nested brackets.  Deliberately not "greedy": nested or malformed
# brackets are treated as no usable candidate rather than silently repaired.
_LIST_PATTERN = re.compile(r"\[[^\[\]]*\]")


def extract(text: Optional[str], finish_reason: Optional[str], expected_length: int) -> Dict[str, Any]:
    """Try to recover one trailing permutation from ``text``.

    Returns ``{"status": "ok"|"zero", "permutation": [...]|None, "reason": str, "list_count": int}``.
    ``reason`` is ``ok`` or one of: ``not_stop:<finish_reason>``, ``missing``, ``no_list``,
    ``multiple_lists``, ``malformed_brackets``, ``list_not_at_end``, ``unparsable``, ``not_a_list``,
    ``wrong_length``, ``non_integer``, ``not_a_permutation``.
    """
    if finish_reason != "stop":
        return {"status": "zero", "permutation": None, "reason": f"not_stop:{finish_reason}", "list_count": 0}
    if text is None:
        return {"status": "zero", "permutation": None, "reason": "missing", "list_count": 0}
    if not isinstance(text, str):
        return {"status": "zero", "permutation": None, "reason": "bad_type", "list_count": 0}

    stripped = text.strip()
    if not stripped:
        return {"status": "zero", "permutation": None, "reason": "missing", "list_count": 0}

    matches = list(_LIST_PATTERN.finditer(stripped))
    if not matches:
        return {"status": "zero", "permutation": None, "reason": "no_list", "list_count": 0}
    if len(matches) > 1:
        return {"status": "zero", "permutation": None, "reason": "multiple_lists", "list_count": len(matches)}
    if stripped.count("[") != 1 or stripped.count("]") != 1:
        return {"status": "zero", "permutation": None, "reason": "malformed_brackets", "list_count": 1}

    match = matches[0]
    if stripped[match.end():].strip():
        return {"status": "zero", "permutation": None, "reason": "list_not_at_end", "list_count": 1}

    # Delegate the complete candidate to the actual primary parser. No copied
    # integer/length/permutation implementation can drift independently.
    from scripts.usim.evaluate import USIMEvaluator

    permutation, reason = USIMEvaluator.parse_strict(match.group(0), expected_length)
    if permutation is None:
        return {"status": "zero", "permutation": None, "reason": reason, "list_count": 1}
    return {"status": "ok", "permutation": permutation, "reason": "ok", "list_count": 1}


SPEC_TEXT = (
    "eligible only if the response succeeded and finish_reason=='stop'; the answer must contain "
    "exactly one '[' and one ']', forming one list at the end (trailing whitespace only; "
    "no punctuation, fences, unmatched or nested brackets); the candidate is passed directly to "
    "USIMEvaluator.parse_strict with expected_length=num_states-1, a permutation of 1..(num_states-1); "
    "multiple lists, truncation, missing or failed answers "
    "score 0; extraction never reads gt; the rule is identical for every condition and every "
    "question stays in the denominator"
)
