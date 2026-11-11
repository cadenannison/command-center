# 0282. Defanged URLs, "at" and "dot" in words and colon-separated phones are known gaps of redaction

Status: accepted

Context: Decision 0281 widens redaction to the shapes the review found in realistic text. Three more spellings were named by the same review; each can only be caught by a rule that also damages ordinary text, and the project manager asked for them to be recorded, not chased.
Decision: These are known gaps, with no code: (1) a defanged URL whose scheme is not followed by `://` or whose dots are bracketed (`hxxps://example[.]com` is now masked by the scheme rule of 0281, but `hxxps example[.]com` and `example[.]com/x` are not); (2) an email spelled in words (`bob at example dot com`): `at` and `dot` are ordinary words; (3) a phone number separated by colons (`801:555:1234`): a colon joins hours, minutes and ratios (`10:30`, `1:1`), so joining digits across it would mask times; (4) any other change that would damage ordinary text (priority rule of 0280).
Alternative: Mask `word at word dot word` (rejected: `meet at noon dot com` reads the same as `bob at example dot com`, and so does every sentence with `at` and `dot`). Join digits across a colon when the groups are 3-3-4 (rejected for now: `801:555:1234` is rare and `2026-11-12 10:30:45` style text needs the colon to stay a time separator; revisit with a real sample).
Reason: 0240 says redaction is best-effort; the review's priority rule says a readable summary comes first.
Consequences: A person who types one of these leaks it to the provider when the AI summary is on. The summary is opt-in and off by default (AGENTS.md rule 6) and item text is a title or a trimmed subject.
Where: `docs/contracts/core.md` (Redaction, known gaps).
Revisit when: One of these is seen in real text, or a way is found to catch it without damaging dates, times and ordinary sentences.
