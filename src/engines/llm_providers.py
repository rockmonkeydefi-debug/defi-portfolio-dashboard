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


class BedrockProvider(LLMProvider):
    """AWS Bedrock provider — uses Bearer token auth via REST API."""
    
    def __init__(self, model: str = "us.anthropic.claude-3-5-haiku-20241022-v1:0", region: str = None, api_key: str = None):
        self.model = model
        self.region = region or os.getenv("AWS_REGION", "us-east-1")
        self.api_key = api_key or os.getenv("AWS_BEARER_TOKEN_BEDROCK")
    
    def complete(self, system_prompt: str, user_prompt: str) -> dict:
        import requests
        
        url = f"https://bedrock-runtime.{self.region}.amazonaws.com/model/{self.model}/converse"
        
        payload = {
            "system": [{"text": system_prompt}],
            "messages": [{"role": "user", "content": [{"text": user_prompt}]}],
            "inferenceConfig": {"temperature": 0.3, "maxTokens": 8192},
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        
        resp = requests.post(url, json=payload, headers=headers, timeout=300)
        if not resp.ok:
            error_body = resp.text[:500]
            raise Exception(f"Bedrock API error {resp.status_code}: {error_body}")
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
    
    if provider_type == "bedrock":
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
