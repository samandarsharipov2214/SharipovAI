"""Lossless storage encoding for the largest immutable evidence producer.

Only council news assessments are eligible. Public readers return the original
JSON, including its types; versions, timestamps and identifiers are unchanged.
The original UTF-8 bytes and SHA-256 are retained, so expansion is reversible.
"""
from __future__ import annotations

import base64
import hashlib
import json
import zlib

NAMESPACE = "council_news_assessments"
MARKER = "__sharipovai_lossless_json_v1__"
MAX_BYTES = 16 * 1024 * 1024


def pack(namespace: str, raw: str) -> str:
    if namespace != NAMESPACE or len(raw) < 2048:
        return raw
    value = json.loads(raw)
    if isinstance(value, dict) and MARKER in value:
        # Reject ambiguous caller-owned envelopes, rather than treating them as
        # an instruction to substitute different evidence.
        raise ValueError("reserved evidence encoding marker")
    data = raw.encode("utf-8")
    if len(data) > MAX_BYTES:
        raise ValueError("evidence exceeds encoding budget")
    encoded = json.dumps({MARKER: {
        "codec": "zlib+base64", "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "data": base64.b64encode(zlib.compress(data, 6)).decode("ascii"),
    }}, separators=(",", ":"))
    return encoded if len(encoded) < len(raw) else raw


def unpack(raw: str) -> str:
    value = json.loads(raw)
    if not isinstance(value, dict) or MARKER not in value:
        return raw
    if set(value) != {MARKER}:
        raise ValueError("ambiguous evidence encoding")
    envelope = value[MARKER]
    size = envelope["bytes"]
    if type(size) is not int or not 0 <= size <= MAX_BYTES or envelope["codec"] != "zlib+base64":
        raise ValueError("invalid evidence encoding budget")
    compressed = base64.b64decode(envelope["data"], validate=True)
    decoder = zlib.decompressobj()
    data = decoder.decompress(compressed, size + 1)
    if (len(data) != size or not decoder.eof or decoder.unused_data
            or hashlib.sha256(data).hexdigest() != envelope["sha256"]):
        raise ValueError("evidence encoding integrity failure")
    return data.decode("utf-8")


def loads(raw: str):
    return json.loads(unpack(raw))
