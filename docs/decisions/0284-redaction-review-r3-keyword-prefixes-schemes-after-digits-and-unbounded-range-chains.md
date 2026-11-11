# 0284. Redaction review (task R3): keyword prefixes and schemes after digits are fixed; chained ranges stay

Status: accepted

Context: The reviewer of task R3 read the rules of 0280 and 0281 and found four ways a secret could now pass. Two are mechanical, one is a small design choice, one is a known cost of the agenda rule.
Decision: (1) The all-capitals course-number exemption and the course-number exemption (`NNNN-NNN`, `NNNN/NNNN` after a letters prefix) do not apply when the prefix is a code keyword: the keyword set now also holds `VERIFY`, `PASSWD` and `OTPS`, so `PASSWD 4821`, `VERIFY 4821` and `pin 4821-993` are masked. (2) A scheme URL may be preceded, in the same run, by digits, `+`, `.` or `-`; that prefix stays and the rest is `[url]` (`1.https://zoom.us/j/1?pwd=x` gives `1.[url]`). (3) Known cost, kept: M/D dates and section ranges chain without limit (`41.11-11.11-11.11-11.11`), so a number made only of such pieces stays; capping the chain would mask real schedules of ranges, and the shape is not one a phone, card or key takes.
Alternative: Cap each chain at one range (rejected: `Reading 3.1-3.4, 4.1-4.2` style lines and `11/10-11/14` weeks are the point of 0280). Match the scheme anywhere in a run (rejected: quadratic on a long run without `://`).
Reason: Priority rule of 0280 (dates and ranges stay) with the keyword and scheme leaks closed, because those two shapes are real secrets and not agenda text.
Consequences: `1x://y` is now `1[url]`. `2020-11-10https://x.io` keeps the date and masks the URL. A number written as a long chain of date-like ranges is a leak by design.
Where: `src/command_center/core/redact.py` (`_URL`, `_KEYWORD_WORDS`, `_after_course_prefix`); tests in `tests/test_redact_agenda.py` (`test_redact_review_findings_keyword_prefixes_and_schemes_after_digits`).
Revisit when: A secret is seen that a range chain hides, or a real keyword is missing from the set.
