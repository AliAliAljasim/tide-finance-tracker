"""Local LLM client (Ollama) shared by parsing.py and categorization.py.

Talks to a local Ollama server over its HTTP API using structured outputs:
the JSON schema is passed as `format`, so the model is constrained to return
a JSON object matching it. Nothing leaves the machine.

Config:
  OLLAMA_HOST   - server address, default http://127.0.0.1:11434. Set it to
                  an empty string to turn the AI step off (the tests do this).
  OLLAMA_MODEL  - model tag, default qwen2.5:7b (~5 GB RAM on CPU).
"""
import json
import os
import urllib.error
import urllib.request

DEFAULT_HOST = 'http://127.0.0.1:11434'
DEFAULT_MODEL = 'qwen2.5:7b'
TIMEOUT_SECONDS = 300  # CPU inference on a long statement can take a while


class LLMUnavailable(Exception):
    """No Ollama server configured or reachable."""


class LLMError(Exception):
    """The server was reachable but the call failed or returned bad output."""


def _host():
    host = os.environ.get('OLLAMA_HOST', DEFAULT_HOST).strip()
    if host and '://' not in host:
        host = 'http://' + host  # the ollama CLI accepts bare "host:port"
    return host.rstrip('/')


def structured_chat(prompt, schema):
    """Returns the model's reply parsed as a dict matching `schema`."""
    host = _host()
    if not host:
        raise LLMUnavailable('OLLAMA_HOST is empty')

    body = json.dumps({
        'model': os.environ.get('OLLAMA_MODEL', DEFAULT_MODEL),
        'messages': [{'role': 'user', 'content': prompt}],
        'format': schema,
        'stream': False,
        'options': {'temperature': 0},
    }).encode()
    req = urllib.request.Request(host + '/api/chat', data=body,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as e:
        raise LLMError(f'Ollama returned HTTP {e.code}: {e.read().decode(errors="replace")[:200]}')
    except urllib.error.URLError as e:
        raise LLMUnavailable(f'Could not reach Ollama at {host}: {e.reason}')
    except (TimeoutError, ValueError) as e:
        raise LLMError(f'Ollama call failed: {e}')

    try:
        return json.loads(payload['message']['content'])
    except (KeyError, TypeError, ValueError) as e:
        raise LLMError(f'Ollama returned an unexpected response: {e}')
