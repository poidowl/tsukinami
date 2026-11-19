#!/usr/bin/env python3
"""tools/itako_asr_server.py — 予備のローカル ASR HTTP サーバー

関亡婆 (M6) の本番 ASR は、すでに次のポートで動いている:
  8091 Qwen3-ASR-1.7B、8092 parakeet-tdt_ctc-0.6b-ja
  （起動・停止は ~/asr/start.sh / ~/asr/stop.sh。API は POST /v1/audio/transcriptions）

このスクリプトを 8091 や 8092 で立てないこと。既存のサーバーと衝突する。
イタコのループ (tools/itako_asr_loop.py) は、既定でその2本を直接呼ぶ。
8090 は Qwen3-30B-A3B の LLM 用なので、ここでも拒否する。

やむを得ず別マシンでこのサーバーを使う場合の例（ポートは 8094 以降。
8093 は关亡婆のオバケ wav 読み取り専用配信 obake_serve 用なので使わない）:
  python tools/itako_asr_server.py --port 8094 --backend mlx-whisper \
      --model mlx-community/whisper-large-v3-turbo --name mlx-large-v3-turbo
"""
import argparse
import json
import os
import resource
import sys
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer


def current_maxrss_mb():
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS returns bytes; Linux returns KiB
    return round(rss / (1024.0 * 1024.0) if sys.platform == "darwin" else rss / 1024.0, 1)


def make_transcriber(backend, model_spec):
    if backend == "mlx-whisper":
        import mlx_whisper  # type: ignore

        # Warm load on first call; deterministic greedy/zero-temp decoding, no cross-utterance context leak
        def _transcribe(wav_path):
            res = mlx_whisper.transcribe(
                wav_path,
                path_or_hf_repo=model_spec,
                language="ja",
                temperature=0.0,
                condition_on_previous_text=False,
            )
            return (res.get("text") or "").strip()

        return _transcribe

    if backend == "faster-whisper":
        from faster_whisper import WhisperModel  # type: ignore

        model = WhisperModel(model_spec, device="auto", compute_type="auto")

        def _transcribe(wav_path):
            segs, _ = model.transcribe(
                wav_path,
                language="ja",
                beam_size=5,
                temperature=0.0,
                condition_on_previous_text=False,
                vad_filter=False,
            )
            return "".join(s.text for s in segs).strip()

        return _transcribe

    if backend == "sherpa-sensevoice":
        import numpy as np  # type: ignore
        import sherpa_onnx  # type: ignore

        model_file = os.path.join(model_spec, "model.int8.onnx")
        if not os.path.exists(model_file):
            model_file = os.path.join(model_spec, "model.onnx")
        tokens_file = os.path.join(model_spec, "tokens.txt")
        rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=model_file,
            tokens=tokens_file,
            language="ja",
            use_itn=False,
            num_threads=4,
        )

        def _transcribe(wav_path):
            with wave.open(wav_path, "rb") as wf:
                sr = wf.getframerate()
                pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
            st = rec.create_stream()
            st.accept_waveform(sr, pcm)
            rec.decode_stream(st)
            return (st.result.text or "").strip()

        return _transcribe

    raise ValueError(f"Unknown backend: {backend}")


def main():
    ap = argparse.ArgumentParser(description="Itako local ASR HTTP server (must not use port 8090)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8094, help="HTTP port (default: 8094; 8090/8091/8092/8093 are reserved on 関亡婆)")
    ap.add_argument(
        "--backend",
        choices=("mlx-whisper", "faster-whisper", "sherpa-sensevoice"),
        default="mlx-whisper",
    )
    ap.add_argument("--model", default="mlx-community/whisper-large-v3-turbo", help="Model HF repo or directory")
    ap.add_argument("--name", default=None, help="ASR identifier recorded in JSONL")
    args = ap.parse_args()

    if args.port == 8090:
        print("ERROR: Port 8090 is reserved for the LLM (Qwen3-30B-A3B) on 関亡婆. Choose 8094 or later.", file=sys.stderr)
        sys.exit(2)
    if args.port == 8093:
        print("ERROR: Port 8093 is reserved for obake_serve (read-only オバケ wavs) on 関亡婆. Choose 8094 or later.", file=sys.stderr)
        sys.exit(2)
    if args.port in (8091, 8092):
        print(
            f"WARNING: Port {args.port} is already used on 関亡婆 "
            "(8091=Qwen3-ASR-1.7B, 8092=parakeet). Do not start a second server there.",
            file=sys.stderr,
        )

    asr_name = args.name or f"{args.backend}:{os.path.basename(args.model)}"
    print(f"[itako-asr] Initializing {asr_name} on http://{args.host}:{args.port} ...", flush=True)
    transcribe_fn = make_transcriber(args.backend, args.model)
    warmed = {"done": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *a):
            return

        def _send_json(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/health"):
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "name": asr_name,
                        "backend": args.backend,
                        "model": args.model,
                        "maxrss_mb": current_maxrss_mb(),
                    },
                )
            else:
                self._send_json(404, {"error": "not found"})

        def do_POST(self):
            if not self.path.startswith("/transcribe"):
                self._send_json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            wav_paths = payload.get("wav_paths") or []
            texts = []
            for wp in wav_paths:
                if not os.path.exists(wp):
                    self._send_json(400, {"error": f"wav not found: {wp}"})
                    return
                texts.append(transcribe_fn(wp))
            rss_mb = current_maxrss_mb()
            if not warmed["done"] and texts:
                warmed["done"] = True
                print(f"[itako-asr] First transcription complete | measured maxrss = {rss_mb} MB", flush=True)
            self._send_json(200, {"name": asr_name, "texts": texts, "maxrss_mb": rss_mb})

    srv = HTTPServer((args.host, args.port), Handler)
    print(
        f"[itako-asr] Ready: POST http://{args.host}:{args.port}/transcribe "
        f"({asr_name}, init maxrss={current_maxrss_mb()} MB)",
        flush=True,
    )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[itako-asr] Shutting down.")


if __name__ == "__main__":
    main()
