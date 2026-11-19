# tools/

- `build_x_player.mjs`：X Player Card 用ページの組み立て（kusanagi 本体）。
- イタコ（关亡婆 / M6 Mac mini）向けの ASR ループ：入口は `itako_asr_loop.py`、合成は `kusanagi_yomu.py` 経由で `node yomu.mjs`。使い方は [ITAKO_ASR.md](./ITAKO_ASR.md)。
  关亡婆で既に動いている 8090（LLM）・8091（Qwen3-ASR）・8092（parakeet）を既定で使う。`itako_asr_server.py` を 8091/8092/8093 で立てないこと（予備の既定は 8094）。

## クレジット

既定 ASR のひとつ **parakeet-tdt_ctc-0.6b-ja**（NVIDIA、MLX 版 `mlx-community/parakeet-tdt_ctc-0.6b-ja`）は [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) です。公開物や配信でこの認識器を使うときはクレジットを残すこと。

- https://huggingface.co/nvidia/parakeet-tdt_ctc-0.6b-ja
- https://huggingface.co/mlx-community/parakeet-tdt_ctc-0.6b-ja
