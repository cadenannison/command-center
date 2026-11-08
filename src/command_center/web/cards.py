"""View models for the settings page. They carry status only; no credential value reaches them."""

from dataclasses import dataclass

from command_center.services.models import SourceSettings
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
    flash: str = ""
    flash_ok: bool = True

    @property
    def polling(self) -> bool:
        """True while the sync runs, so the status element keeps asking."""
        return self.status.status == "syncing"


def card_view(item: SourceSettings, *, flash: str = "", flash_ok: bool = True) -> CardView:
    """Build the card for a source from its settings status."""
    form = form_for(item.source)
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
        )
        for f in form.fields
    )
    if item.sync is None:
        status = StatusView("none", "Not connected", "")
    else:
        label = _STATUS_LABELS.get(item.sync.status, item.sync.status)
        status = StatusView(item.sync.status, label, item.sync.message)
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
        flash=flash,
        flash_ok=flash_ok,
    )
