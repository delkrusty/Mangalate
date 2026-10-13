"""Real upstream + OpenAI SDK contract, entirely against a local fake provider.

No user credential, external API request or paid call is made.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class Provider(BaseHTTPRequestHandler):
    content = "<|1|>Olá, mundo!\n<|2|>Bom dia!"
    finish_reason = "stop"
    calls = 0

    def log_message(self, *args):
        pass

    def do_POST(self):
        assert self.path == "/v1/chat/completions"
        assert self.headers["Authorization"] == "Bearer mangalate-contract-only"
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert body["model"] == "contract-model"
        assert body["max_tokens"] == 4096
        assert "professional manga translator" in body["messages"][0]["content"].lower()
        type(self).calls += 1
        data = json.dumps({
            "id": "test", "object": "chat.completion", "created": 1, "model": "contract-model",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": self.content},
                         "finish_reason": self.finish_reason}],
            # Deliberately no usage: allowed by compatible provider contracts.
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


async def test():
    from engine_compat import apply_compatibility, find_panels
    apply_compatibility()
    import numpy as np
    from PIL import Image, ImageDraw
    page = Image.new("RGB", (900, 1200), "white")
    draw = ImageDraw.Draw(page)
    for rectangle in ((30, 30, 435, 570), (465, 30, 870, 570),
                      (30, 600, 435, 1170), (465, 600, 870, 1170)):
        draw.rectangle(rectangle, outline="black", width=5)
    panels = find_panels(np.array(page))
    assert len(panels) == 4, panels
    assert panels[0][0] > panels[1][0] and panels[2][0] > panels[3][0], panels
    assert panels[0][1] < panels[2][1], panels
    print("Actual four-panel detection with RTL ordering PASSED.")
    from manga_translator.translators.custom_openai import CustomOpenAiTranslator
    from manga_translator.config import TranslatorConfig
    translator = CustomOpenAiTranslator()
    translator.parse_args(TranslatorConfig(
        translator="custom_openai", target_lang="PTB",
        gpt_config=str(ROOT / "profiles/scan-prompt.yaml"),
    ))
    try:
        result = await translator.translate("ENG", "PTB", ["Hello world!", "Good morning!"])
        assert result == ["Olá, mundo!", "Bom dia!"], result
        Provider.finish_reason = "length"
        try:
            await translator.translate("ENG", "PTB", ["Hello world!", "Good morning!"])
        except ValueError:
            pass
        else:
            raise AssertionError("Truncated response was accepted")
        Provider.finish_reason = "stop"
        Provider.content = "<|1|>Olá!<|1|>Duplicado!"
        try:
            await translator.translate("ENG", "PTB", ["Hello world!", "Good morning!"])
        except ValueError:
            pass
        else:
            raise AssertionError("Duplicate marker was accepted")
        assert Provider.calls == 3, Provider.calls
        print("Actual BYOK engine + SDK + scan prompt + local HTTP contract PASSED; no paid API calls.")
    finally:
        await translator.client.close()


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ["CUSTOM_OPENAI_API_KEY"] = "mangalate-contract-only"
    os.environ["CUSTOM_OPENAI_API_BASE"] = f"http://127.0.0.1:{server.server_port}/v1"
    os.environ["CUSTOM_OPENAI_MODEL"] = "contract-model"
    try:
        asyncio.run(test())
    finally:
        server.shutdown()
        server.server_close()
