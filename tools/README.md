# tools/

イタコ（关亡婆 / M6 Mac mini）向けの ASR ループと照合ツール。

- 使い方と実行手順は [ITAKO_ASR.md](./ITAKO_ASR.md) を読む。
- ループの入口は `itako_asr_loop.py`。関亡婆で既に動いている 8090（LLM）・8091（Qwen3-ASR）・8092（parakeet）を既定で使う。`itako_asr_server.py` を 8091 で立てないこと。

## クレジット

既定 ASR のひとつ **parakeet-tdt_ctc-0.6b-ja**（NVIDIA、MLX 版 `mlx-community/parakeet-tdt_ctc-0.6b-ja`）は [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) です。公開物や配信でこの認識器を使うときはクレジットを残すこと。

- https://huggingface.co/nvidia/parakeet-tdt_ctc-0.6b-ja
- https://huggingface.co/mlx-community/parakeet-tdt_ctc-0.6b-ja
