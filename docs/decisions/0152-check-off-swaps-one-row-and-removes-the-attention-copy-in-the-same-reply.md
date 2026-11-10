# 0152. Check-off swaps one row and removes the attention copy in the same reply

Status: accepted

Context: One item can be on a page more than once: the day's agenda or the week list, the "needs attention" list, the month's deadline list. Each copy is its own `<li>`, so a swap of one leaves the others stale. A done item has no priority, so it should leave the priority list.
Decision: Every copy has the id `row-<ctx>-<item id>` (`ctx` is agenda, attention, week or deadline). The control posts to `/items/{id}/done?ctx=...` and the reply is that row drawn again, swapped in place (`hx-target="closest li"`, `outerHTML`). When the check-off comes from another list, the reply also carries `<li id="row-attention-..." hx-swap-oob="delete">` so the attention copy goes at once. When it comes from the attention list itself, the row stays, struck through, with Undo, and is gone on reload. Other copies (such as a week row seen from Today) refresh on reload. Undo is offered only for the user's own check-off; an item the source finished stays done. Weather rows have no controls. Without an item service (`container.items is None`) no control is drawn and the routes are 404.
Alternative: Reload the whole page after every click; re-render every list in each reply; a small script that finds and edits all copies.
Reason: One swap keeps the page where the user is (scroll, open panels, typed notes) and needs no script of our own. The stale copies are the same item seen elsewhere and a reload corrects them; the price is paid only when the user opens two lists that show the same item.
Where: `src/command_center/web/item_routes.py`, `src/command_center/web/templates/_item_row.html`, `_rows.html`, `tests/test_web_items.py`.
Revisit when: Users keep both lists in view and the stale copy confuses them; then re-render all copies with out-of-band swaps.
