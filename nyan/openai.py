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

_client = None

def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ.get("OPENROUTER_API_KEY", ""),
            max_retries=0,
            default_headers={
                "HTTP-Referer": "https://github.com/IlyaGusev/nyan",
                "X-Title": "Nyan",
            }
        )
    return _client


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
    model_name: str = "stepfun/step-3.5-flash:free",
    sleep_time: int = 2,
) -> str:
    decoding_args = copy.deepcopy(decoding_args)
    assert decoding_args.n == 1

    client = _get_client()

    max_retries = 3
    retry_delay = 30

    while True:
        try:
            completions = client.chat.completions.create(
                messages=messages, model=model_name, **decoding_args.__dict__
            )
            break
        except RateLimitError as e:
            max_retries -= 1
            # Debug: dump full error details
            response = getattr(e, 'response', None)
            if response is not None:
                logging.warning("Response status: %s", response.status_code)
                logging.warning("Response headers: %s", dict(response.headers))
                logging.warning("Response body: %s", response.text)
            else:
                logging.warning("No response object on error: %s", repr(e))
            if max_retries <= 0:
                logging.error("Rate limit: max retries exceeded, giving up.")
                return ""
            logging.warning(
                "Rate limit (429). Waiting %ds before retry (%d left)...",
                retry_delay, max_retries,
            )
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 120)
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
    model_name: str = "stepfun/step-3.5-flash:free",
    sleep_time: int = 2,
) -> List[str]:
    completions = []
    for messages in batch:
        result = openai_completion(
            messages=messages, 
            decoding_args=decoding_args, 
            model_name=model_name, 
            sleep_time=sleep_time
        )
        completions.append(result)
        time.sleep(max(sleep_time, 5))
        
    return completions
