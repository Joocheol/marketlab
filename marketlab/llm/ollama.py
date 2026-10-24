"""Ollama 로컬 전송계층 (설계안 §6의 LiveAdapter용 transport).

유료 API 없이 매 틱 LLM 판단을 가능하게 하는 경로: localhost의 Ollama 서버
(기본 127.0.0.1:11434)로 공개 가중치 모델을 호출한다. 어댑터 계약
(async callable(req, model, params) -> {text, usage, finish_reason})을 그대로
따르므로 호출 로그·재생·예산 가드가 전부 동일하게 작동한다.

재현성: options에 temperature·seed를 고정하면 같은 프롬프트에 같은 응답을
받을 수 있다(모델·Ollama 버전 고정 전제). 호출 로그가 있으면 그마저 불필요.
표준 라이브러리만 사용(urllib), 블로킹 호출은 asyncio.to_thread로 감싼다.
"""

import asyncio
import json
import urllib.request

BASE_URL = "http://127.0.0.1:11434"


def _post(url, payload, timeout):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


class OllamaTransport:
    def __init__(self, base_url=BASE_URL, request_timeout=120.0):
        self.base_url = base_url
        self.request_timeout = request_timeout

    async def __call__(self, req, model, params):
        # 호출별 결정적 시드: 같은 call_id·프롬프트는 같은 응답(모델·버전 고정 전제)
        import hashlib
        seed = params.get("seed")
        if seed is None:
            seed = int(hashlib.sha256(req["call_id"].encode()).hexdigest()[:8], 16)
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": req["prompt"]}],
            "stream": False,
            "options": {
                "temperature": params.get("temperature", 0.7),
                "seed": seed,
                "num_predict": params.get("max_tokens", 120),
            },
        }
        if params.get("format") is not None:
            payload["format"] = params["format"]   # 구조화 출력: JSON 스키마 강제
        data = await asyncio.to_thread(
            _post, f"{self.base_url}/api/chat", payload, self.request_timeout)
        return {
            "text": data["message"]["content"],
            "usage": {
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
                "total_tokens": (data.get("prompt_eval_count", 0)
                                 + data.get("eval_count", 0)),
            },
            "finish_reason": data.get("done_reason", "stop"),
        }


def server_alive(base_url=BASE_URL):
    try:
        with urllib.request.urlopen(base_url + "/api/tags", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False
