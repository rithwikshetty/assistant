from __future__ import annotations

from typing import Any, Dict, List

from openai import OpenAI

from ...config.settings import settings


_SYSTEM_PROMPT = (
    "If the information is unavailable, state that directly without proposing alternatives."
)


def _response_to_dict(response: Any) -> Dict[str, Any]:
    """Convert the OpenAI SDK response into a serializable dictionary."""
    if hasattr(response, "model_dump"):
        return response.model_dump()
    if hasattr(response, "to_dict"):
        return response.to_dict()  # type: ignore[return-value]
    if hasattr(response, "dict"):
        return response.dict()  # type: ignore[return-value]
    if isinstance(response, dict):
        return response
    raise TypeError("Unexpected response type from OpenAI Responses API")


def _extract_citations(response_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
    citations: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()

    for output_item in response_dict.get("output") or []:
        if not isinstance(output_item, dict) or output_item.get("type") != "message":
            continue
        for content_item in output_item.get("content") or []:
            if not isinstance(content_item, dict) or content_item.get("type") != "output_text":
                continue
            for annotation in content_item.get("annotations") or []:
                if not isinstance(annotation, dict) or annotation.get("type") != "url_citation":
                    continue
                url = annotation.get("url")
                if not isinstance(url, str) or not url.strip() or url in seen_urls:
                    continue
                seen_urls.add(url)
                citations.append(
                    {
                        "index": len(citations) + 1,
                        "url": url,
                        "title": annotation.get("title"),
                    }
                )
    return citations


def _extract_content(response_dict: Dict[str, Any]) -> str:
    text_segments: List[str] = []
    for output_item in response_dict.get("output") or []:
        if not isinstance(output_item, dict) or output_item.get("type") != "message":
            continue
        for content_item in output_item.get("content") or []:
            if not isinstance(content_item, dict) or content_item.get("type") != "output_text":
                continue
            text = content_item.get("text")
            if isinstance(text, str) and text.strip():
                text_segments.append(text.strip())
    return "\n\n".join(text_segments).strip()


def web_search(query: str, model: str = "gpt-4.1-mini") -> Dict[str, Any]:
    """Run an OpenAI web search and return structured content and citations."""
    api_key = settings.openai_api_key
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured")

    client = OpenAI(api_key=api_key)

    try:
        response = client.responses.create(
            model=model,
            instructions=_SYSTEM_PROMPT,
            input=query,
            tools=[
                {
                    "type": "web_search_preview",
                    "search_context_size": "medium",
                }
            ],
            max_output_tokens=900,
        )
    except Exception as exc:  # pragma: no cover - network errors raised upstream
        raise RuntimeError("OpenAI web search request failed") from exc

    response_dict = _response_to_dict(response)
    content = _extract_content(response_dict)
    if not content:
        raise RuntimeError("OpenAI web search response was missing content")

    return {
        "content": content,
        "citations": _extract_citations(response_dict),
    }
