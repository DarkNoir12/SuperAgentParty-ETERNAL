from typing import Optional
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl

from py.load_files import sanitize_url

router = APIRouter(prefix="/api", tags=["extra"])

class EmbeddingDimsRequest(BaseModel):
    api_key: str
    base_url: Optional[HttpUrl] = None   # Uses official https://api.openai.com/v1 when left empty
    model: str

class EmbeddingDimsResponse(BaseModel):
    dims: int

@router.post("/embedding_dims", response_model=EmbeddingDimsResponse)
async def get_embedding_dims(req: EmbeddingDimsRequest):
    """
    Call the embeddings endpoint once with an arbitrary sentence and return the length of the returned vector as the dimension.
    Compatible with the OpenAI official API and any proxy with the same interface format.
    """
    url = sanitize_url(
        input_url=req.base_url, 
        default_base="https://api.openai.com/v1", 
        endpoint="/embeddings"
    )

    payload = {"model": req.model, "input": "test"}
    headers = {"Authorization": f"Bearer {req.api_key}"}

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.post(url, json=payload, headers=headers)
        except Exception as e:
            raise HTTPException(502, detail=f"Failed to call embeddings endpoint: {e}")

    if r.status_code != 200:
        raise HTTPException(
            status_code=r.status_code,
            detail=f"Upstream returned error: {r.text}"
        )

    try:
        vec = r.json()["data"][0]["embedding"]
    except (KeyError, IndexError):
        raise HTTPException(502, detail="Upstream returned malformed response, cannot parse embedding")

    return EmbeddingDimsResponse(dims=len(vec))