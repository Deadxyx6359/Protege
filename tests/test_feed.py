"""Reading feeds (C6): RSS 2.0, RSS 1.0 and Atom as plain entries, and anything
that is not a feed, or is a feed carrying a document type, refused with a reason.
"""

from __future__ import annotations

import pytest

from protege.core.net import feed as feed_module
from protege.core.net.feed import Entry, FeedError, parse_feed

RSS = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
  <title>Garden notes</title>
  <link>https://example.com/</link>
  <item>
    <title>Tomatoes &amp; beans</title>
    <link>https://example.com/tomatoes</link>
    <guid isPermaLink="false">post-2</guid>
    <pubDate>Thu, 10 Sep 2026 08:00:00 GMT</pubDate>
    <description><![CDATA[<p>Stake them <b>early</b>.</p><script>steal()</script>]]></description>
  </item>
  <item>
    <title>Seed swap</title>
    <link>
      https://example.com/swap
    </link>
  </item>
</channel>
</rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title type="text">Release notes</title>
  <link rel="self" href="https://example.com/feed.atom"/>
  <entry>
    <title type="html">Version 2 &lt;em&gt;is out&lt;/em&gt;</title>
    <link rel="replies" href="https://example.com/v2#comments"/>
    <link href="https://example.com/v2"/>
    <id>tag:example.com,2026:v2</id>
    <updated>2026-09-10T08:00:00Z</updated>
    <content type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml"><p>Faster <b>search</b>.</p></div></content>
  </entry>
</feed>"""

RDF = b"""<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel rdf:about="https://example.com/"><title>Old style</title></channel>
  <item rdf:about="https://example.com/one">
    <title>One</title>
    <link>https://example.com/one</link>
    <dc:date>2026-09-01</dc:date>
  </item>
</rdf:RDF>"""


def test_rss_entries_come_out_as_plain_text():
    feed = parse_feed(RSS)
    assert feed.title == "Garden notes"
    assert feed.entries == (
        Entry("post-2", "Tomatoes & beans", "https://example.com/tomatoes",
              "Thu, 10 Sep 2026 08:00:00 GMT", "Stake them early."),
        Entry("https://example.com/swap", "Seed swap", "https://example.com/swap"),
    )


def test_atom_takes_the_alternate_link_and_reads_markup_as_text():
    feed = parse_feed(ATOM)
    assert feed.title == "Release notes"
    assert feed.entries == (Entry("tag:example.com,2026:v2", "Version 2 is out",
                                  "https://example.com/v2", "2026-09-10T08:00:00Z",
                                  "Faster search."),)


def test_rss_one_is_read_by_its_rdf_about():
    feed = parse_feed(RDF)
    assert feed.title == "Old style"
    assert feed.entries == (Entry("https://example.com/one", "One", "https://example.com/one",
                                  "2026-09-01"),)


def test_a_document_type_is_refused_before_anything_is_expanded():
    bomb = (b'<?xml version="1.0"?>\n<!DOCTYPE rss [<!ENTITY a "aaaaaaaaaa">'
            b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>\n'
            b"<rss><channel><title>&b;</title></channel></rss>")
    with pytest.raises(FeedError, match="document type"):
        parse_feed(bomb)


@pytest.mark.parametrize("page", [
    b"<!DOCTYPE html><html><body><p>Hello</p></body></html>",
    b"<!doctype html>\n<html><body><p>Hello<br></body></html>",
    b"<html><head><title>x</title></head><body></body></html>",
])
def test_a_web_page_is_not_a_feed_and_says_what_to_do(page):
    with pytest.raises(FeedError, match="as a page instead"):
        parse_feed(page)


@pytest.mark.parametrize("data,reason", [
    (b"", "could not be read"),
    (b"not xml at all", "could not be read"),
    (b"<rss><channel><title>&nbsp;</title></channel></rss>", "undefined entity"),
    (b"<rss>" + b"<a>" * 70 + b"</a>" * 70 + b"</rss>", "nested too deeply"),
    (b"<opml><body/></opml>", "not a feed"),
])
def test_what_cannot_be_read_is_refused_with_a_reason(data, reason):
    with pytest.raises(FeedError, match=reason):
        parse_feed(data)


def test_entries_and_summaries_are_bounded(monkeypatch):
    monkeypatch.setattr(feed_module, "MAX_ENTRIES", 2)
    monkeypatch.setattr(feed_module, "MAX_SUMMARY_CHARS", 10)
    items = b"".join(b"<item><guid>%d</guid><description>A long summary here</description></item>"
                     % n for n in range(3))
    feed = parse_feed(b"<rss><channel>" + items + b"</channel></rss>")
    assert [entry.id for entry in feed.entries] == ["0", "1"]
    assert feed.entries[0].summary == "A long su…"


def test_an_entry_with_nothing_to_know_it_by_is_left_out():
    feed = parse_feed(b"<rss><channel><item><description>x</description></item>"
                      b"<item><title>Only a title</title></item></channel></rss>")
    assert [entry.title for entry in feed.entries] == ["Only a title"]
    assert feed.entries[0].id.startswith("Only a title")
