# 0243. "/", "_", dashes and no-break spaces join digits; a comma joins only runs of 4+ digits

Status: accepted; supersedes in part 0011 (the digit-group separators); superseded in part by 0280 (dates, times and course numbers inside a group) and 0281 (",", "*" and "x" in a 3-3-4 phone)

Context: `415/555/0132`, `415–555–0132` (en dash), `4_1_5_5_5_5_0_1_3_2` and `12345,67890` passed the digit rule of 0011, whose separators were whitespace, "-", ".", "(" and ")".
Decision: The digit-group separators are now whitespace (no-break and narrow no-break spaces included), "-", the Unicode dashes U+2010 to U+2015 and the minus U+2212, ".", "/", "_", "(" and ")", and the combining marks U+0300 to U+036F (a digit underlined or struck through by a "fancy text" generator, which NFKC cannot compose away). A "," joins two digit runs only when both sides have 4 or more digits, so `12345,67890` and `4111,1111,1111,1111` are one group (10 and 16 digits), while `$1,299.00`, `1,234,567` and `due 2026-11-07, 2026-12-01` are not joined. The 6-digit threshold, the ISO-date exemption and the over-redaction stance of 0011 are unchanged.
Alternative: Treat every comma as a joiner (rejected: it masks prices and populations and defeats the ISO-date exemption in `2026-11-07, 2026-12-01`). Exempt `MM/DD/YYYY` dates (rejected: `12/31/1999` is a birth date; over-redaction is the rule).
Reason: Separators the review listed, and nothing else, so the false-positive tests (dates, times, prices, versions) keep passing.
Consequences: Known false positives: `10/09/2026` and `11/9/2026` (6+ digits), `1/2/3/4/5/6`. Known gaps: `1,234,567,890` and `4,111,111,111,111,111` (thousands-grouped) are not joined; `12345, 67890` (comma then space) is two 5-digit runs.
Where: `src/command_center/core/redact.py` (`_SEPARATORS`, `_DIGIT_GROUP`), `tests/test_redact_gaps.py`.
Revisit when: Slash dates are common in titles, or a comma-and-space number list is seen.
