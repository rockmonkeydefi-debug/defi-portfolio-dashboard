"""LLM provider abstractions for OpenAI and AWS Bedrock."""

import json
import os


class LLMProvider:
    """Base class for LLM providers."""
    def complete(self, system_prompt: str, user_prompt: str) -> dict:
        """Send prompt and return parsed JSON response + token counts."""
        raise NotImplementedError


class OpenAIProvider(LLMProvider):
    """OpenAI API provider."""
    
    def __init__(self, model: str = "gpt-4o", api_key: str = None):
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not set")
    
    def complete(self, system_prompt: str, user_prompt: str) -> dict:
        import requests
        last_err = None
        for attempt in range(3):
            try:
                resp = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.3,
                        "response_format": {"type": "json_object"},
                    },
                    timeout=120,
                )
                if resp.status_code == 429 and attempt < 2:
                    import time
                    time.sleep(5 * (attempt + 1))
                    continue
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                return {
                    "response": json.loads(content),
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "provider": "openai",
                    "model": self.model,
                }
            except requests.exceptions.Timeout:
                last_err = f"OpenAI request timed out (attempt {attempt+1}/3)"
                print(last_err)
                if attempt < 2:
                    import time
                    time.sleep(3)
                continue
            except json.JSONDecodeError as e:
                raise Exception(f"OpenAI returned invalid JSON: {e}")
            except requests.exceptions.RequestException as e:
                if attempt < 2 and hasattr(e, 'response') and e.response is not None and e.response.status_code >= 500:
                    import time
                    time.sleep(5)
                    continue
                raise
        raise Exception(last_err or "OpenAI request failed after 3 attempts")


def _claude_supports_temperature(model_id: str) -> bool:
    """Return True if a Claude model ID accepts the `temperature` parameter.

    Anthropic deprecated `temperature` (along with top_p / top_k) starting
    with the Claude 4.7 family. Older models (3.x, 4.0–4.6) still accept it
    and behave differently when it's omitted, so we keep sending it for them.

    Detection extracts the `claude-<family>-<major>-<minor>` segment from
    either Anthropic-native IDs (`claude-opus-4-7`) or Bedrock inference
    profile IDs (`us.anthropic.claude-opus-4-7-v1:0`) and checks whether
    `(major, minor)` is `>= (4, 7)`. Names that don't match the pattern
    (older 3.x dated IDs, non-Claude models) default to keeping temperature.
    """
    if not model_id:
        return True
    import re
    # Match `claude-<family>-<major>-<minor>` where family is opus/sonnet/haiku
    # and major/minor are single digits. Anchor on the family name so that
    # other dashed segments (dates, version suffixes) don't trigger false hits.
    m = re.search(
        r"claude-(opus|sonnet|haiku)-(\d+)-(\d+)",
        model_id.lower()
    )
    if not m:
        return True
    major = int(m.group(2))
    minor = int(m.group(3))
    # 4.7+ and any 5.x or higher drop temperature.
    if major > 4:
        return False
    if major == 4 and minor >= 7:
        return False
    return True


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API provider."""

    def __init__(self, model: str = "claude-sonnet-4-6", api_key: str = None):
        self.model = model
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

    def complete(self, system_prompt: str, user_prompt: str) -> dict:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)

        last_err = None
        for attempt in range(3):
            try:
                kwargs = dict(
                    model=self.model,
                    max_tokens=8192,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                if _claude_supports_temperature(self.model):
                    kwargs["temperature"] = 0.3
                resp = client.messages.create(**kwargs)
                content = resp.content[0].text

                # Parse JSON from response
                text = content.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    repaired = text.rstrip()
                    if repaired.endswith(','):
                        repaired = repaired[:-1]
                    open_braces = repaired.count('{') - repaired.count('}')
                    open_brackets = repaired.count('[') - repaired.count(']')
                    repaired += ']' * open_brackets + '}' * open_braces
                    try:
                        parsed = json.loads(repaired)
                    except json.JSONDecodeError:
                        parsed = {"error": "LLM response was truncated", "partial_text": text[:500]}

                return {
                    "response": parsed,
                    "prompt_tokens": resp.usage.input_tokens,
                    "completion_tokens": resp.usage.output_tokens,
                    "provider": "anthropic",
                    "model": self.model,
                }
            except anthropic.RateLimitError:
                last_err = f"Anthropic rate limited (attempt {attempt+1}/3)"
                print(last_err)
                if attempt < 2:
                    import time
                    time.sleep(5 * (attempt + 1))
                continue
            except anthropic.APITimeoutError:
                last_err = f"Anthropic request timed out (attempt {attempt+1}/3)"
                print(last_err)
                if attempt < 2:
                    import time
                    time.sleep(3)
                continue
            except anthropic.APIStatusError as e:
                if attempt < 2 and e.status_code >= 500:
                    import time
                    time.sleep(5)
                    continue
                raise Exception(f"Anthropic API error {e.status_code}: {e.message}")
        raise Exception(last_err or "Anthropic request failed after 3 attempts")


class BedrockProvider(LLMProvider):
    """AWS Bedrock provider — uses Bearer token auth via REST API."""
    
    def __init__(self, model: str = "us.anthropic.claude-3-5-haiku-20241022-v1:0", region: str = None, api_key: str = None):
        self.model = model
        self.region = region or os.getenv("AWS_REGION", "us-east-1")
        self.api_key = api_key or os.getenv("AWS_BEARER_TOKEN_BEDROCK")
    
    def complete(self, system_prompt: str, user_prompt: str) -> dict:
        import requests
        
        url = f"https://bedrock-runtime.{self.region}.amazonaws.com/model/{self.model}/converse"

        # Claude 4.7+ rejects `temperature` in inferenceConfig — only include it
        # for older models that still accept (and behave as expected with) it.
        inference_config = {"maxTokens": 8192}
        if _claude_supports_temperature(self.model):
            inference_config["temperature"] = 0.3

        payload = {
            "system": [{"text": system_prompt}],
            "messages": [{"role": "user", "content": [{"text": user_prompt}]}],
            "inferenceConfig": inference_config,
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        
        resp = requests.post(url, json=payload, headers=headers, timeout=300)
        if not resp.ok:
            error_body = resp.text[:500]
            raise requests.exceptions.HTTPError(f"Bedrock API error {resp.status_code}: {error_body}")
        result = resp.json()
        
        content = result.get("output", {}).get("message", {}).get("content", [{}])[0].get("text", "{}")
        usage = result.get("usage", {})
        
        # Parse JSON from response
        text = content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        
        # Handle truncated JSON — try to repair by closing open structures
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # Attempt repair: close any open strings, arrays, objects
            repaired = text.rstrip()
            if repaired.endswith(','):
                repaired = repaired[:-1]
            # Count open braces/brackets
            open_braces = repaired.count('{') - repaired.count('}')
            open_brackets = repaired.count('[') - repaired.count(']')
            # Check for unterminated string
            in_string = False
            for ch in repaired:
                if ch == '"' and (not repaired or repaired[repaired.index(ch)-1:repaired.index(ch)] != '\\'):
                    in_string = not in_string
            if in_string:
                repaired += '"'
            repaired += ']' * open_brackets + '}' * open_braces
            try:
                parsed = json.loads(repaired)
            except json.JSONDecodeError:
                parsed = {"error": "LLM response was truncated", "partial_text": text[:500]}
        
        return {
            "response": parsed,
            "prompt_tokens": usage.get("inputTokens", 0),
            "completion_tokens": usage.get("outputTokens", 0),
            "provider": "bedrock",
            "model": self.model,
        }


def get_provider(config: dict) -> LLMProvider:
    """Factory to create the right provider from config."""
    provider_type = config.get("provider", "openai").lower()
    model = config.get("model", "")

    if provider_type == "anthropic":
        return AnthropicProvider(
            model=model or "claude-sonnet-4-6",
            api_key=config.get("api_key") or os.getenv("ANTHROPIC_API_KEY"),
        )
    elif provider_type == "bedrock":
        return BedrockProvider(
            model=model or "us.anthropic.claude-3-5-haiku-20241022-v1:0",
            region=config.get("aws_region"),
            api_key=config.get("api_key") or os.getenv("AWS_BEARER_TOKEN_BEDROCK"),
        )
    else:
        return OpenAIProvider(
            model=model or "gpt-4o",
            api_key=config.get("api_key") or os.getenv("OPENAI_API_KEY"),
        )
