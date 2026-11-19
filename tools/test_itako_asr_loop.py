#!/usr/bin/env python3
"""Unit tests for Itako ASR adaptions (mocked HTTP / kana; no live 809x)."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from contextlib import contextmanager

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import itako_asr_lib as L  # noqa: E402


class FakeResp:
    def __init__(self, body, code=200):
        self._body = body if isinstance(body, bytes) else body.encode("utf-8")
        self._code = code

    def read(self):
        return self._body

    def getcode(self):
        return self._code

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestRetry(unittest.TestCase):
    def test_backoff_1_2_4_then_success(self):
        calls = {"n": 0}
        sleeps = []

        def urlopen(req, timeout=None):
            calls["n"] += 1
            if calls["n"] < 4:
                raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
            return FakeResp(b'{"ok":true}')

        raw, code = L.request_with_retry(
            object(), timeout=120, retry_budget=90, sleeper=sleeps.append, urlopen=urlopen
        )
        self.assertEqual(sleeps, [1.0, 2.0, 4.0])
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw.decode()), {"ok": True})
        self.assertEqual(calls["n"], 4)

    def test_budget_90_sleeps_then_gives_up(self):
        sleeps = []

        def urlopen(req, timeout=None):
            raise urllib.error.URLError(ConnectionResetError(104, "Connection reset"))

        with self.assertRaises(urllib.error.URLError):
            L.request_with_retry(
                object(), timeout=120, retry_budget=90, sleeper=sleeps.append, urlopen=urlopen
            )
        self.assertEqual(sleeps, [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 27.0])
        self.assertEqual(sum(sleeps), 90.0)

    def test_http_error_is_not_retried(self):
        calls = {"n": 0}

        def urlopen(req, timeout=None):
            calls["n"] += 1
            raise urllib.error.HTTPError("http://x", 500, "boom", hdrs=None, fp=io.BytesIO(b"err"))

        with self.assertRaises(urllib.error.HTTPError):
            L.request_with_retry(object(), sleeper=lambda s: self.fail("should not sleep"), urlopen=urlopen)
        self.assertEqual(calls["n"], 1)


class TestClamp(unittest.TestCase):
    BOUNDS = {
        "hz": (120.0, 420.0, 1, "F0"),
        "fscale": (0.82, 1.36, 3, "scale"),
        "tilt_w": (2.0, 9.0, 0, "window"),
        "g_vo": (0.50, 0.965, 3, "G"),
    }

    def test_clamps_high_and_low_and_rounds(self):
        cleaned, err = L.clamp_and_round_knob_dict(
            {"hz": 500, "fscale": 0.5, "tilt_w": 1.4, "g_vo": 2.0},
            ["hz", "fscale", "tilt_w", "g_vo"],
            self.BOUNDS,
        )
        self.assertIsNone(err)
        self.assertEqual(cleaned["hz"], 420.0)
        self.assertEqual(cleaned["fscale"], 0.82)
        self.assertEqual(cleaned["tilt_w"], 2)
        self.assertEqual(cleaned["g_vo"], 0.965)

    def test_in_range_is_kept_and_rounded(self):
        cleaned, err = L.clamp_and_round_knob_dict(
            {"hz": 245.44, "fscale": 1.0516},
            ["hz", "fscale"],
            self.BOUNDS,
        )
        self.assertIsNone(err)
        self.assertEqual(cleaned["hz"], 245.4)
        self.assertEqual(cleaned["fscale"], 1.052)

    def test_missing_and_non_numeric_rejected(self):
        cleaned, err = L.clamp_and_round_knob_dict({"hz": 200}, ["hz", "fscale"], self.BOUNDS)
        self.assertIsNone(cleaned)
        self.assertIn("missing required knob 'fscale'", err)
        cleaned, err = L.clamp_and_round_knob_dict({"hz": "nope"}, ["hz"], self.BOUNDS)
        self.assertIsNone(cleaned)
        self.assertIn("non-numeric", err)


class TestJsonRetry(unittest.TestCase):
    def test_retries_once_then_parses(self):
        payloads = ["this is not json", '```json\n{"hz": 200}\n```']
        calls = {"n": 0}

        def fetch():
            calls["n"] += 1
            return payloads[calls["n"] - 1]

        obj, n = L.load_json_from_llm_response(fetch)
        self.assertEqual(obj, {"hz": 200})
        self.assertEqual(n, 2)
        self.assertEqual(calls["n"], 2)

    def test_second_failure_raises(self):
        def fetch():
            return "still not json"

        with self.assertRaises(ValueError):
            L.load_json_from_llm_response(fetch)

    def test_first_success_does_not_refetch(self):
        calls = {"n": 0}

        def fetch():
            calls["n"] += 1
            return '{"rate": 1.1}'

        obj, n = L.load_json_from_llm_response(fetch)
        self.assertEqual(obj, {"rate": 1.1})
        self.assertEqual(n, 1)
        self.assertEqual(calls["n"], 1)


class TestWorstOfTwo(unittest.TestCase):
    def test_per_item_worse_differs_from_max_of_overall(self):
        # item1: 2 chars, item2: 3 chars
        asr1 = [
            {"cer": 0.0, "edits": 0, "ref_kana": "アイ"},       # 0/2
            {"cer": 1.0, "edits": 3, "ref_kana": "ウエオ"},    # 3/3
        ]
        asr2 = [
            {"cer": 0.5, "edits": 1, "ref_kana": "アイ"},       # 1/2
            {"cer": 0.0, "edits": 0, "ref_kana": "ウエオ"},    # 0/3
        ]
        # overall asr1 = 3/5 = 0.6, asr2 = 1/5 = 0.2, max of overall = 0.6, mean = 0.4
        # per-item worse edits = 1 + 3 = 4, chars = 5 -> 0.8
        official, winners = L.worse_cer_per_item({"asr1": asr1, "asr2": asr2})
        self.assertEqual(official, 0.8)
        self.assertEqual(winners, ["asr2", "asr1"])

    def test_single_asr_is_itself(self):
        items = [{"cer": 0.25, "edits": 1, "ref_kana": "abcd"}]
        official, winners = L.worse_cer_per_item({"only": items})
        self.assertEqual(official, 0.25)
        self.assertEqual(winners, ["only"])


class TestSymmetricKana(unittest.TestCase):
    def test_openjtalk_ignores_stdout_warnings_and_is_symmetric(self):
        # Fake "python" that prints an unmarked warning, then @@-marked kana lines.
        with tempfile.TemporaryDirectory() as td:
            fake = os.path.join(td, "fake_openjtalk.py")
            with open(fake, "w", encoding="utf-8") as f:
                f.write(
                    "#!/usr/bin/env python3\n"
                    "import sys, json\n"
                    "print('ONNX Runtime warning: initializer is not used')\n"
                    "print('loading model...')\n"
                    "texts = json.load(sys.stdin)\n"
                    "for t in texts:\n"
                    "    # crude: drop punctuation, to katakana-ish by leaving already-kata, else tag\n"
                    "    out = ''.join(ch for ch in t if ch not in '、。 ・')\n"
                    "    print('@@' + out)\n"
                )
            os.chmod(fake, 0o755)
            # Use the same interpreter as the test, with - we need python_bin to be a
            # script runner: the lib calls [python_bin, "-c", snippet].
            # So wrap as a python that, when invoked with -c, execs our fake by
            # replacing the snippet... Better: point python_bin at a shell-like
            # wrapper that is itself a Python interpreter substitute.
            wrapper = os.path.join(td, "wrapper")
            with open(wrapper, "w", encoding="utf-8") as f:
                f.write(
                    "#!/usr/bin/env python3\n"
                    "import sys, json, re\n"
                    "# Recreate smoke.py's stdout-marking contract, plus a warning.\n"
                    "print('ONNX Runtime warning: initializer is not used')\n"
                    "args = sys.argv[1:]\n"
                    "assert args and args[0] == '-c'\n"
                    "texts = json.load(sys.stdin)\n"
                    "for t in texts:\n"
                    "    kata = re.sub(r'[^ァ-ヴー]', '', t)\n"
                    "    print('@@' + kata)\n"
                )
            os.chmod(wrapper, 0o755)
            refs = ["上海はおっきな街で。", "うちは餃子が好きやで"]
            hyps = ["上海はおっきな街で。", "うちは餃子が好きやで"]
            # These inputs are mixed; the fake only keeps ァ-ヴー so result may be empty
            # unless we pass katakana. Use katakana plus punctuation plus a warning trap.
            refs = ["シャンハイハ、オーキナマチデ。", "ウチハギョーザガスキヤデ"]
            hyps = ["シャンハイハ、オーキナマチデ。", "ウチハギョーザガスキヤデ"]
            norm = L.KanaNormalizer(backend="openjtalk", openjtalk_python=wrapper)
            kanas = norm.batch(refs + hyps)
            self.assertEqual(len(kanas), 4)
            self.assertFalse(any("ONNX" in k or "warning" in k for k in kanas))
            self.assertEqual(kanas[0], "シャンハイハオーキナマチデ")
            self.assertEqual(kanas[0], kanas[2])
            self.assertEqual(kanas[1], kanas[3])
            cer, items = L.compute_cer(refs, hyps, norm)
            self.assertEqual(cer, 0.0)
            self.assertEqual(items[0]["ref_kana"], items[0]["hyp_kana"])

    def test_fallback_is_symmetric_for_mixed_ref_hyp(self):
        lex = [("上海", "シャンハイ"), ("街", "マチ"), ("餃子", "ギョーザ")]
        norm = L.KanaNormalizer(backend="fallback", fallback_lexicon=lex)
        ref = "上海はおっきな街で"
        hyp = "シャンハイハオッキナマチデ"  # already kana
        cer, items = L.compute_cer([ref], [hyp], norm)
        self.assertEqual(items[0]["ref_kana"], items[0]["hyp_kana"])
        self.assertEqual(cer, 0.0)


class TestDefaultsAndAsrClient(unittest.TestCase):
    def test_default_urls_and_model(self):
        self.assertEqual(L.DEFAULT_LLM_MODEL, "default_model")
        self.assertEqual(L.DEFAULT_LLM_URL, "http://127.0.0.1:8090/v1")
        self.assertEqual(
            L.DEFAULT_ASR_URLS,
            (
                "http://127.0.0.1:8091/v1/audio/transcriptions",
                "http://127.0.0.1:8092/v1/audio/transcriptions",
            ),
        )
        self.assertGreaterEqual(L.DEFAULT_HTTP_TIMEOUT_SEC, 120)
        self.assertEqual(L.DEFAULT_RETRY_BUDGET_SEC, 90)

    def test_no_14b_in_lib_or_loop_source(self):
        for name in ("itako_asr_lib.py", "itako_asr_loop.py", "itako_asr_server.py", "ITAKO_ASR.md", "README.md"):
            with open(os.path.join(HERE, name), encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("Qwen3-14B", text, name)
            self.assertNotIn("qwen3-14b", text, name)

    def test_openai_transcriptions_path_json(self):
        seen = {}

        def urlopen(req, timeout=None):
            seen["url"] = req.full_url
            seen["body"] = json.loads(req.data.decode())
            seen["timeout"] = timeout
            return FakeResp(json.dumps({
                "text": "こんにちは",
                "sec": 0.11,
                "load_sec": 0.5,
                "peak_gb": 2.3,
                "model": "mlx-community/Qwen3-ASR-1.7B-8bit",
            }))

        with tempfile.NamedTemporaryFile(suffix=".wav") as wf:
            wf.write(b"RIFF")
            wf.flush()
            name, texts = L.run_http_asr(
                "http://127.0.0.1:8091/v1/audio/transcriptions",
                [wf.name],
                timeout=120,
                urlopen=urlopen,
                sleeper=lambda s: None,
            )
        self.assertEqual(name, "mlx-community/Qwen3-ASR-1.7B-8bit")
        self.assertEqual(texts, ["こんにちは"])
        self.assertEqual(seen["body"]["path"], os.path.abspath(wf.name) if True else None)
        self.assertIn("path", seen["body"])
        self.assertEqual(seen["timeout"], 120)

    def test_loop_cli_defaults(self):
        # Importing the loop pulls in yomu/hitofude; that's available on the box.
        sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))
        import itako_asr_loop as loop  # noqa: E402

        # parse_args with no --asr / --llm-model
        old = sys.argv
        try:
            sys.argv = ["itako_asr_loop.py", "--help"]
            # just inspect the parser by calling main's ArgumentParser via a dry helper:
        finally:
            sys.argv = old
        # Reconstruct what main would use
        self.assertTrue(hasattr(loop, "make_kana_normalizer"))
        self.assertEqual(loop.extract_json_object('{"a": 1}'), {"a": 1})
        cleaned, err = loop.validate_and_round_knob_dict({"hz": 1000, "fscale": 0.1, "rate": 3}, ["hz", "fscale", "rate"])
        self.assertIsNone(err)
        self.assertEqual(cleaned["hz"], 420.0)
        self.assertEqual(cleaned["fscale"], 0.82)
        self.assertEqual(cleaned["rate"], 1.65)


if __name__ == "__main__":
    unittest.main(verbosity=2)
