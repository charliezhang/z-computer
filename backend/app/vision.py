"""Platform-side vision primitive: one fast multimodal call per request. The image is never stored."""
import base64
import re

from anthropic import AsyncAnthropic

MODEL = "claude-haiku-4-5"  # lightest current model: ~1-2 s for a short caption
MAX_IMAGE_BYTES = 3 * 1024 * 1024
_DATA_URL = re.compile(r"^data:(image/(?:jpeg|png|webp|gif));base64,(.+)$", re.S)
_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic()
    return _client


async def react_to_image(prompt: str, image_data_url: str, max_tokens: int = 300) -> str:
    m = _DATA_URL.match(image_data_url or "")
    if not m:
        raise ValueError("image must be a data:image/jpeg|png|webp|gif;base64 URL")
    media_type, data = m.group(1), m.group(2)
    if len(data) * 3 // 4 > MAX_IMAGE_BYTES:
        raise ValueError("image too large (max 3 MB)")
    base64.b64decode(data[:64] + "=" * (-len(data[:64]) % 4))  # cheap sanity check on the encoding
    resp = await _get_client().messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
            {"type": "text", "text": prompt},
        ]}],
    )
    text = "".join(block.text for block in resp.content if block.type == "text").strip()
    return _FENCE.sub("", text).strip()


# Small models sometimes wrap JSON in ```json fences even when told not to; apps parse the text, so strip them.
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")
