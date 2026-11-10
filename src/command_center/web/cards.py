"""View models for the settings page. They carry status only; no credential value reaches them."""

from collections.abc import Mapping
from dataclasses import dataclass

from command_center.services.models import SourceSettings
from command_center.services.settings import UNVERIFIED_PREFIX
from command_center.web.howto import HowTo, howto_for
from command_center.web.sources import form_for

POLL_SECONDS = 2
CONNECT_TIMEOUT_MS = 120_000
SIGN_IN_TIMEOUT_MS = 900_000  # a Google sign-in waits on a person

_STATUS_LABELS = {
    "syncing": "Syncing…",
    "ok": "Connected",
    "reconnect": "Reconnect needed",
    "error": "Error",
}


@dataclass(frozen=True)
class FieldView:
    """One input and whether the source already holds a value for it."""

    key: str
    label: str
    secret: bool
    multiline: bool
    hint: str
    is_set: bool
    last4: str | None
    # The stored (or just typed) value of a non-secret field. A secret field's is always "".
    value: str = ""


@dataclass(frozen=True)
class StatusView:
    """The sync state of a source as the page words it."""

    status: str
    label: str
    message: str


@dataclass(frozen=True)
class CardView:
    """One source's card."""

    source: str
    label: str
    note: str
    fields: tuple[FieldView, ...]
    status: StatusView
    button: str
    button_disabled: bool
    sign_in_wait: bool
    timeout_ms: int
    credential_only: bool = False
    flash: str = ""
    flash_ok: bool = True
    howto: HowTo | None = None
    can_sync: bool = False
    can_test: bool = False
    can_save_unverified: bool = False
    city_search: bool = False

    @property
    def keep_typed(self) -> bool:
        """True after a failed action: the browser keeps the secret inputs it holds (never sent)."""
        return bool(self.flash) and not self.flash_ok

    @property
    def polling(self) -> bool:
        """True while the sync runs, so the status element keeps asking."""
        return self.status.status == "syncing"


def card_view(
    item: SourceSettings,
    *,
    flash: str = "",
    flash_ok: bool = True,
    typed: Mapping[str, str] | None = None,
    offer_unverified: bool = False,
) -> CardView:
    """Build the card for a source from its settings status.

    `typed` is what the user just submitted: after a failed submit a non-secret field shows it
    instead of the stored value. A secret field never shows a value, typed or stored.
    """
    form = form_for(item.source)
    typed = typed or {}
    fields = tuple(
        FieldView(
            key=f.key,
            label=f.label,
            secret=f.secret,
            multiline=f.multiline,
            hint=f.hint,
            is_set=(key_status := item.keys.get(f.key)) is not None and key_status.set,
            # Only secrets show their ending; a plain setting shows just that it is set.
            last4=key_status.last4 if f.secret and key_status is not None else None,
            value="" if f.secret else typed.get(f.key, item.values.get(f.key, "")),
        )
        for f in form.fields
    )
    if item.sync is None and form.credential_only and any(f.is_set for f in fields):
        status = StatusView("ok", "Connected", "")
    elif item.sync is None:
        status = StatusView("none", "Not connected", "")
    else:
        label = _STATUS_LABELS.get(item.sync.status, item.sync.status)
        if item.sync.status == "error" and item.sync.message.startswith(UNVERIFIED_PREFIX):
            label = "Needs attention"
        status = StatusView(item.sync.status, label, item.sync.message)
    connected = any(f.is_set for f in fields)
    return CardView(
        source=item.source,
        label=form.label,
        note=form.note,
        fields=fields,
        status=status,
        button="Reconnect" if status.status == "reconnect" else "Connect",
        button_disabled=status.status == "syncing",
        sign_in_wait=form.sign_in_wait,
        timeout_ms=SIGN_IN_TIMEOUT_MS if form.sign_in_wait else CONNECT_TIMEOUT_MS,
        credential_only=form.credential_only,
        flash=flash,
        flash_ok=flash_ok,
        howto=howto_for(item.source),
        can_sync=connected and not form.credential_only,
        can_test=connected,
        can_save_unverified=offer_unverified,
        city_search=form.city_search,
    )
