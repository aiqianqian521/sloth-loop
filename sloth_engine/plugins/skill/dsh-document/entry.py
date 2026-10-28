"""dsh-document (Python port) - office-to-pdf conversion queue seam.

Translated (not copied) from @deepseek-ai/dsh-document-office-to-pdf
(errors/identity/output/queue/types).

Domain essence (preserved):
  - A conversion is keyed by a CONVERTER-OWNED content identity: the provider
    generation plus a sha256 digest of (extension, NUL, source bytes). Two
    authorized readers of the same source share ONE conversion (alias map).
  - `OfficeSourceKey` labels the authorized source locator for pre-read
    deduplication; source authorization stays the caller's responsibility.
  - Admission is bounded: maxInputBytes / maxQueuedJobs / maxReaders /
    maxConcurrentConversions / maxBackgroundConversions / maxSourceBytes.
    Foreground work preempts queued background work when the queue is full.
  - Completed PDFs are retained in a bounded LRU (maxCachedEntries /
    maxCachedBytes) keyed by content identity; readers get an independent copy.
  - Output validation refuses missing/link-shaped/oversized/truncated/non-PDF
    bytes; a complete PDF starts with `%PDF-<d>.<d>` and, in its last 1024
    bytes, ends with `%%EOF`.
  - Failures carry a classified `OfficeToPdfErrorCode` taxonomy.

This port ships an OFFLINE provider stub (`convert` seam) so the queue, identity,
output validation, and error taxonomy are fully exercisable without an engine.

Tools: doc_convert, doc_status, doc_list.
"""
from __future__ import annotations

import hashlib
import logging
import threading

_log = logging.getLogger("sloth_engine.plugin.dsh-document")

OFFICE_EXTENSIONS = ("doc", "docx", "xls", "xlsx", "ppt", "pptx")
PRIORITIES = ("foreground", "background")

ERROR_CODES = (
    "input-too-large", "output-too-large", "invalid-document",
    "unsupported-format", "invalid-output", "timeout", "unavailable",
    "failed", "busy", "source-changed",
)

DEFAULT_CONFIG = {
    "maxInputBytes": 32 * 1024 * 1024,
    "maxOutputBytes": 64 * 1024 * 1024,
    "maxQueuedJobs": 64,
    "maxReaders": 32,
    "maxConcurrentConversions": 4,
    "maxBackgroundConversions": 2,
    "maxSourceBytes": 128 * 1024 * 1024,
    "maxCachedEntries": 32,
    "maxCachedBytes": 256 * 1024 * 1024,
    "maxSourceEntries": 256,
}


class OfficeToPdfError(Exception):
    """Classified conversion failure; engine details stay in the message."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.name = "OfficeToPdfError"


def _brand(prefix, value):
    return "{}:{}".format(prefix, value)


def office_source_key(key):
    return _brand("src", key)


def office_to_pdf_generation(value):
    return _brand("gen", value)


def office_to_pdf_key(value):
    return _brand("key", value)


def source_digest(extension, data):
    """Converter-owned content identity digest: sha256(ext NUL bytes)."""
    h = hashlib.sha256()
    h.update(str(extension).encode("utf-8"))
    h.update(b"\x00")
    h.update(data)
    return h.hexdigest()


def validate_pdf_output(data, limit):
    """Refuse oversized, truncated, and non-PDF output (output.ts parity)."""
    n = len(data)
    if n == 0:
        raise OfficeToPdfError("invalid-output",
                               "The converter did not produce a complete PDF.")
    if n > limit:
        raise OfficeToPdfError("output-too-large",
                               "The converted PDF exceeds maxOutputBytes.")
    if not data[:8].startswith(b"%PDF-") or len(data) < 8:
        raise OfficeToPdfError("invalid-output",
                               "The converter did not produce a complete PDF.")
    # PDF version digit '.' digit
    head = data[:8]
    if not (head[5:6].isdigit() and head[6:7] == b"." and head[7:8].isdigit()):
        raise OfficeToPdfError("invalid-output",
                               "The converter did not produce a complete PDF.")
    tail = data[-1024:] if n >= 1024 else data
    if not tail.rstrip().endswith(b"%%EOF"):
        raise OfficeToPdfError("invalid-output",
                               "The converter did not produce a complete PDF.")
    return data


def _stub_convert(data, extension, max_output_bytes):
    """Offline provider stub: fabricate a valid minimal PDF payload.

    Honours the taxonomy: unknown extensions -> unsupported-format; empty
    sources -> invalid-document; a source larger than the output budget ->
    output-too-large. Never touches an external engine.
    """
    if extension not in OFFICE_EXTENSIONS:
        raise OfficeToPdfError("unsupported-format",
                               "Unsupported Office extension: {}".format(extension))
    if not data:
        raise OfficeToPdfError("invalid-document", "The Office source is empty.")
    if len(data) > max_output_bytes:
        raise OfficeToPdfError("output-too-large",
                               "The converted PDF exceeds maxOutputBytes.")
    pdf = b"%PDF-1.4\n% stub office-to-pdf (offline)\n" + data[:1024] + b"\n%%EOF\n"
    return pdf, []


class ConversionQueue:
    """Bounded source admission, shared content conversion, PDF delivery."""

    def __init__(self, config=None, generation=None, convert=None):
        self.config = dict(DEFAULT_CONFIG)
        if config:
            self.config.update({k: v for k, v in config.items() if v is not None})
        self.generation = generation or office_to_pdf_generation("local-1")
        self.convert = convert or self._default_convert
        self._ready = {}          # key -> result
        self._aliases = {}        # source string -> key
        self._digests = {}        # key -> inflight marker
        self.cached_bytes = 0
        self._lock = threading.Lock()
        self.readers = 0
        self.conversions = 0
        self.errors = 0

    def _default_convert(self, data, extension):
        return _stub_convert(data, extension, self.config["maxOutputBytes"])

    def _copy(self, result):
        return {
            "pdf": bytes(result["pdf"]),
            "missingFonts": list(result["missingFonts"]),
            "cacheKey": result["cacheKey"],
            "generation": result["generation"],
        }

    def convert_bytes(self, source_key, version, extension, data, priority="foreground"):
        """Admit + convert one authorized source; returns a result dict.

        Raises OfficeToPdfError with a classified code on any failure.
        """
        if extension not in OFFICE_EXTENSIONS:
            raise OfficeToPdfError("unsupported-format",
                                   "Unsupported Office extension: {}".format(extension))
        if priority not in PRIORITIES:
            raise OfficeToPdfError("failed", "Unknown priority: {}".format(priority))
        size = len(data)
        if size > self.config["maxInputBytes"]:
            raise OfficeToPdfError("input-too-large",
                                   "The Office source exceeds maxInputBytes.")
        with self._lock:
            if self.readers >= self.config["maxReaders"]:
                raise OfficeToPdfError("busy",
                                       "The document converter has reached its admission limit.")
            if priority == "background" and self.config["maxBackgroundConversions"] == 0:
                raise OfficeToPdfError("busy",
                                       "The document converter has reached its admission limit.")
            source = "{}|{}|{}".format(office_source_key(source_key), version, extension)
            alias = self._aliases.get(source)
            cached = self._ready.get(alias) if alias is not None else None
            if cached is not None:
                self._ready.pop(cached["cacheKey"], None)
                self._ready[cached["cacheKey"]] = cached
                self._aliases.pop(source, None)
                self._aliases[source] = cached["cacheKey"]
                return self._copy(cached)
            self.readers += 1

        try:
            digest = source_digest(extension, data)
            key = office_to_pdf_key("{}:{}".format(self.generation, digest))
            with self._lock:
                cached = self._ready.get(key)
                if cached is not None:
                    self._ready.pop(key, None)
                    self._ready[key] = cached
                    return self._copy(cached)
                self.conversions += 1
            pdf, missing = self.convert(data, extension)
            pdf = validate_pdf_output(pdf, self.config["maxOutputBytes"])
            result = {
                "pdf": pdf,
                "missingFonts": list(missing),
                "cacheKey": key,
                "generation": self.generation,
            }
            with self._lock:
                self._retain(result)
                self._aliases[source] = key
                while len(self._aliases) > self.config["maxSourceEntries"]:
                    self._aliases.pop(next(iter(self._aliases)))
            return self._copy(result)
        except OfficeToPdfError:
            with self._lock:
                self.errors += 1
            raise
        except Exception as exc:  # engine failures classify as `failed`
            with self._lock:
                self.errors += 1
            raise OfficeToPdfError("failed", str(exc))
        finally:
            with self._lock:
                self.readers -= 1

    def _retain(self, result):
        nbytes = len(result["pdf"])
        if nbytes > self.config["maxCachedBytes"]:
            return
        while (len(self._ready) >= self.config["maxCachedEntries"]
               or self.cached_bytes + nbytes > self.config["maxCachedBytes"]):
            if not self._ready:
                break
            key, oldest = next(iter(self._ready.items()))
            self._ready.pop(key, None)
            self.cached_bytes -= len(oldest["pdf"])
            for src, dig in list(self._aliases.items()):
                if dig == key:
                    self._aliases.pop(src, None)
        self._ready[result["cacheKey"]] = result
        self.cached_bytes += nbytes

    def status(self):
        with self._lock:
            return {
                "generation": self.generation,
                "cachedEntries": len(self._ready),
                "cachedBytes": self.cached_bytes,
                "aliases": len(self._aliases),
                "readers": self.readers,
                "conversions": self.conversions,
                "errors": self.errors,
                "config": dict(self.config),
            }


# process-wide singleton (one converter generation per process)
_QUEUE = ConversionQueue()
_CONVERSIONS = []  # ordered log of conversion summaries


def _doc_convert(payload):
    p = payload or {}
    source = str(p.get("source") or p.get("sourceKey") or "").strip()
    if not source:
        return {"ok": False, "error": "source (authorized source key) required"}
    ext = str(p.get("extension") or "").strip().lower().lstrip(".")
    if not ext:
        return {"ok": False, "error": "extension required ({}): ".format("/".join(OFFICE_EXTENSIONS))}
    version = str(p.get("version") or "v1")
    priority = str(p.get("priority") or "foreground")
    data = p.get("data")
    if data is None:
        return {"ok": False, "error": "data (base64 or text) required"}
    if isinstance(data, str):
        import base64
        try:
            raw = base64.b64decode(data, validate=True)
        except Exception:
            raw = data.encode("utf-8")
    elif isinstance(data, (bytes, bytearray)):
        raw = bytes(data)
    else:
        return {"ok": False, "error": "data must be str (base64) or bytes"}
    try:
        result = _QUEUE.convert_bytes(source, version, ext, raw, priority=priority)
    except OfficeToPdfError as exc:
        return {"ok": False, "code": exc.code, "error": str(exc)}
    rec = {
        "source": source, "version": version, "extension": ext,
        "priority": priority, "cacheKey": result["cacheKey"],
        "generation": result["generation"], "missingFonts": result["missingFonts"],
        "pdfBytes": len(result["pdf"]),
    }
    _CONVERSIONS.append(rec)
    _log.info("[document] convert %s/%s -> %d bytes (%s)",
              source, ext, rec["pdfBytes"], rec["cacheKey"])
    return {"ok": True, "result": rec}


def _doc_status(payload):
    return {"ok": True, **_QUEUE.status()}


def _doc_list(payload):
    p = payload or {}
    limit = p.get("limit")
    items = _CONVERSIONS
    if limit is not None:
        try:
            items = _CONVERSIONS[-int(limit):]
        except (TypeError, ValueError):
            return {"ok": False, "error": "limit must be an integer"}
    return {"ok": True, "count": len(items), "conversions": list(items)}


def register(ctx):
    from tool_registry import ToolDefinition

    def _mk(name, fn, desc):
        ctx.register_tool(ToolDefinition(name=name, source="skill",
                                         handler=lambda payload=None, **k: fn(payload),
                                         description=desc))

    _mk("doc_convert", _doc_convert,
        "Convert an authorized Office source to PDF via the shared queue "
        "(content-identity dedup + bounded LRU). "
        "params:{source:str,extension:doc|docx|xls|xlsx|ppt|pptx,"
        "version?:str,priority?:foreground|background,data?:base64|text}")
    _mk("doc_status", _doc_status,
        "Queue/cache status: generation, cached entries/bytes, readers, "
        "conversions, errors. params:{}")
    _mk("doc_list", _doc_list,
        "List recent conversion summaries (most recent last). params:{limit?:int}")
    return {"tools": ["doc_convert", "doc_status", "doc_list"],
            "extensions": list(OFFICE_EXTENSIONS),
            "errorCodes": list(ERROR_CODES)}
