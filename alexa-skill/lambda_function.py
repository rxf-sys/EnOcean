"""AWS Lambda for a self-hosted Alexa Smart Home skill in front of Home Assistant.

Forwards every Alexa directive unchanged to Home Assistant's built-in Alexa
Smart Home API (POST {BASE_URL}/api/alexa/smart_home) using the OAuth token
that Alexa obtained through account linking, and returns Home Assistant's
answer to Alexa.

Environment variables:
  BASE_URL                 public Home Assistant URL, no trailing slash (required)
  NOT_VERIFY_SSL           "true" to skip certificate checks (testing only)
  DEBUG                    "true" for debug logging; enables LONG_LIVED_ACCESS_TOKEN
  LONG_LIVED_ACCESS_TOKEN  token used when a test directive carries none (DEBUG only)

Runtime: Python 3.12+ (stdlib only). Region for German skills: eu-west-1.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import urllib.error
import urllib.request
import uuid

_LOGGER = logging.getLogger("ha_alexa")
TIMEOUT_SECONDS = 8


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def _find_token(directive: dict) -> str | None:
    """Return the account-linking token of a directive, if any."""
    payload = directive.get("payload", {})
    endpoint = directive.get("endpoint", {})
    for scope in (endpoint.get("scope"), payload.get("grantee"), payload.get("scope")):
        if isinstance(scope, dict) and scope.get("token"):
            return scope["token"]
    return None


def _error_response(directive: dict, error_type: str, message: str) -> dict:
    """Build an Alexa ErrorResponse event for the given directive."""
    header = directive.get("header", {})
    event = {
        "header": {
            "namespace": "Alexa",
            "name": "ErrorResponse",
            "messageId": str(uuid.uuid4()),
            "payloadVersion": "3",
        },
        "payload": {"type": error_type, "message": message},
    }
    if header.get("correlationToken"):
        event["header"]["correlationToken"] = header["correlationToken"]
    if directive.get("endpoint"):
        event["endpoint"] = {"endpointId": directive["endpoint"].get("endpointId")}
    return {"event": event}


def lambda_handler(event: dict, context) -> dict:  # noqa: ARG001 (Lambda signature)
    debug = _env_flag("DEBUG")
    _LOGGER.setLevel(logging.DEBUG if debug else logging.INFO)

    directive = event.get("directive")
    if not isinstance(directive, dict) or directive.get("header", {}).get("payloadVersion") != "3":
        raise ValueError("Unsupported request: expected an Alexa Smart Home v3 directive")

    base_url = os.environ.get("BASE_URL", "").rstrip("/")
    if not base_url:
        return _error_response(directive, "INTERNAL_ERROR", "BASE_URL is not configured")

    token = _find_token(directive)
    if token is None and debug:
        token = os.environ.get("LONG_LIVED_ACCESS_TOKEN") or None
    if token is None:
        return _error_response(
            directive, "INVALID_AUTHORIZATION_CREDENTIAL", "No access token in directive"
        )

    context_ssl = ssl.create_default_context()
    if _env_flag("NOT_VERIFY_SSL"):
        context_ssl.check_hostname = False
        context_ssl.verify_mode = ssl.CERT_NONE

    request = urllib.request.Request(
        f"{base_url}/api/alexa/smart_home",
        data=json.dumps(event).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    _LOGGER.debug("Forwarding %s.%s", directive["header"].get("namespace"), directive["header"].get("name"))
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS, context=context_ssl) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        _LOGGER.error("Home Assistant answered HTTP %s", err.code)
        if err.code in (401, 403):
            return _error_response(
                directive, "INVALID_AUTHORIZATION_CREDENTIAL", "Home Assistant rejected the token"
            )
        return _error_response(directive, "INTERNAL_ERROR", f"Home Assistant HTTP {err.code}")
    except (urllib.error.URLError, TimeoutError) as err:
        _LOGGER.error("Home Assistant not reachable: %s", err)
        return _error_response(directive, "ENDPOINT_UNREACHABLE", "Home Assistant not reachable")

    _LOGGER.debug("Response: %s", body)
    return json.loads(body)
