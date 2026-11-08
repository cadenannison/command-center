# 0054. htmx 2.0.11 is vendored at web/static/vendor/htmx.min.js

Status: accepted

Context: The pages load `/static/vendor/htmx.min.js` and nothing from a CDN (decision 0039). The task card asks for this record with the htmx version and sha256, but both were left as the placeholders `<VERSION>` and `<SHA256>`, and the file was not in the repo.
Decision: Vendor htmx **2.0.11**, the `latest` dist-tag of `htmx.org` on npm on 2026-11-07 (licence 0BSD). The file is `dist/htmx.min.js` from the npm tarball `https://registry.npmjs.org/htmx.org/-/htmx.org-2.0.11.tgz`, whose sha512 matched the `dist.integrity` npm publishes for that version before it was unpacked.
sha256 of `src/command_center/web/static/vendor/htmx.min.js`: `d6fdc75f204e6bdefa99b69bf1e6d4ac69b8a364f77929f45c13476b4000f717` (52,182 bytes). `tests/test_end_to_end.py` checks the served file against this hash.
Alternative: (a) Wait for the owner to supply the version and hash: the hash would then be checked, not just recorded. (b) The 4.x `next` tag: a pre-release line. (c) A CDN `<script>` with SRI: breaks the "nothing loaded from outside" rule.
Reason: The verification above proves the file is what npm published for 2.0.11; it does not prove that 2.0.11 is the version the owner meant. The templates use only long-standing attributes (`hx-get`, `hx-put`, `hx-delete`, `hx-headers`, `hx-target`, `hx-trigger`, `hx-swap`, `hx-swap-oob`, `hx-sync`, `hx-indicator`, `hx-disabled-elt`, `hx-confirm`), all present in 2.x. This was read from the templates, not exercised in a browser.
Where: `src/command_center/web/static/vendor/htmx.min.js`; `tests/test_end_to_end.py`.
Revisit when: the owner names a different version or hash (replace the file and supersede this record), or a CSP is added (decision 0039 left that open).
