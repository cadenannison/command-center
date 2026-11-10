# 0260. Typographic dashes, quotes and list marks may sit between a keyword and its code

Status: accepted; supersedes in part 0242 (the separators allowed between the keyword and the code)

Context: A review of 0242's rule found that `Your verification code — 4821`, `code – 4821`, `code “4821”`, `code «4821»`, `code: *4821*`, `code → 4821` and `codes 4821; 9910` or `codes 48213 & 99107` came back unchanged: the gap between the keyword and the digits allowed only whitespace, ":", "#", "=", "-", brackets, straight quotes and commas. These are the shapes an SMS or a mail client produces (smart quotes, em dashes, bold asterisks), so they are realistic, not evasion.
Decision: The gap between the keyword, the words after it and the code also accepts the dashes U+2010 to U+2015 and the minus U+2212, the curly quotes U+2018 to U+201F, the guillemets U+00AB and U+00BB, "*", ";", "&", "|", ">" and the arrow U+2192. All are non-letters and non-digits, so the word and digit parts of the pattern stay disjoint from the gap and matching stays linear. The wording is also corrected: every further code is masked when it sits within five words of the PREVIOUS code, not of the keyword, so a chain of codes is masked to its end.
Alternative: Any non-word character as a gap (rejected: it would also let `code.4821.` and `code/4821` match, which are paths and dates). Unicode category tests (rejected: `re` has no cheap category class, and a callback per character would cost more than a list).
Reason: The list is the set of separators seen in real code messages; adding a character later is one line.
Consequences: A code written after any other symbol, or before its keyword (`4821 is your code`), is still not masked (0242). Over-masking grows only by the shapes above: `Code freeze — 2026`.
Where: `src/command_center/core/redact.py` (`_CODE_GAP`), `tests/test_redact_gaps.py` (rows "reviewer round 3").
Revisit when: A code message with another separator leaks, or the false positives on years cost real context.
