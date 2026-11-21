"""オバケ台帳ループの共通: 8090 への「細切れ」問い合わせと、その間の 8090 の返りの見張り。

8090（mlx_lm.server）は 1 本ずつしか処理せん。長い生成（400 トークンで約 6 秒）の間に局の kome_henji（3 秒待ち）が来ると落ちる。
そこで 1 回の問い合わせを 48 トークン（約 0.8 秒）までに切り、間に GAP 秒あけて続きを頼む（/v1/completions に途中までの答えを足して送る）。
長い入力も、前から少しずつ送って prompt cache に載せてから（max_tokens=1）本番を頼む。"""
import json, time, threading, urllib.request
BASE = "http://127.0.0.1:8090/v1"
CHUNK, GAP, PREFILL_STEP = 48, 1.2, 500

def _post(path, body, timeout):
    return json.load(urllib.request.urlopen(urllib.request.Request(BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=timeout))

def probe(timeout=5):
    t0 = time.time()
    try:
        _post("/chat/completions", {"model": "default_model", "messages": [{"role": "user", "content": "一言"}], "max_tokens": 4}, timeout)
        return round(time.time() - t0, 3)
    except Exception:
        return None

PUNCT = set('"\',:{}[]、。！？「」 \n')
def trim(out):
    """尻尾を少し削る。語の途中で切るとトークンの切れ目がずれて変な続きになる（"patter" 事件）ので、
    最後の記号の並びの手前（＝たいていトークンの切れ目）まで戻す。近くに無ければ 1 字。"""
    i = len(out) - 1
    while i >= 0 and out[i] not in PUNCT and len(out) - i < 16: i -= 1
    if i < 0 or out[i] not in PUNCT: return out[:-1]
    while i > 0 and out[i - 1] in PUNCT: i -= 1
    return out[:i] if i > 0 else out[:-1]

def template(system, user):   # Qwen3 Instruct 2507 の chat 形
    return f"<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n"

def gen(system, user, max_total=400, temperature=0.8, watch=False):
    # watch=True は測る時だけ（見張りの問い合わせが prompt cache の 2 枠を食って、こっちの続きが cache 外れになるため）
    prompt = template(system, user)
    lat, stop = [], threading.Event()
    def w():
        while not stop.wait(1.5): lat.append(probe(timeout=8))
    th = threading.Thread(target=w, daemon=True)
    if watch: th.start()
    reqs, out, ntok, t0 = [], "", 0, time.time()
    try:
        for cut in range(PREFILL_STEP * 2, len(prompt), PREFILL_STEP):   # 長い入力は前から少しずつ cache へ
            t = time.time(); _post("/completions", {"model": "default_model", "prompt": prompt[:cut], "max_tokens": 1}, 60); reqs.append(round(time.time() - t, 2)); time.sleep(GAP)
        while ntok < max_total:
            t = time.time()
            if out: out = trim(out)   # 前回の答えは丸ごと cache に載っとる → 入力 0 トークンになると mlx_lm が落ちるので、尻尾を言い直させる
            r = _post("/completions", {"model": "default_model", "prompt": prompt + out, "max_tokens": CHUNK, "temperature": temperature, "top_p": 0.95}, 60)
            reqs.append(round(time.time() - t, 2))
            c = r["choices"][0]; out += c["text"]; ntok += (r.get("usage") or {}).get("completion_tokens", CHUNK)
            if c.get("finish_reason") == "stop" or "<|im_end|>" in out: break
            time.sleep(GAP if reqs[-1] < 1.2 else GAP * 3)   # cache が外れて重かった直後は、局の番を長めに空ける
    finally:
        stop.set(); th.join(timeout=10) if watch else None
    ok = [x for x in lat if x is not None]
    meta = {"sec": round(time.time() - t0, 1), "requests": len(reqs), "req_max_sec": max(reqs) if reqs else None, "tokens": ntok,
            "probe_during": {"n": len(lat), "fail": len(lat) - len(ok), "max": max(ok) if ok else None, "over3s": sum(1 for x in ok if x > 3) + len(lat) - len(ok)}}
    return out.split("<|im_end|>")[0], meta
