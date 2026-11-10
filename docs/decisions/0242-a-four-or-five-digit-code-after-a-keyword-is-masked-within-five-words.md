# 0242. A 4-5 digit code after code, otp, pin, passcode or verification is masked within five words

Status: accepted; superseded in part by 0260 (the separators allowed between the keyword and the code)

Context: `Your code: 48213` has 5 digits, under the 6-digit rule of 0011, and an SMS code is the thing most likely to be pasted into a subject line.
Decision: A run of 4 or 5 digits is replaced by `[number]` when it follows `code`, `otp`, `pin`, `passcode` or `verification` (case-insensitive, optional plural `s`, the keyword not inside a longer word, so `barcode` does not count) with at most five letter-only words and any of whitespace, ":", "#", "=", "-", brackets, quotes or commas between, or nothing at all (`OTP4821`, `code (4821)`, `code, 4821`). The run must be the whole number: a digit, or "-", "/" or "." followed by a digit, after it ends the match, so `code due 2026-11-09` keeps its date and `pin 1234.5` keeps its decimal. Digits before the keyword (`4821 is your code`) are not covered.
Alternative: Three words (rejected: `verification code for your account is 12345` is five words away and is the typical shape). Mask every 4-5 digit run (rejected: room numbers, years and course numbers are the context the summary needs). Mask digits on both sides of the keyword (rejected: `4821 is your code` could be anything; revisit if seen).
Reason: Window and keyword list come from the card; five words is the smallest window that covers the typical SMS sentence.
Consequences: Further codes in the same window are masked by the same match (`backup codes 48213 and 99107`), so the output is stable without a second pass. Known false positives: a year or room number within five words after the keyword (`Code Camp 2026`, `Code freeze for Fall 2026`, `pin the notice to room 2031`), masked on purpose: a 19xx or 20xx PIN is common, so exempting years would leak them. The bare words `code`, `pin`, `otp` and `verification` are never masked.
Where: `src/command_center/core/redact.py` (`_CODE`, `_redact_code`), `tests/test_redact_gaps.py`.
Revisit when: The false positives on years cost real context, or a code is seen before its keyword.
