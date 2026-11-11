# 0244. IP addresses and "[at]" / "(dot)" email spellings are masked

Status: accepted; superseded in part by 0255, 0261, 0280 and 0281 (the IPv4 position in the rule order; the characters around an IPv6 run; a four-part version after a version word; braces and a spaced "@" in an email)

Context: `10.0.0.1` has 5 digits and IPv6 has no 6-digit run, so neither was masked. `bob [at] example [dot] com` has no "@".
Decision: IPv4 is four dotted octets (0-255, leading zeros allowed), not part of a longer dotted number, masked to `[ip]`; `1.2.3.4.5.6` is therefore left to the digit rule and `3.12.1` is not an address. IPv6 is a maximal run of hex digits, ":" and "." that `ipaddress.IPv6Address` accepts (so `::1`, `fe80::1`, the full form and `::ffff:10.0.0.1`; `10:30:45` is not) and that has at least two colons and at most 45 characters; a trailing "." or ":" and one leading ":" are tried off when the whole run is not an address (`fe80::1: refused`, `addr:fe80::1`), and a run followed by a letter or digit (`Cafe::new`) is a word, not an address. A spelled-out email is a local part, "[at]" or "(at)", then a domain whose dots are "." or "[dot]" or "(dot)" (case-insensitive, single spaces allowed), masked to `[email]`. `[at]` or `(at)` alone in a sentence is not enough.
Alternative: A bare dotted-quad regex for IPv6 as well (rejected: the grammar is too easy to get wrong; the stdlib parser is exact and pure). Replace every "[at]" with "@" and rerun the email rule (rejected: `meet (at) the library` would lose its words).
Reason: The matchers are anchored at run starts and the IPv6 check is skipped for anything over 45 characters or with fewer than two colons, so time stays linear.
Consequences: Known false positives: a four-part version such as `1.2.3.4`, and a path made only of hex digits such as `a::b` or `dead::beef` (read as IPv6). `Face::Dead` is masked, `Cafe::new` and `std::vector` and times are not.
Where: `src/command_center/core/redact.py` (`_IPV4`, `_IPV6_RUN`, `_is_ipv6`, `_SPELLED_EMAIL`), `tests/test_redact_gaps.py`.
Revisit when: Four-part version numbers appear in titles often, or another obfuscation (`bob at example dot com`, no brackets) is seen.
