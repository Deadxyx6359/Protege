"""Reading Gmail and Google Calendar as a connected address (C5), against a fake Google.

The address is already connected: its lasting sign-in sealed, a short-lived one
held. Every request must carry that sign-in, go only to Google's own hosts, and
be held to the address's own permission. Nothing leaves this computer.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

import pytest

from akira.core.connect import gcal, gmail, google
from akira.core.connect.google import AccountStore, ConnectError, GoogleAccounts, refresh_name
from akira.core.net import client as net
from akira.core.net import query_value
from akira.core.permissions import Policy, SecretStore, secrets

pytestmark = pytest.mark.skipif(not secrets.available(), reason="needs DPAPI")

ADDRESS = "akira.helper@gmail.com"
LIST = "/gmail/v1/users/me/messages"
EVENTS = "/calendar/v3/calendars/primary/events"


class Reply:
    def __init__(self, body, status=200):
        self.status, self.reason = status, "OK"
        self._body = json.dumps(body).encode("utf-8")

    def getheader(self, name, default=None):
        return "application/json" if name.lower() == "content-type" else default

    def read(self, size):
        piece, self._body = self._body[:size], self._body[size:]
        return piece


class FakeGoogle:
    def __init__(self, answers):
        self.answers, self.requests = answers, []

    def open(self, host, address, port, timeout):
        fake = self

        class Connection:
            def request(self, method, path, body=None, headers=None):
                fake.requests.append({"host": host, "path": path,
                                      "headers": {k.lower(): v for k, v in (headers or {}).items()}})
                self._reply = Reply(fake.answers[(host, path.split("?", 1)[0])])

            def getresponse(self):
                return self._reply

            def close(self):
                pass

        return Connection()


@pytest.fixture
def fake_google(monkeypatch):
    def install(answers):
        fake = FakeGoogle(answers)
        monkeypatch.setattr(net, "_resolve", lambda host, port: ["142.250.180.10"])
        monkeypatch.setattr(net, "_open", fake.open)
        return fake
    return install


@pytest.fixture
def accounts(tmp_path):
    vault = SecretStore(tmp_path / "secrets")
    store = AccountStore(tmp_path / "accounts.json")
    vault.put(refresh_name(ADDRESS), "1//lasting")
    store.save(google.Account(ADDRESS, ("mail", "calendar"), 1.0))
    google._ACCESS[ADDRESS] = ("ya29.held", 10**12)
    yield GoogleAccounts(vault=vault, store=store)
    google._ACCESS.clear()


def allowed(*capabilities) -> Policy:
    policy = Policy()
    for capability in capabilities:
        policy.grant(capability, (ADDRESS,))
    return policy


def encoded(data: bytes | str) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def message(message_id, subject, *, payload=None, unread=True):
    headers = [{"name": "From", "value": "Bank <alerts@bank.example>"},
               {"name": "To", "value": ADDRESS}, {"name": "Subject", "value": subject},
               {"name": "Date", "value": "Fri, 11 Sep 2026 09:00:00 +0100"}]
    return {"id": message_id, "threadId": f"t{message_id}",
            "labelIds": ["INBOX"] + (["UNREAD"] if unread else []),
            "snippet": "Your statement is ready &amp; waiting",
            "payload": dict(payload or {}, headers=headers)}


def read(accounts, policy, message_id="18a1"):
    return gmail.read(accounts, ADDRESS, message_id, policy=policy, audit=None, actor="t")


# -- mail -----------------------------------------------------------------------------------------


def test_a_search_lists_what_gmail_found_with_who_and_when(accounts, fake_google):
    fake = fake_google({
        ("gmail.googleapis.com", LIST): {"messages": [{"id": "18a1"}, {"id": "../../drafts"},
                                                      {"id": "18a2"}]},
        ("gmail.googleapis.com", f"{LIST}/18a1"): message("18a1", "Statement"),
        ("gmail.googleapis.com", f"{LIST}/18a2"): message("18a2", "Receipt", unread=False)})
    found = gmail.search(accounts, ADDRESS, "from:bank", policy=allowed("mail.read"), audit=None,
                         actor="t")
    assert [m.subject for m in found] == ["Statement", "Receipt"], "an id that is not one was used"
    assert found[0].unread and not found[1].unread
    assert found[0].sender == "Bank <alerts@bank.example>"
    assert found[0].snippet == "Your statement is ready & waiting"
    first = "https://gmail.googleapis.com" + fake.requests[0]["path"]
    assert (query_value(first, "q"), query_value(first, "maxResults")) == ("from:bank", "10")
    assert "metadataHeaders=Subject" in fake.requests[1]["path"]
    assert {r["headers"]["authorization"] for r in fake.requests} == {"Bearer ya29.held"}
    assert {r["host"] for r in fake.requests} == {"gmail.googleapis.com"}


def test_reading_prefers_the_plain_text_and_only_names_attachments(accounts, fake_google):
    payload = {"mimeType": "multipart/mixed", "parts": [
        {"mimeType": "multipart/alternative", "parts": [
            {"mimeType": "text/plain", "body": {"data": encoded("Hello, in plain words.")}},
            {"mimeType": "text/html", "body": {"data": encoded("<p>Hello, in markup.</p>")}}]},
        {"mimeType": "application/pdf", "filename": "statement.pdf",
         "body": {"attachmentId": "ANGj", "size": 4096}}]}
    fake = fake_google({("gmail.googleapis.com", f"{LIST}/18a1"):
                        message("18a1", "Statement", payload=payload)})
    letter = read(accounts, allowed("mail.read"))
    assert letter.text == "Hello, in plain words." and letter.attachments == ("statement.pdf",)
    assert [r["path"] for r in fake.requests] == [f"{LIST}/18a1?format=full"], \
        "an attachment was fetched"


def test_a_message_in_markup_only_is_read_as_text(accounts, fake_google):
    page = "<html><body><h1>Hi</h1><p>Your code is <b>1234</b></p><script>steal()</script></body></html>"
    fake_google({("gmail.googleapis.com", f"{LIST}/18a1"): message(
        "18a1", "Code", payload={"mimeType": "text/html", "body": {"data": encoded(page)}})})
    text = read(accounts, allowed("mail.read")).text
    assert "Your code is" in text and "1234" in text
    assert "<b>" not in text and "steal" not in text


def test_the_charset_a_message_names_is_honoured(accounts, fake_google):
    part = {"mimeType": "text/plain",
            "headers": [{"name": "Content-Type", "value": 'text/plain; charset="iso-8859-1"'}],
            "body": {"data": encoded("Caf\xe9 at nine".encode("latin-1"))}}
    fake_google({("gmail.googleapis.com", f"{LIST}/18a1"): message(
        "18a1", "Coffee", payload={"mimeType": "multipart/alternative", "parts": [part]})})
    assert read(accounts, allowed("mail.read")).text == "Café at nine"


def test_an_id_that_is_not_one_never_reaches_an_address(accounts, fake_google):
    fake = fake_google({})
    with pytest.raises(ConnectError, match="not a Gmail message id"):
        read(accounts, allowed("mail.read"), message_id="../drafts?format=raw")
    assert fake.requests == []


def test_without_mail_read_for_the_address_nothing_is_read(accounts, fake_google):
    fake = fake_google({("gmail.googleapis.com", f"{LIST}/18a1"): message("18a1", "Statement")})
    with pytest.raises(ConnectError, match="Not permitted"):
        read(accounts, allowed("calendar.read"))
    assert fake.requests == []


# -- the calendar -----------------------------------------------------------------------------------


START = datetime(2026, 9, 12, 8, 0, tzinfo=timezone.utc)


def test_events_come_in_order_with_the_cancelled_left_out(accounts, fake_google):
    fake = fake_google({("www.googleapis.com", EVENTS): {"items": [
        {"summary": "Supervisor", "start": {"dateTime": "2026-09-14T09:00:00+01:00"},
         "end": {"dateTime": "2026-09-14T10:00:00+01:00"}, "location": "Room 4",
         "organizer": {"email": "dr@uni.example"}, "attendees": [{}, {}],
         "description": "<p>Bring <b>chapter two</b></p>"},
        {"status": "cancelled", "summary": "Called off"},
        {"summary": "Bank holiday", "start": {"date": "2026-09-15"},
         "end": {"date": "2026-09-16"}}]}})
    found = gcal.events(accounts, ADDRESS, start=START, days=7, policy=allowed("calendar.read"),
                        audit=None, actor="t")
    assert [e.title for e in found] == ["Supervisor", "Bank holiday"]
    supervisor, holiday = found
    assert not supervisor.all_day and holiday.all_day
    assert (supervisor.where, supervisor.organizer, supervisor.attendees) == \
        ("Room 4", "dr@uni.example", 2)
    assert "chapter two" in supervisor.description and "<b>" not in supervisor.description
    sent = "https://www.googleapis.com" + fake.requests[0]["path"]
    assert query_value(sent, "timeMin") == "2026-09-12T08:00:00Z"
    assert query_value(sent, "timeMax") == "2026-09-19T08:00:00Z"
    assert query_value(sent, "singleEvents") == "true"
    assert fake.requests[0]["headers"]["authorization"] == "Bearer ya29.held"


def test_one_look_spans_a_month_at_most(accounts, fake_google):
    fake = fake_google({("www.googleapis.com", EVENTS): {"items": []}})
    gcal.events(accounts, ADDRESS, start=START, days=400, policy=allowed("calendar.read"),
                audit=None, actor="t")
    sent = "https://www.googleapis.com" + fake.requests[0]["path"]
    assert query_value(sent, "timeMax") == "2026-10-13T08:00:00Z"


def test_the_calendar_is_its_own_permission(accounts, fake_google):
    fake = fake_google({("www.googleapis.com", EVENTS): {"items": []}})
    with pytest.raises(ConnectError, match="Not permitted"):
        gcal.events(accounts, ADDRESS, start=START, days=7, policy=allowed("mail.read"),
                    audit=None, actor="t")
    assert fake.requests == []
