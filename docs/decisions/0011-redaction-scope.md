# 0011. Redaction scope: emails and digit groups, before trim, over-redact on purpose

Status: accepted; partly superseded by 0240 and 0243 (the rule list, and the digit-group separators)

Context: Digit runs alone miss phone and card numbers written as `801-555-1234`, `(801) 555 1234` or `4111 1111 1111 1111`. Summary input must never carry them (0004).
Decision: `redact` replaces any token containing an email-shaped `@` with `[email]` and any group of digits joined by whitespace, dashes, dots or parentheses with 6+ digits in total with `[number]`. Only an ISO date (`YYYY-MM-DD`, real month and day) with nothing attached stays, so `20261107`, `2026-11-07-1234` and `2026-11-07.5` are redacted. `redact` runs before `trim`, never after.
Reason: A false positive costs a word of context; a miss leaks personal data. Trimming first could cut a number to a prefix of fewer than 6 digits that redaction then leaves behind.
Consequences: Some harmless text is redacted (`1 2 3 4 5 6`, `1.2.3.4.5.6`, `1 000 000`); this is accepted. A number split around a whitespace-delimited ISO date is judged in two pieces. Idempotent, and property-tested so no group of 6+ digits survives outside standalone ISO dates.
