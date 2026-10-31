"""NLLB-200 over HTTP, in the FLORES-200 codes the model itself speaks.

The surface is deliberately not the LibreTranslate API. NLLB names languages
by FLORES-200 code and needs an explicit source language on every call, so a
LibreTranslate shape would have to invent an ISO mapping and a detector the
model does not have. The translation gateway owns that mapping instead and
reaches this server with the codes the tokenizer already carries.
"""

# nocheck: mirrored-unit-test - the server needs torch, transformers and fastapi, which only this role's image installs; the ISO to FLORES boundary it is called across is covered by the gateway's test_flores and test_engines

from __future__ import annotations

import asyncio
import os
import threading

import torch
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

UNPROCESSABLE = 422

MODEL = os.environ["NLLB_MODEL"]
DEVICE = os.environ["NLLB_DEVICE"]
THREADS = int(os.environ["NLLB_THREADS"])
BEAMS = int(os.environ["NLLB_BEAMS"])
MAX_INPUT_TOKENS = int(os.environ["NLLB_MAX_INPUT_TOKENS"])
MAX_OUTPUT_TOKENS = int(os.environ["NLLB_MAX_OUTPUT_TOKENS"])

torch.set_num_threads(THREADS)

tokenizer = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForSeq2SeqLM.from_pretrained(MODEL).to(DEVICE).eval()

LANGUAGES = frozenset(
    token
    for token in tokenizer.additional_special_tokens
    if tokenizer.convert_tokens_to_ids(token) != tokenizer.unk_token_id
)

_generating = threading.Lock()

app = FastAPI(title="Infinito.Nexus NLLB-200 Engine")


def render(source: str, target: str, text: str) -> str:
    """Return the model's rendering of *text*.

    Args:
        source: FLORES-200 code of the source language.
        target: FLORES-200 code of the target language.
        text: the string to translate.

    The decode happens under a lock because the process already spends every
    core it was given inside one generate call; letting a second request in
    oversubscribes the threads rather than adding throughput.
    """
    with _generating:
        tokenizer.src_lang = source
        encoded = tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=MAX_INPUT_TOKENS,
        ).to(DEVICE)
        with torch.inference_mode():
            generated = model.generate(
                **encoded,
                forced_bos_token_id=tokenizer.convert_tokens_to_ids(target),
                max_new_tokens=MAX_OUTPUT_TOKENS,
                num_beams=BEAMS,
            )
        return tokenizer.batch_decode(generated, skip_special_tokens=True)[0].strip()


@app.get("/languages")
async def languages() -> JSONResponse:
    """The FLORES-200 codes the loaded checkpoint carries.

    This is also the readiness probe: the route exists only once the weights
    are in memory, because uvicorn binds the port after this module imported.
    """
    return JSONResponse(content={"languages": sorted(LANGUAGES)})


@app.post("/translate")
async def translate(request: Request) -> JSONResponse:
    """Translate one string between two FLORES-200 languages."""
    body = await request.json()
    source = body.get("source")
    target = body.get("target")
    text = body.get("text")
    if not source or not target or not text:
        return JSONResponse(
            status_code=UNPROCESSABLE,
            content={"error": "'source', 'target' and 'text' are required"},
        )
    unknown = sorted({source, target} - LANGUAGES)
    if unknown:
        return JSONResponse(
            status_code=UNPROCESSABLE,
            content={"error": f"{MODEL} carries no language {', '.join(unknown)}"},
        )
    answer = await asyncio.to_thread(render, source, target, text)
    return JSONResponse(content={"translation": answer})
