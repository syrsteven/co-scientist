"""One unauthenticated GET using the Responses body reader; never generate or read keys.

Run separately for each route. Direct disables application proxy discovery only;
OS routing/TUN remains in control. A complete 401 is a connectivity result, not
proof that authenticated model generation succeeds.
"""

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from co_scientist_next.europe_pmc import NoRedirect
from co_scientist_next.reading_model import transport_error
from co_scientist_next.responses_model import TrackedHandler, proxy_facts, read_response_body


def probe(route, proxy=None):
    handlers = [NoRedirect()]
    if route == "direct":
        handlers.append(urllib.request.ProxyHandler({}))
    elif route == "explicit":
        parsed = urlsplit(proxy or "")
        if (
            parsed.scheme != "http"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Explicit HTTP proxy without credentials required")
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    start = time.monotonic()
    trace = {"start": start, "deadline": start + 30, "phase": "request_open"}
    result = {
        "route": route,
        "endpoint": "https://api.openai.com/v1/models",
        "method": "GET",
        "authorization_sent": False,
        "model_post_attempts": 0,
        "credentials_read": False,
        "system_proxy_discovery": proxy_facts(),
        "proxy_environment_present": {
            key: bool(os.environ.get(key))
            for key in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY")
        },
        "application_proxy_disabled": route == "direct",
    }
    try:
        request = urllib.request.Request(result["endpoint"], headers={"Accept": "application/json"})
        try:
            response = urllib.request.build_opener(*handlers, TrackedHandler(trace)).open(
                request, timeout=20
            )
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            trace["phase"] = "response_read"
            raw, truncated = read_response_body(response, trace, 20)
            result.update(
                http_status=response.code,
                bytes=len(raw),
                body_sha256=hashlib.sha256(raw).hexdigest(),
                complete_body=not truncated,
            )
            try:
                result["json_object"] = isinstance(json.loads(raw), dict)
            except ValueError:
                result["json_object"] = False
    except Exception as exc:  # noqa: BLE001 -- safe allowlist, no exception strings
        result["error"] = transport_error(exc, trace["phase"]).error_record()
    result["elapsed_seconds"] = time.monotonic() - start
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", choices=("system", "direct", "explicit"), required=True)
    parser.add_argument("--proxy")
    parser.add_argument("--output")
    args = parser.parse_args()
    if bool(args.proxy) != (args.route == "explicit"):
        parser.error("Only explicit route requires --proxy; no automatic fallback")
    result = probe(args.route, args.proxy)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(output)
    print(output, end="")
    if not result.get("complete_body"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
