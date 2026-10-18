"""Signed merchant requests, modeled on Visa's Trusted Agent Protocol (simulated).

Every payment request the agent sends a merchant is signed with RFC 9421 HTTP Message
Signatures and an Ed25519 key, tagged `agent-payer-auth`. The signature covers the merchant
host, the path and a SHA-256 digest of the body (amount, merchant, token), so changing any of
them breaks it. Merchants fetch the public key from the key directory the engine serves.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

TAG = "agent-payer-auth"
VALID_S = 300  # a signed request expires after 5 minutes
DIRECTORY_PATH = "/.well-known/http-message-signatures-directory"
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:8000")  # where merchants find the key directory

# TAP_PRIVATE_KEY: base64 of the raw 32-byte Ed25519 key, so the key id survives restarts.
# ponytail: without it a new key is made per process; fine for the demo, set it on Vultr.
_raw = os.getenv("TAP_PRIVATE_KEY")
_key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(_raw)) if _raw else Ed25519PrivateKey.generate()
_pub = _key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
KEY_ID = hashlib.sha256(_pub).hexdigest()[:16]
_seen_nonces: set[str] = set()


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def directory() -> dict:
    """The public key as a JWKS, served at DIRECTORY_PATH."""
    return {"keys": [{"kty": "OKP", "crv": "Ed25519", "kid": KEY_ID, "x": _b64url(_pub), "use": "sig"}]}


def _digest(body: bytes) -> str:
    return f"sha-256=:{base64.b64encode(hashlib.sha256(body).digest()).decode()}:"


def _base(authority: str, path: str, digest: str, params: str) -> bytes:
    """RFC 9421 signature base."""
    return (f'"@authority": {authority}\n"@path": {path}\n"content-digest": {digest}\n'
            f'"@signature-params": {params}').encode()


def sign(authority: str, path: str, body: dict) -> tuple[bytes, dict]:
    """Return (raw body, headers) for a signed merchant request."""
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    created = int(time.time())
    params = (f'("@authority" "@path" "content-digest");created={created};expires={created + VALID_S}'
              f';keyid="{KEY_ID}";alg="ed25519";nonce="{uuid.uuid4().hex}";tag="{TAG}"')
    digest = _digest(raw)
    sig = base64.b64encode(_key.sign(_base(authority, path, digest, params))).decode()
    return raw, {
        "Content-Digest": digest,
        "Signature-Input": f"sig1={params}",
        "Signature": f"sig1=:{sig}:",
        "Signature-Agent": f'"{PUBLIC_URL}{DIRECTORY_PATH}"',
    }


def verify(authority: str, path: str, raw: bytes, headers: dict, public_key: bytes = _pub) -> tuple[bool, str]:
    """What a merchant checks, following Cloudflare's TAP validation steps. Returns (ok, reason)."""
    try:
        params = headers["Signature-Input"].removeprefix("sig1=")
        sig = base64.b64decode(headers["Signature"].removeprefix("sig1=:").removesuffix(":"))
        fields = dict(p.split("=", 1) for p in params.split(";")[1:])
    except (KeyError, ValueError):
        return False, "missing or malformed signature headers"
    now = int(time.time())
    if fields.get("tag") != f'"{TAG}"':
        return False, "wrong tag"
    if not fields.get("created", "").isdigit() or not fields.get("expires", "").isdigit():
        return False, "missing created/expires"
    if not int(fields["created"]) <= now + 5 or now > int(fields["expires"]):
        return False, "expired or not yet valid"
    if _digest(raw) != headers.get("Content-Digest"):
        return False, "body does not match its digest"
    nonce = fields.get("nonce", "")
    if nonce in _seen_nonces:
        return False, "replayed nonce"
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(sig, _base(authority, path, headers["Content-Digest"], params))
    except InvalidSignature:
        return False, "bad signature"
    _seen_nonces.add(nonce)
    return True, "valid"
