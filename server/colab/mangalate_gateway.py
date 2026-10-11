"""
Gateway do Mangalate para o Google Colab.

Exige o cabeçalho X-Mangalate-Key e repassa as requisições para o
manga-image-translator rodando em 127.0.0.1:8001.

Uso: MANGALATE_KEY=senha python mangalate_gateway.py  (escuta na porta 5003)
"""

import os

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response

KEY = os.environ.get("MANGALATE_KEY", "")
UPSTREAM = os.environ.get("MANGALATE_UPSTREAM", "http://127.0.0.1:8001")

app = FastAPI(title="Mangalate gateway")
client = httpx.AsyncClient(base_url=UPSTREAM, timeout=httpx.Timeout(480.0, connect=20.0))


@app.api_route("/{path:path}", methods=["GET", "POST"])
async def proxy(path: str, request: Request) -> Response:
    if KEY and request.headers.get("x-mangalate-key") != KEY:
        return Response("Chave do Mangalate inválida", status_code=401)
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length", "x-mangalate-key", "authorization")
    }
    upstream = await client.request(
        request.method,
        "/" + path,
        content=await request.body(),
        headers=headers,
        params=request.query_params,
    )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5003, log_level="warning")
