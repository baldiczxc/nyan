import logging
import time
from dataclasses import dataclass
from typing import Optional, Sequence, List, Dict, Any
from multiprocessing.pool import ThreadPool

from dotenv import load_dotenv
from openai import OpenAI, RateLimitError
import copy
import os
import re

load_dotenv()


@dataclass
class OpenAIDecodingArguments:
    max_tokens: int = 8000
    temperature: float = 0.0
    top_p: float = 0.95
    n: int = 1
    stream: bool = False
    stop: Optional[Sequence[str]] = None
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0


DEFAULT_ARGS = OpenAIDecodingArguments()


def openai_completion(
    messages: List[Dict[str, Any]],
    decoding_args: OpenAIDecodingArguments = DEFAULT_ARGS,
    model_name: str = "openai/gpt-oss-120b:free",
    sleep_time: int = 2,
) -> str:
    decoding_args = copy.deepcopy(decoding_args)
    assert decoding_args.n == 1

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ.get("OPENROUTER_API_KEY", ""),
    )

    max_retries = 5
    retry_delay = 30  # seconds, doubles each retry

    while True:
        try:
            completions = client.chat.completions.create(
                messages=messages, model=model_name, **decoding_args.__dict__
            )
            break
        except RateLimitError as e:
            max_retries -= 1
            if max_retries <= 0:
                logging.error("Rate limit: max retries exceeded, giving up.")
                raise e
            logging.warning(
                "Rate limit (429). Waiting %ds before retry (%d left)...",
                retry_delay, max_retries,
            )
            time.sleep(retry_delay)
            retry_delay *= 2
        except Exception as e:
            logging.warning("OpenAI error: %s.", e)
            if "Please reduce" in str(e):
                decoding_args.max_tokens = int(decoding_args.max_tokens * 0.8)
                logging.warning(
                    "Reducing target length to %d, Retrying...",
                    decoding_args.max_tokens,
                )
            else:
                raise e
    content = completions.choices[0].message.content
    if content is None:
        content = ""
    content = content.strip()
    content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
    return content


def openai_batch_completion(
    batch: List[List[Dict[str, Any]]],
    decoding_args: OpenAIDecodingArguments = DEFAULT_ARGS,
    model_name: str = "openai/gpt-oss-120b:free",
    sleep_time: int = 2,
) -> List[str]:
    completions = []
    with ThreadPool(len(batch)) as pool:
        results = pool.starmap(
            openai_completion,
            [(messages, decoding_args, model_name, sleep_time) for messages in batch],
        )
        for result in results:
            completions.append(result)
    return completions
