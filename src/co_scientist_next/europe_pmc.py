"""Europe PMC acquisition only. Every HTTP send is a durable M15 Attempt."""

import base64
import hashlib
import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict
from urllib.parse import urlencode

from .contracts import CallResponse, KnownCallFailure, Usage
from .literature import (
    AccessLevel,
    ExecutionStatus,
    FetchResult,
    SearchResult,
    SourceRecord,
)
from .store import now

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/"
SCOPE = "Europe PMC indexed publications; manual query; relevance order; no automatic expansion"
MAX_BYTES = 8_000_000


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None  # A redirect is a response, not an invisible second send.


def public_http(request):
    """One send, no retries, no redirects. Missing response remains uncertain."""
    if not request["url"].startswith(BASE):
        raise ValueError("Only the fixed official Europe PMC API is supported")
    started = now()
    req = urllib.request.Request(request["url"], headers=request["headers"], method="GET")
    opener = urllib.request.build_opener(NoRedirect())
    try:
        response = opener.open(req, timeout=30)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        body = response.read(MAX_BYTES + 1)
        truncated = len(body) > MAX_BYTES
        body = body[:MAX_BYTES]
        envelope = {
            "url": request["url"],
            "status_code": response.code,
            "headers": dict(response.headers.items()),
            "body_base64": base64.b64encode(body).decode("ascii"),
            "sha256": hashlib.sha256(body).hexdigest(),
            "truncated": truncated,
            "started_at": started,
            "received_at": now(),
        }
    if not 200 <= envelope["status_code"] < 300:
        raise KnownCallFailure(
            f"Europe PMC HTTP {envelope['status_code']}",
            response=envelope,
            usage=Usage(tool_units=1),
        )
    return CallResponse(envelope, Usage(tool_units=1))


def body_text(envelope):
    if envelope.get("truncated"):
        raise ValueError("Response exceeded 8 MB; saved prefix only, not complete material")
    raw = base64.b64decode(envelope["body_base64"], validate=True)
    if hashlib.sha256(raw).hexdigest() != envelope["sha256"]:
        raise ValueError("Saved response digest mismatch")
    return raw.decode("utf-8")


def source_record(row):
    source, identifier = row["source"], row["id"]
    if not isinstance(source, str) or not isinstance(identifier, str):
        raise TypeError("Invalid provider identity")
    if not re.fullmatch(r"[A-Z]+", source) or not re.fullmatch(r"[A-Za-z0-9._-]+", identifier):
        raise ValueError("Unsupported provider identity")
    return SourceRecord(
        f"epmc:{source}:{identifier}",
        f"https://europepmc.org/article/{source}/{identifier}",
        row.get("title") or "Untitled provider record",
    )


def plain_abstract(value):
    # Europe PMC abstracts may contain XML markup. Never render provider HTML.
    try:
        return " ".join(ET.fromstring("<abstract>" + value + "</abstract>").itertext()).strip()
    except ET.ParseError:
        return value.strip()  # Literal text, still displayed with textContent.


class EuropePMC:
    """LiteraturePort bound to an executing TaskCalls, without retrieval strategy."""

    def __init__(self, calls, *, page_size=5, transport=public_http):
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or not 1 <= page_size <= 20
        ):
            raise ValueError("page_size must be 1..20 for this explicit small-request slice")
        self.calls, self.page_size, self.transport = calls, page_size, transport
        self.details = {
            "provider": "Europe PMC",
            "model_read": False,
            "relationships": [],
            "transport": "real_public_http"
            if transport is public_http
            else "injected_test_transport",
        }

    def get(self, key, path, params=None):
        url = BASE + path + ("?" + urlencode(params) if params else "")
        request = {
            "method": "GET",
            "url": url,
            "headers": {
                "Accept": "application/json" if params else "application/xml",
                "User-Agent": "CoScientist-W1-L1/1.0 (manual development acquisition)",
            },
        }
        response = self.calls.execute(key, "Europe PMC public REST", request, self.transport)
        self.last_envelope = response.output
        return body_text(response.output), response.output["received_at"]

    def search(self, request):
        if request.source != "Europe PMC" or request.scope != SCOPE:
            raise ValueError("Unsupported source/scope")
        try:
            text, at = self.get(
                "search",
                "search",
                {
                    "query": request.query,
                    "format": "json",
                    "resultType": "lite",
                    "pageSize": self.page_size,
                    "cursorMark": request.cursor or "*",
                    "synonym": "false",
                },
            )
            data = json.loads(text)
            total = data["hitCount"]
            rows = data["resultList"]["result"]
            if (
                isinstance(total, bool)
                or not isinstance(total, int)
                or total < 0
                or not isinstance(rows, list)
            ):
                raise ValueError("Malformed search response")
            records, metadata, bad = [], [], []
            seen = set()
            for row in rows:
                try:
                    record = source_record(row)
                except (KeyError, TypeError, ValueError):
                    bad.append("Malformed source record retained in raw response")
                    continue
                if record.source_ref in seen:
                    continue
                seen.add(record.source_ref)
                records.append(record)
                metadata.append({"source": asdict(record), "metadata": row, "access": "metadata"})
            next_cursor = data.get("nextCursorMark")
            if next_cursor == (request.cursor or "*") or not rows:
                next_cursor = None
            # Conservative on later pages: only a short final page with no next cursor
            # can claim exhaustion. Total is provider-reported, not independent coverage.
            complete = (
                not next_cursor
                and not bad
                and (len(rows) < self.page_size or (request.cursor is None and total <= len(rows)))
            )
            if not next_cursor and not complete:
                bad.append("Pagination exhaustion cannot be established from this response")
            self.details.update(
                {
                    "sources": metadata,
                    "raw_returned_count": len(rows),
                    "deduplicated_count": len(records),
                    "warnings": bad,
                    "provider_request": data.get("request"),
                    "raw_response_locator": "attempt:search/body_base64#resultList.result",
                }
            )
            return SearchResult(
                request,
                ExecutionStatus.INCOMPLETE if bad else ExecutionStatus.SUCCEEDED,
                at,
                tuple(records),
                total,
                next_cursor,
                complete,
                "; ".join(bad) or None,
            )
        except KnownCallFailure as exc:
            return SearchResult(
                request, ExecutionStatus.FAILED, exc.response["received_at"], error=str(exc)
            )
        except (ValueError, TypeError, KeyError) as exc:
            return SearchResult(
                request,
                ExecutionStatus.INCOMPLETE,
                self.last_envelope["received_at"],
                error=str(exc),
            )

    def fetch(self, request):
        match = re.fullmatch(r"epmc:([A-Z]+):([A-Za-z0-9._-]+)", request.source_ref)
        if not match:
            raise ValueError("Unsupported source identity")
        source, identifier = match.groups()
        record = None
        access, text, at = AccessLevel.NONE, None, None
        try:
            raw, at = self.get(
                "metadata",
                f"article/{source}/{identifier}",
                {
                    "resultType": "core",
                    "format": "json",
                },
            )
            data = json.loads(raw)
            rows = [data["result"]] if data.get("result") else []
            if not rows:
                raise ValueError(
                    "Source not returned by identity lookup; not evidence of scientific absence"
                )
            row = rows[0]
            found = source_record(row)
            if found.source_ref != request.source_ref:
                raise ValueError("Identity lookup returned a different source")
            record = found
            access = AccessLevel.METADATA
            self.details.update(
                {
                    "metadata": row,
                    "source": asdict(record),
                    "metadata_locator": "attempt:metadata/body_base64#result",
                    "relationships": [
                        {
                            "basis": "provider versionList; not independently verified",
                            "provider_value": row["versionList"],
                        }
                    ]
                    if row.get("versionList")
                    else [],
                }
            )
            if request.desired_access == AccessLevel.METADATA:
                return FetchResult(request, ExecutionStatus.SUCCEEDED, at, access, record)
            if row.get("abstractText", "").strip():
                text = plain_abstract(row["abstractText"])
                if text:
                    access = AccessLevel.ABSTRACT
                    self.details["text_locator"] = (
                        "attempt:metadata/body_base64#result.abstractText"
                    )
                    self.details["representation"] = (
                        "provider abstract, markup flattened; not full text"
                    )
            if request.desired_access == AccessLevel.ABSTRACT and access == AccessLevel.ABSTRACT:
                return FetchResult(request, ExecutionStatus.SUCCEEDED, at, access, record, text)
            if request.desired_access == AccessLevel.FULL_TEXT:
                pmcid = row.get("pmcid", "")
                if row.get("isOpenAccess") != "Y" or not re.fullmatch(r"PMC[0-9]+", pmcid):
                    raise ValueError(
                        "No provider-listed OA PMCID: fullTextXML unavailable through this adapter"
                    )
                xml, at = self.get("fulltext", pmcid + "/fullTextXML")
                if "<!ENTITY" in xml.upper():
                    raise ValueError("XML entity declarations not supported")
                article = ET.fromstring(xml)
                if article.tag != "article" or article.find("body") is None:
                    raise ValueError("No article body: cannot label this response full text")
                if (
                    article.get("article-type") in ("abstract", "conference-abstract")
                    or not "".join(article.find("body").itertext()).strip()
                ):
                    raise ValueError(
                        "Abstract-only or empty article body is not a retrieved full article"
                    )
                pmc_ids = [
                    x.text
                    for x in article.findall(".//article-id")
                    if x.get("pub-id-type") in ("pmc", "pmcid")
                ]
                if not any(str(x).removeprefix("PMC") == pmcid[3:] for x in pmc_ids):
                    raise ValueError("Full-text PMCID does not match the requested source")
                text = "\n".join(t.strip() for t in article.itertext() if t.strip())
                access = AccessLevel.FULL_TEXT
                self.details.update(
                    {
                        "pmcid": pmcid,
                        "text_locator": "attempt:fulltext/body_base64#/article",
                        "representation": "JATS XML saved; flattened article text, not a scientific interpretation",
                        "supplementary": "not fetched; links inside XML are not obtained supplementary materials",
                        "limitations": "Figures/binary files and supplementary files not downloaded",
                    }
                )
                return FetchResult(
                    request,
                    ExecutionStatus.SUCCEEDED,
                    at,
                    access,
                    record,
                    text,
                    limitation=self.details["limitations"],
                )
            reason = (
                "Supplementary acquisition not implemented"
                if request.desired_access == AccessLevel.SUPPLEMENTARY
                else "No abstract supplied by provider"
            )
            raise ValueError(reason)
        except KnownCallFailure as exc:
            reason, at = str(exc), exc.response["received_at"]
        except (ValueError, TypeError, KeyError, ET.ParseError) as exc:
            reason = str(exc)
            at = self.last_envelope["received_at"]
        self.details["requested_access_unavailable"] = reason
        return FetchResult(
            request,
            ExecutionStatus.INCOMPLETE if record else ExecutionStatus.FAILED,
            at,
            access,
            record,
            text,
            limitation=reason,
            error=reason,
        )
