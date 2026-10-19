from __future__ import annotations

import copy
from typing import Any

from hll.tools.api import encode_image


def init_action_chat() -> list[list[Any]]:
    system_prompt = (
        "You are a helpful AI mobile phone operating assistant. You need to help me "
        "operate the phone to complete the user's instruction."
    )
    return [["system", [{"type": "text", "text": system_prompt}]]]


def add_response(
    role: str,
    prompt: str,
    chat_history: list[list[Any]],
    image: str | None = None,
) -> list[list[Any]]:
    new_chat_history = copy.deepcopy(chat_history)
    if image:
        base64_image = encode_image(image)
        content = [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
            },
        ]
    else:
        content = [{"type": "text", "text": prompt}]
    new_chat_history.append([role, content])
    return new_chat_history
