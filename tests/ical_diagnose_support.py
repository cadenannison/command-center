"""Helpers for the feed-diagnosis tests: tiny iCalendar documents with recognisable private text."""

import socket

import httpx
import pytest

FEED_1 = "https://feeds.example.com/course-1/token-abc123"
FEED_2 = "https://feeds.example.com/course-2/token-def456"
TITLE = "PRIVATE-TITLE-Midterm"
DESCRIPTION = "PRIVATE-DESCRIPTION-chapter"
LOCATION = "PRIVATE-LOCATION-room"
# Nothing here may ever reach the output of a diagnosis.
PRIVATE = (
    "token-abc123",
    "token-def456",
    "feeds.example.com",
    "https://",
    TITLE,
    DESCRIPTION,
    LOCATION,
)


def resolves_to_public(monkeypatch: pytest.MonkeyPatch, address: str = "93.184.216.34") -> None:
    info = (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))

    def fake(*_args: object, **_kwargs: object) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [info]

    monkeypatch.setattr(socket, "getaddrinfo", fake)


def calendar(*components: str) -> str:
    body = "\r\n".join(components)
    head = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//fake//cc tests//EN"
    return f"{head}\r\n{body}\r\nEND:VCALENDAR\r\n"


def vevent(uid: str, *lines: str) -> str:
    text = [
        "BEGIN:VEVENT",
        f"UID:{uid}@fake",
        "DTSTAMP:20261001T000000Z",
        f"SUMMARY:{TITLE}",
        f"DESCRIPTION:{DESCRIPTION}",
        f"LOCATION:{LOCATION}",
        *lines,
        "END:VEVENT",
    ]
    return "\r\n".join(text)


def vtodo(uid: str, *lines: str) -> str:
    text = [
        "BEGIN:VTODO",
        f"UID:{uid}@fake",
        "DTSTAMP:20261001T000000Z",
        f"SUMMARY:{TITLE}",
        *lines,
    ]
    return "\r\n".join([*text, "END:VTODO"])


def feed(body: str, content_type: str = "text/calendar; charset=utf-8") -> httpx.Response:
    return httpx.Response(200, text=body, headers={"content-type": content_type})
