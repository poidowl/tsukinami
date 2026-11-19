#!/usr/bin/env python3
"""Shared helpers for the Itako ASR tuning loop (HTTP retry, kana CER, scoring).

This module is intentionally free of hitofude / yomu / kotoba imports so unit
tests can run without the synthesizer stack.
"""
from __future__ import annotations

import errno
import http.client
import json
import math
import os
import re
import subprocess
import time
import unicodedata
import urllib.error
import urllib.request

DEFAULT_LLM_MODEL = "default_model"
DEFAULT_LLM_URL = "http://127.0.0.1:8090/v1"
DEFAULT_ASR_URLS = (
    "http://127.0.0.1:8091/v1/audio/transcriptions",
    "http://127.0.0.1:8092/v1/audio/transcriptions",
)
DEFAULT_HTTP_TIMEOUT_SEC = 120
DEFAULT_RETRY_BUDGET_SEC = 90
DEFAULT_OPENJTALK_PYTHON = os.path.expanduser("~/kana/bin/python")

# pyopenjtalk emits ONNX / backend warnings on stdout. Real kana lines are marked.
OPENJTALK_LINE_MARK = "@@"
_OPENJTALK_SNIPPET = (
    "import sys,json,re,pyopenjtalk\n"
    "for t in json.load(sys.stdin):\n"
    "    print('%s' + re.sub(r'[^ァ-ヴー]', '', pyopenjtalk.g2p(t, kana=True)))\n"
    % OPENJTALK_LINE_MARK
)


def is_connection_error(exc):
    """True for connection refused / dropped (not HTTP status or read timeout)."""
    if exc is None:
        return False
    if isinstance(exc, urllib.error.HTTPError):
        return False
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, str):
            s = reason.lower()
            return any(
                tok in s
                for tok in (
                    "connection refused",
                    "connection reset",
                    "connection aborted",
                    "broken pipe",
                    "remotely closed",
                    "network is unreachable",
                )
            )
        return is_connection_error(reason)
    if isinstance(
        exc,
        (
            ConnectionRefusedError,
            ConnectionResetError,
            BrokenPipeError,
            ConnectionAbortedError,
            http.client.RemoteDisconnected,
            http.client.IncompleteRead,
        ),
    ):
        return True
    if isinstance(exc, OSError) and exc.errno in (
        errno.ECONNREFUSED,
        errno.ECONNRESET,
        errno.EPIPE,
        errno.ECONNABORTED,
    ):
        return True
    return False


def request_with_retry(
    req,
    timeout=DEFAULT_HTTP_TIMEOUT_SEC,
    retry_budget=DEFAULT_RETRY_BUDGET_SEC,
    sleeper=time.sleep,
    urlopen=urllib.request.urlopen,
):
    """urlopen with 1, 2, 4, 8... backoff, total sleep capped at retry_budget seconds.

    Retries only connection refused / dropped. timeout is per-request (>=120s).
    """
    delay = 1.0
    slept = 0.0
    while True:
        try:
            with urlopen(req, timeout=timeout) as resp:
                return resp.read(), resp.getcode()
        except Exception as exc:
            if not is_connection_error(exc) or slept >= retry_budget:
                raise
            this_delay = min(delay, retry_budget - slept)
            if this_delay <= 0:
                raise
            sleeper(this_delay)
            slept += this_delay
            delay *= 2


def clamp_and_round_knob_dict(cand, active_knobs, bounds):
    """Clamp each knob to [lo, hi] and round to the bound's digit count.

    Missing / non-numeric values still return (None, reason). Out-of-range
    values are not rejected; they are clamped to the nearer end of the range.
    `bounds` maps name -> (lo, hi, ndig, desc).
    """
    if not isinstance(cand, dict):
        return None, "proposal is not a JSON object"
    cleaned = {}
    for k in active_knobs:
        if k not in cand:
            return None, f"missing required knob '{k}'"
        try:
            v = float(cand[k])
        except (TypeError, ValueError):
            return None, f"non-numeric value for '{k}': {cand[k]!r}"
        if not math.isfinite(v):
            return None, f"non-finite value for '{k}'"
        lo, hi, ndig, _ = bounds[k]
        if v < lo:
            v = lo
        elif v > hi:
            v = hi
        cleaned[k] = int(round(v)) if ndig == 0 else round(v, ndig)
    return cleaned, None


def extract_json_object(raw_text):
    # Strip a thinking block if a model emits one, then take the first JSON object.
    s = re.sub(r"<think>[\s\S]*?</think>", "", raw_text or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.I).strip()
    m = re.search(r"\{[\s\S]*\}", s)
    if not m:
        raise ValueError(f"No JSON object found in LLM response: {s[:160]!r}")
    return json.loads(m.group(0))


def load_json_from_llm_response(fetch_content_fn):
    """Parse JSON from fetch_content_fn(). Retry the fetch once if unparseable.

    Returns (obj, n_fetches). Raises ValueError / json.JSONDecodeError after
    the second failed parse.
    """
    raw = fetch_content_fn()
    try:
        return extract_json_object(raw), 1
    except (ValueError, json.JSONDecodeError):
        raw = fetch_content_fn()
        return extract_json_object(raw), 2


def to_katakana(s):
    out = []
    for ch in s:
        o = ord(ch)
        if 0x3041 <= o <= 0x3096:
            out.append(chr(o + 0x60))
        else:
            out.append(ch)
    return "".join(out)


def strip_to_kata_choon(s):
    """Keep only katakana and the long-vowel mark (ァ-ヴ and ー), matching smoke.py."""
    s = unicodedata.normalize("NFKC", s or "")
    s = to_katakana(s)
    return "".join(ch for ch in s if ("ァ" <= ch <= "ヴ") or ch == "ー")


def kanaize_openjtalk(texts, python_bin=None):
    """Convert texts with ~/kana pyopenjtalk.g2p(..., kana=True).

    pyopenjtalk prints warnings to stdout; only lines starting with '@@' count.
    Both references and hypotheses must go through this same function.
    """
    python_bin = python_bin or os.environ.get("ITAKO_OPENJTALK_PYTHON") or DEFAULT_OPENJTALK_PYTHON
    texts = list(texts)
    proc = subprocess.run(
        [python_bin, "-c", _OPENJTALK_SNIPPET],
        input=json.dumps(texts, ensure_ascii=False),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(
            f"pyopenjtalk kana conversion failed (exit {proc.returncode}) "
            f"with {python_bin}: {err[:400]}"
        )
    lines = [ln[len(OPENJTALK_LINE_MARK):] for ln in proc.stdout.splitlines() if ln.startswith(OPENJTALK_LINE_MARK)]
    if len(lines) != len(texts):
        raise RuntimeError(
            f"pyopenjtalk returned {len(lines)} marked lines for {len(texts)} texts; "
            "stdout may have been parsed incorrectly. "
            f"preview={proc.stdout[:200]!r}"
        )
    return lines


def normalize_kana_kakasi_or_fallback(text, kakasi=None, fallback_lexicon=None):
    """Legacy pykakasi / lexicon path (kept behind --kana-backend pykakasi)."""
    s = unicodedata.normalize("NFKC", text or "")
    if kakasi is not None:
        s = "".join(item.get("kana", item.get("orig", "")) for item in kakasi.convert(s))
    elif fallback_lexicon:
        for kj, kn in fallback_lexicon:
            s = s.replace(kj, kn)
    s = to_katakana(s)
    s = "".join(ch for ch in s if ("ァ" <= ch <= "ヶ") or ch == "ー")
    s = s.replace("ヲ", "オ").replace("ヂ", "ジ").replace("ヅ", "ズ").replace("ヴ", "ブ")
    a_heads = set("アカサタナハマヤラワガザダバパァャヮ")
    i_heads = set("イキシチニヒミリヰギジヂビピィ")
    u_heads = set("ウクスツヌフムユルグズヅブプゥュ")
    e_heads = set("エケセテネヘメレヱゲゼデベペェ")
    o_heads = set("オコソトノホモヨロヲゴゾドボポォョ")
    small_kana = set("ァィゥェォャュョヮ")

    def trailing_vowel(ch):
        if ch in a_heads:
            return "a"
        if ch in i_heads:
            return "i"
        if ch in u_heads:
            return "u"
        if ch in e_heads:
            return "e"
        if ch in o_heads:
            return "o"
        return None

    out = []
    prev_v = None
    n = len(s)
    for idx, ch in enumerate(s):
        nxt = s[idx + 1] if idx + 1 < n else ""
        is_standalone_vowel = nxt not in small_kana
        if ch == "ー":
            if out and out[-1] != "ー":
                out.append("ー")
            continue
        if is_standalone_vowel and (
            (ch == "ウ" and prev_v in ("o", "u"))
            or (ch == "オ" and prev_v == "o")
            or (ch == "ア" and prev_v == "a")
            or (ch == "エ" and prev_v == "e")
        ):
            if out and out[-1] != "ー":
                out.append("ー")
            continue
        out.append(ch)
        prev_v = trailing_vowel(ch)
    return "".join(out)


class KanaNormalizer:
    """Symmetric kana converter: the same backend is applied to ref and hyp."""

    def __init__(self, backend="openjtalk", openjtalk_python=None, kakasi=None, fallback_lexicon=None):
        if backend not in ("openjtalk", "pykakasi", "fallback"):
            raise ValueError(f"Unknown kana backend: {backend}")
        self.backend = backend
        self.openjtalk_python = openjtalk_python or DEFAULT_OPENJTALK_PYTHON
        self.kakasi = kakasi
        self.fallback_lexicon = fallback_lexicon or []

    def batch(self, texts):
        texts = list(texts)
        if self.backend == "openjtalk":
            return kanaize_openjtalk(texts, python_bin=self.openjtalk_python)
        return [
            normalize_kana_kakasi_or_fallback(
                t,
                kakasi=self.kakasi if self.backend == "pykakasi" else None,
                fallback_lexicon=self.fallback_lexicon,
            )
            for t in texts
        ]


def levenshtein_distance(a, b):
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * lb
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[lb]


def compute_cer_from_kana(ref_kanas, hyp_kanas, ref_raws=None, hyp_raws=None):
    """CER = sum(edits) / sum(len(ref_kana)) after both sides are already kana."""
    total_edits = 0
    total_chars = 0
    per_item = []
    for i, (rn, hn) in enumerate(zip(ref_kanas, hyp_kanas)):
        ed = levenshtein_distance(rn, hn)
        total_edits += ed
        total_chars += len(rn)
        per_item.append({
            "ref_raw": None if ref_raws is None else ref_raws[i],
            "ref_kana": rn,
            "hyp_raw": None if hyp_raws is None else hyp_raws[i],
            "hyp_kana": hn,
            "edits": ed,
            "cer": round(ed / max(1, len(rn)), 4),
        })
    overall = total_edits / max(1, total_chars)
    return round(overall, 4), per_item


def compute_cer(ref_texts, hyp_texts, normalizer):
    """Symmetrically kana-ize ref and hyp, then score CER."""
    ref_texts = list(ref_texts)
    hyp_texts = list(hyp_texts)
    kanas = normalizer.batch(ref_texts + hyp_texts)
    n = len(ref_texts)
    return compute_cer_from_kana(kanas[:n], kanas[n:], ref_raws=ref_texts, hyp_raws=hyp_texts)


def worse_cer_per_item(items_by_asr):
    """Official score = worse (higher CER) ASR on each item, then sum(edits)/sum(len).

    Taking max of the two overall CERs would let a model hide item-level failures
    that the other ASR caught. Per-item worse avoids that.
    """
    if not items_by_asr:
        return 0.0, []
    names = list(items_by_asr)
    n = len(items_by_asr[names[0]])
    if any(len(items_by_asr[nm]) != n for nm in names):
        raise ValueError("ASR item lists have different lengths")
    total_edits = 0
    total_chars = 0
    winners = []
    for i in range(n):
        worst_name = max(names, key=lambda nm: (items_by_asr[nm][i]["cer"], items_by_asr[nm][i]["edits"]))
        it = items_by_asr[worst_name][i]
        total_edits += it["edits"]
        total_chars += len(it["ref_kana"])
        winners.append(worst_name)
    return round(total_edits / max(1, total_chars), 4), winners


def _multipart_wav_body(wav_path):
    boundary = "----ItakoAsrBoundary7f3c2a"
    filename = os.path.basename(wav_path)
    with open(wav_path, "rb") as f:
        data = f.read()
    pre = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode("utf-8")
    post = f"\r\n--{boundary}--\r\n".encode("ascii")
    return pre + data + post, boundary


def transcribe_openai_compatible(
    url,
    wav_path,
    timeout=DEFAULT_HTTP_TIMEOUT_SEC,
    retry_budget=DEFAULT_RETRY_BUDGET_SEC,
    sleeper=time.sleep,
    urlopen=urllib.request.urlopen,
    prefer_path=True,
):
    """POST /v1/audio/transcriptions as JSON {path} or multipart file.

    Returns the parsed JSON body (expects keys such as text, sec, load_sec, peak_gb).
    """
    abs_p = os.path.abspath(wav_path)
    last_http_err = None
    if prefer_path:
        req = urllib.request.Request(
            url,
            data=json.dumps({"path": abs_p}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            raw, _code = request_with_retry(
                req, timeout=timeout, retry_budget=retry_budget, sleeper=sleeper, urlopen=urlopen
            )
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_http_err = exc
            if exc.code not in (400, 404, 415, 422):
                raise

    body, boundary = _multipart_wav_body(abs_p)
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        raw, _code = request_with_retry(
            req, timeout=timeout, retry_budget=retry_budget, sleeper=sleeper, urlopen=urlopen
        )
        return json.loads(raw.decode("utf-8"))
    except Exception:
        if last_http_err is not None:
            raise last_http_err
        raise


def transcribe_legacy_batch(
    url,
    wav_paths,
    timeout=DEFAULT_HTTP_TIMEOUT_SEC,
    retry_budget=DEFAULT_RETRY_BUDGET_SEC,
    sleeper=time.sleep,
    urlopen=urllib.request.urlopen,
):
    """Old itako_asr_server.py protocol: POST {wav_paths: [...]} -> {name, texts}."""
    req = urllib.request.Request(
        url,
        data=json.dumps({"wav_paths": [os.path.abspath(p) for p in wav_paths]}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    raw, _code = request_with_retry(
        req, timeout=timeout, retry_budget=retry_budget, sleeper=sleeper, urlopen=urlopen
    )
    return json.loads(raw.decode("utf-8"))


def is_openai_transcriptions_url(spec):
    return "/v1/audio/transcriptions" in (spec or "")


def run_http_asr(
    spec,
    wav_paths,
    timeout=DEFAULT_HTTP_TIMEOUT_SEC,
    retry_budget=DEFAULT_RETRY_BUDGET_SEC,
    sleeper=time.sleep,
    urlopen=urllib.request.urlopen,
):
    """Return (asr_name, list_of_texts) for one HTTP ASR endpoint."""
    if is_openai_transcriptions_url(spec):
        texts = []
        name = spec
        for wp in wav_paths:
            data = transcribe_openai_compatible(
                spec,
                wp,
                timeout=timeout,
                retry_budget=retry_budget,
                sleeper=sleeper,
                urlopen=urlopen,
            )
            texts.append((data.get("text") or "").strip())
            name = data.get("model") or data.get("name") or spec
        return name, texts

    data = transcribe_legacy_batch(
        spec, wav_paths, timeout=timeout, retry_budget=retry_budget, sleeper=sleeper, urlopen=urlopen
    )
    return data.get("name") or spec, data["texts"]
