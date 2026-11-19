"""Command-line interface for Tsukinami ASR (`python -m asr <subcommand>`)."""

from __future__ import annotations

import argparse
import json
import pickle
import struct
import sys
import time
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from asr.audio import load_wav
from asr.config import (
    VALID_DECODE_METHODS,
    VALID_MODEL_ARCHS,
    AudioConfig,
    DecodeConfig,
    ModelConfig,
    TrainConfig,
)
from asr.dataset import load_manifest
from asr.inference import ASREngine
from asr.metrics import (
    compute_cer,
    compute_mer,
    compute_rtf,
    compute_wer,
    confusion_pairs,
)
from asr.synth_data import (
    VALID_ENGINES,
    generate_dataset,
    synthesize_fast_kotoba,
    synthesize_tsukinami,
)
from asr.tokenizer import Tokenizer
from asr.train import train_asr

__all__ = ["build_parser", "main"]


def _resolve_manifest_audio_path(raw_audio_path: str, manifest_dir: Path) -> Path:
    path = Path(raw_audio_path)
    if path.is_absolute():
        return path
    rel_to_manifest = manifest_dir / path
    if rel_to_manifest.exists():
        return rel_to_manifest.resolve()
    if path.exists():
        return path.resolve()
    return rel_to_manifest


def _validate_positive_int(name: str, value: int) -> None:
    if value < 1:
        raise ValueError(f"--{name} must be >= 1, got {value}")


def _evaluate_manifest(
    engine: ASREngine,
    manifest_path: Path,
    decode_cfg: DecodeConfig,
) -> dict[str, Any]:
    records = load_manifest(manifest_path)
    if not records:
        raise ValueError(f"Manifest contains no utterances: {manifest_path}")

    manifest_dir = manifest_path.parent
    refs: list[str] = []
    hyps: list[str] = []
    samples: list[dict[str, Any]] = []
    total_audio_sec = 0.0
    total_infer_sec = 0.0

    for rec in records:
        audio_path = _resolve_manifest_audio_path(str(rec["audio_path"]), manifest_dir)
        wav, sr = load_wav(audio_path, target_sr=engine.audio_cfg.sample_rate)
        t0 = time.perf_counter()
        res = engine.transcribe(wav, sr=sr, decode_cfg=decode_cfg)
        elapsed = time.perf_counter() - t0

        ref = str(rec["text"])
        hyp = str(res["text"])
        refs.append(ref)
        hyps.append(hyp)
        total_audio_sec += float(res["duration_sec"])
        total_infer_sec += elapsed
        samples.append(
            {
                "audio_path": str(audio_path),
                "ref": ref,
                "hyp": hyp,
                "rtf": float(res["rtf"]),
                "duration_sec": float(res["duration_sec"]),
            }
        )

    cer_details = compute_cer(refs, hyps)
    mer_details = compute_mer(refs, hyps)
    wer_details = compute_wer(refs, hyps)
    confusions = confusion_pairs(refs, hyps, top_k=10)
    mean_rtf = float(compute_rtf(total_infer_sec, total_audio_sec))

    return {
        "manifest": str(manifest_path),
        "num_utterances": len(records),
        "decode_config": decode_cfg.to_dict(),
        "cer": float(cer_details["cer"]),
        "mer": float(mer_details["mer"]),
        "wer": float(wer_details["wer"]),
        "cer_details": cer_details,
        "mer_details": mer_details,
        "wer_details": wer_details,
        "mean_rtf": mean_rtf,
        "rtf": mean_rtf,
        "total_audio_sec": float(total_audio_sec),
        "confusion_pairs": [[r, h, int(c)] for r, h, c in confusions],
        "samples": samples,
    }


def _cmd_demo(args: argparse.Namespace) -> int:
    _validate_positive_int("epochs", args.epochs)
    _validate_positive_int("num-train", args.num_train)
    _validate_positive_int("num-val", args.num_val)

    out_dir = Path(args.out_dir)
    data_dir = out_dir / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"[1/4] Generating synthetic Japanese dataset "
        f"(train={args.num_train}, val={args.num_val}, engine=fast, seed={args.seed})..."
    )
    manifests = generate_dataset(
        data_dir,
        num_train=args.num_train,
        num_val=args.num_val,
        engine="fast",
        seed=args.seed,
    )

    audio_cfg = AudioConfig()
    model_cfg = ModelConfig(
        arch=args.arch,
        n_mels=audio_cfg.n_mels,
        hidden_size=128,
        num_layers=2,
    )
    train_cfg = TrainConfig(
        epochs=args.epochs,
        batch_size=min(16, max(1, args.num_train)),
        lr=3e-3,
        seed=args.seed,
        checkpoint_dir=str(out_dir),
    )
    tokenizer = Tokenizer("kana")

    print(
        f"[2/4] Training {args.arch} acoustic model for {args.epochs} epoch(s) on CPU..."
    )
    summary = train_asr(
        manifests["train"],
        manifests["val"],
        audio_cfg=audio_cfg,
        model_cfg=model_cfg,
        train_cfg=train_cfg,
        tokenizer=tokenizer,
    )
    best_ckpt = Path(summary["best_checkpoint"])

    print(f"[3/4] Evaluating checkpoint {best_ckpt} on validation split...")
    engine = ASREngine.from_checkpoint(best_ckpt)
    decode_cfg = DecodeConfig(method="beam", beam_width=4)
    eval_res = _evaluate_manifest(engine, manifests["val"], decode_cfg)
    print(
        f"  Val CER: {eval_res['cer'] * 100:.2f}% | "
        f"MER: {eval_res['mer'] * 100:.2f}% | "
        f"Mean RTF: {eval_res['mean_rtf']:.3f}"
    )
    if eval_res["confusion_pairs"]:
        top_conf = ", ".join(
            f"{r}->{h} ({c})" for r, h, c in eval_res["confusion_pairs"][:5]
        )
        print(f"  Top confusions: {top_conf}")

    sample_text = "オハヨウゴザイマス"
    print(f"[4/4] Live TTS -> ASR round-trip for: {sample_text}")
    wav, _moras = synthesize_fast_kotoba(
        sample_text,
        sr=engine.audio_cfg.sample_rate,
        seed=args.seed,
    )
    live_res = engine.transcribe(wav, sr=engine.audio_cfg.sample_rate, decode_cfg=decode_cfg)
    live_cer = compute_cer([sample_text], [live_res["text"]], normalize_kana=True)["cer"]
    print(f"  Reference : {sample_text}")
    print(f"  Predicted : {live_res['text']}")
    print(f"  CER       : {live_cer * 100:.2f}% | RTF: {live_res['rtf']:.3f}")
    print(f"  Checkpoint: {best_ckpt}")
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    _validate_positive_int("num-train", args.num_train)
    _validate_positive_int("num-val", args.num_val)

    manifests = generate_dataset(
        args.out_dir,
        num_train=args.num_train,
        num_val=args.num_val,
        engine=args.engine,
        seed=args.seed,
    )
    print(f"Generated dataset ({args.engine}) in {Path(args.out_dir).resolve()}")
    print(f"  train ({args.num_train}): {manifests['train']}")
    print(f"  val   ({args.num_val}): {manifests['val']}")
    return 0


def _cmd_train(args: argparse.Namespace) -> int:
    _validate_positive_int("epochs", args.epochs)
    _validate_positive_int("batch-size", args.batch_size)
    _validate_positive_int("hidden-size", args.hidden_size)
    _validate_positive_int("num-layers", args.num_layers)
    if args.lr <= 0.0:
        raise ValueError(f"--lr must be > 0, got {args.lr}")

    audio_cfg = AudioConfig()
    model_cfg = ModelConfig(
        arch=args.arch,
        n_mels=audio_cfg.n_mels,
        hidden_size=args.hidden_size,
        num_layers=args.num_layers,
    )
    train_cfg = TrainConfig(
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        seed=args.seed,
        use_spec_augment=not args.no_spec_augment,
        checkpoint_dir=str(args.out_dir),
    )
    tokenizer = Tokenizer("kana")

    summary = train_asr(
        args.train_manifest,
        args.val_manifest,
        audio_cfg=audio_cfg,
        model_cfg=model_cfg,
        train_cfg=train_cfg,
        tokenizer=tokenizer,
        resume_from=args.resume,
    )
    print(
        f"Training complete ({summary['epochs_completed']} epochs): "
        f"best_val_cer={summary['best_val_cer'] * 100:.2f}%, "
        f"final_val_loss={summary['final_val_loss']:.4f}"
    )
    print(f"  best checkpoint  : {summary['best_checkpoint']}")
    print(f"  latest checkpoint: {summary['latest_checkpoint']}")
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    _validate_positive_int("beam-width", args.beam_width)

    engine = ASREngine.from_checkpoint(args.checkpoint)
    decode_cfg = DecodeConfig(method=args.method, beam_width=args.beam_width)
    result = _evaluate_manifest(engine, Path(args.manifest), decode_cfg)
    result["checkpoint"] = str(args.checkpoint)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0

    print(f"Evaluation on {result['manifest']} ({result['num_utterances']} utterances)")
    print(
        f"  CER: {result['cer'] * 100:.2f}% "
        f"(S={result['cer_details']['substitutions']}, "
        f"D={result['cer_details']['deletions']}, "
        f"I={result['cer_details']['insertions']})"
    )
    print(
        f"  MER: {result['mer'] * 100:.2f}% | "
        f"WER: {result['wer'] * 100:.2f}% | "
        f"Mean RTF: {result['mean_rtf']:.3f}"
    )
    if result["confusion_pairs"]:
        top_conf = ", ".join(
            f"{r}->{h} ({c})" for r, h, c in result["confusion_pairs"][:10]
        )
        print(f"  Top confusions: {top_conf}")
    return 0


def _cmd_transcribe(args: argparse.Namespace) -> int:
    _validate_positive_int("beam-width", args.beam_width)

    engine = ASREngine.from_checkpoint(args.checkpoint)
    decode_cfg = DecodeConfig(method=args.method, beam_width=args.beam_width)

    if args.wav is not None:
        wav, sr = load_wav(args.wav, target_sr=engine.audio_cfg.sample_rate)
        res = engine.transcribe(wav, sr=sr, decode_cfg=decode_cfg)
        res["source"] = "wav"
        res["wav_path"] = str(args.wav)
    else:
        if not isinstance(args.tts, str) or not args.tts.strip():
            raise ValueError("--tts text must be a non-empty string")
        if args.engine == "tsukinami":
            wav, _moras = synthesize_tsukinami(
                args.tts,
                preset=args.preset,
                sr=engine.audio_cfg.sample_rate,
            )
        else:
            wav, _moras = synthesize_fast_kotoba(
                args.tts,
                sr=engine.audio_cfg.sample_rate,
            )
        if wav.size == 0 or len(_moras) == 0:
            raise ValueError(
                f"--tts text must contain at least one speakable kana mora, got {args.tts!r}"
            )
        res = engine.transcribe(wav, sr=engine.audio_cfg.sample_rate, decode_cfg=decode_cfg)
        cer_val = float(
            compute_cer([args.tts], [res["text"]], normalize_kana=True)["cer"]
        )
        res["source"] = "tts"
        res["tts_engine"] = args.engine
        res["preset"] = args.preset
        res["reference_text"] = str(args.tts)
        res["tts_text"] = str(args.tts)
        res["cer"] = cer_val

    if args.json:
        print(json.dumps(res, ensure_ascii=False, allow_nan=False))
        return 0

    if res["source"] == "tts":
        print(f"Reference : {res['reference_text']}")
        print(f"Predicted : {res['text']}")
        print(
            f"CER       : {res['cer'] * 100:.2f}% | "
            f"Duration: {res['duration_sec']:.2f}s | RTF: {res['rtf']:.3f}"
        )
    else:
        print(f"Predicted : {res['text']}")
        print(f"Duration  : {res['duration_sec']:.2f}s | RTF: {res['rtf']:.3f}")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    if args.port < 1 or args.port > 65535:
        raise ValueError(f"--port must be in 1..65535, got {args.port}")

    ckpt_path: str | None = args.checkpoint
    if ckpt_path is not None:
        p = Path(ckpt_path)
        if not p.exists():
            raise FileNotFoundError(f"Checkpoint not found: {p}")
        if p.is_dir():
            raise ValueError(f"Checkpoint path is a directory: {p}")

    try:
        from asr.server import create_app
    except ImportError as exc:
        raise ImportError(
            f"Web server module `asr.server` is not available: {exc}"
        ) from exc

    try:
        import uvicorn
    except ImportError as exc:
        raise ImportError(f"uvicorn is required to run `serve`: {exc}") from exc

    app = create_app(checkpoint_path=ckpt_path)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level ArgumentParser for `python -m asr`."""
    parser = argparse.ArgumentParser(
        prog="python -m asr",
        description="Tsukinami ASR — pure-NumPy DSP + PyTorch CPU Japanese speech recognition playground.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # demo
    p_demo = subparsers.add_parser(
        "demo",
        help="One-command CPU quickstart: generate data, train, evaluate, and run live TTS->ASR.",
    )
    p_demo.add_argument("--out-dir", default="demo_out", help="Output directory (default: demo_out).")
    p_demo.add_argument("--epochs", type=int, default=8, help="Training epochs (default: 8).")
    p_demo.add_argument("--num-train", type=int, default=60, help="Training utterances (default: 60).")
    p_demo.add_argument("--num-val", type=int, default=12, help="Validation utterances (default: 12).")
    p_demo.add_argument(
        "--arch",
        choices=VALID_MODEL_ARCHS,
        default="cnn_bigru",
        help="Acoustic model architecture (default: cnn_bigru).",
    )
    p_demo.add_argument("--seed", type=int, default=42, help="Random seed (default: 42).")
    p_demo.set_defaults(handler=_cmd_demo)

    # generate
    p_gen = subparsers.add_parser(
        "generate",
        help="Generate synthetic Japanese speech dataset and JSONL manifests.",
    )
    p_gen.add_argument("--out-dir", required=True, help="Output directory for WAVs and manifests.")
    p_gen.add_argument("--num-train", type=int, default=200, help="Number of training utterances (default: 200).")
    p_gen.add_argument("--num-val", type=int, default=40, help="Number of validation utterances (default: 40).")
    p_gen.add_argument(
        "--engine",
        choices=VALID_ENGINES,
        default="fast",
        help="Synthesis engine (default: fast).",
    )
    p_gen.add_argument("--seed", type=int, default=42, help="Random seed (default: 42).")
    p_gen.set_defaults(handler=_cmd_generate)

    # train
    p_train = subparsers.add_parser(
        "train",
        help="Train a CTC acoustic model from JSONL manifests.",
    )
    p_train.add_argument("--train-manifest", required=True, help="Path to train JSONL manifest.")
    p_train.add_argument("--val-manifest", required=True, help="Path to validation JSONL manifest.")
    p_train.add_argument("--out-dir", default="checkpoints", help="Checkpoint output directory (default: checkpoints).")
    p_train.add_argument(
        "--arch",
        choices=VALID_MODEL_ARCHS,
        default="cnn_bigru",
        help="Model architecture (default: cnn_bigru).",
    )
    p_train.add_argument("--epochs", type=int, default=20, help="Number of epochs (default: 20).")
    p_train.add_argument("--batch-size", type=int, default=16, help="Batch size (default: 16).")
    p_train.add_argument("--lr", type=float, default=3e-3, help="Learning rate (default: 3e-3).")
    p_train.add_argument("--seed", type=int, default=42, help="Random seed (default: 42).")
    p_train.add_argument("--resume", default=None, help="Optional checkpoint path to resume from.")
    p_train.add_argument("--hidden-size", type=int, default=192, help="Model hidden size (default: 192).")
    p_train.add_argument("--num-layers", type=int, default=2, help="Number of encoder layers (default: 2).")
    p_train.add_argument("--no-spec-augment", action="store_true", help="Disable SpecAugment during training.")
    p_train.set_defaults(handler=_cmd_train)

    # eval
    p_eval = subparsers.add_parser(
        "eval",
        help="Evaluate a trained checkpoint on a JSONL manifest.",
    )
    p_eval.add_argument("--checkpoint", required=True, help="Path to trained .pt checkpoint.")
    p_eval.add_argument("--manifest", required=True, help="Path to evaluation JSONL manifest.")
    p_eval.add_argument(
        "--method",
        choices=VALID_DECODE_METHODS,
        default="beam",
        help="Decoding method (default: beam).",
    )
    p_eval.add_argument("--beam-width", type=int, default=8, help="Beam width for beam search (default: 8).")
    p_eval.add_argument("--json", action="store_true", help="Output a single JSON object to stdout.")
    p_eval.set_defaults(handler=_cmd_eval)

    # transcribe
    p_tr = subparsers.add_parser(
        "transcribe",
        help="Transcribe a WAV file or a live synthesized Japanese TTS utterance.",
    )
    p_tr.add_argument("--checkpoint", required=True, help="Path to trained .pt checkpoint.")
    src_group = p_tr.add_mutually_exclusive_group(required=True)
    src_group.add_argument("--wav", default=None, help="Path to input WAV file.")
    src_group.add_argument("--tts", default=None, help="Japanese text to synthesize and transcribe.")
    p_tr.add_argument("--preset", default="default", help="Tsukinami TTS voice preset (default: default).")
    p_tr.add_argument(
        "--engine",
        choices=("fast", "tsukinami"),
        default="tsukinami",
        help="TTS synthesis engine for --tts (default: tsukinami).",
    )
    p_tr.add_argument(
        "--method",
        choices=VALID_DECODE_METHODS,
        default="beam",
        help="Decoding method (default: beam).",
    )
    p_tr.add_argument("--beam-width", type=int, default=8, help="Beam width for beam search (default: 8).")
    p_tr.add_argument("--json", action="store_true", help="Output a single JSON object to stdout.")
    p_tr.set_defaults(handler=_cmd_transcribe)

    # serve
    p_serve = subparsers.add_parser(
        "serve",
        help="Launch the interactive FastAPI + Canvas ASR Web Playground.",
    )
    p_serve.add_argument("--checkpoint", default=None, help="Path to trained .pt checkpoint.")
    p_serve.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1).")
    p_serve.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000).")
    p_serve.set_defaults(handler=_cmd_serve)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point returning a standard process exit code."""
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.handler(args))
    except (
        FileNotFoundError,
        ValueError,
        TypeError,
        KeyError,
        RuntimeError,
        OSError,
        ImportError,
        OverflowError,
        EOFError,
        pickle.PickleError,
        zipfile.BadZipFile,
        struct.error,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
