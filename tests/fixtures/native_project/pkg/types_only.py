from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pkg._native import Tokenizer


def name(tokenizer: "Tokenizer") -> str:
    return str(tokenizer)
