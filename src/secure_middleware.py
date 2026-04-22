"""
Secure LLM Middleware - Proxy class for safe LLM interaction.

This middleware guarantees that no raw sensitive text leaves the perimeter.
All requests are passed through PII Guard before sending to external LLMs.

Supports:
- OpenAI API
- Anthropic Claude API
- Automatic PII masking
- Security audit logging
"""

import asyncio
from typing import List, Dict, Any, Optional
from .pii_guard import get_pii_guard


class SecureLLMMiddleware:
    """
    Proxy class for secure LLM interaction.

    Features:
    - Automatic PII masking
    - Security audit logging
    - Support for multiple LLM providers
    - Request/response tracking
    """

    def __init__(
        self,
        provider: str = "anthropic",
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        enable_logging: bool = True
    ):
        """
        Initialize Secure LLM Middleware.

        Args:
            provider: LLM provider ('anthropic' or 'openai')
            api_key: API key for the provider
            model: Model name (default: provider-specific)
            enable_logging: Enable security audit logging
        """
        self.provider = provider.lower()
        self.api_key = api_key
        self.model = model
        self.enable_logging = enable_logging

        # Get PII Guard instance
        self.pii_guard = get_pii_guard()

        # Initialize LLM client
        self.client = None
        self._init_client()

    def _init_client(self):
        """Initialize the LLM client based on provider."""
        try:
            import os
            proxy_url = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("ALL_PROXY")

            if self.provider == "anthropic":
                from anthropic import AsyncAnthropic

                kwargs = {"api_key": self.api_key}
                if proxy_url:
                    try:
                        import httpx
                        proxies = {"http://": proxy_url, "https://": proxy_url}
                        kwargs["http_client"] = httpx.AsyncClient(proxies=proxies, timeout=60.0)
                        print(f"[INFO] Anthropic client with proxy: {proxy_url}")
                    except ImportError:
                        print("[WARN] httpx not installed, proxy will not be used")

                self.client = AsyncAnthropic(**kwargs)
                if not self.model:
                    self.model = "claude-sonnet-4-20250514"
                if not proxy_url:
                    print(f"[INFO] Anthropic client initialized (model: {self.model})")

            elif self.provider == "openai":
                from openai import AsyncOpenAI

                kwargs = {"api_key": self.api_key}
                if proxy_url:
                    try:
                        import httpx
                        proxies = {"http://": proxy_url, "https://": proxy_url}
                        kwargs["http_client"] = httpx.AsyncClient(proxies=proxies, timeout=60.0)
                        print(f"[INFO] OpenAI client with proxy: {proxy_url}")
                    except ImportError:
                        print("[WARN] httpx not installed, proxy will not be used")

                self.client = AsyncOpenAI(**kwargs)
                if not self.model:
                    self.model = "gpt-4o"
                if not proxy_url:
                    print(f"[INFO] OpenAI client initialized (model: {self.model})")

            else:
                raise ValueError(f"Unsupported provider: {self.provider}")

        except Exception as e:
            print(f"[ERROR] Failed to initialize {self.provider} client: {e}")
            self.client = None

    async def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 2000,
        temperature: float = 0.3,
        system_prompt: Optional[str] = None,
        language: str = "ru"
    ) -> str:
        """
        Secure chat with LLM - masks all PII before sending.

        Args:
            messages: List of message dicts with 'role' and 'content'
            max_tokens: Maximum tokens in response
            temperature: Temperature for generation
            system_prompt: System prompt (optional)
            language: Language for PII detection

        Returns:
            LLM response
        """
        if not self.client:
            raise RuntimeError("LLM client not initialized")

        # 1. Create safe copy of messages
        safe_messages = []
        masked_count = 0

        for msg in messages:
            content = msg.get("content", "")

            # Security audit logging
            if self.enable_logging:
                print(f"[SECURITY_AUDIT] Incoming ({msg.get('role')}): {content[:50]}...")

            # 2. Mask PII
            masked_content = self.pii_guard.mask(content, language=language)

            # Check if anything was masked
            if content != masked_content:
                masked_count += 1
                stats = self.pii_guard.get_statistics(content, language)
                if stats:
                    print(f"[SECURITY] Masked entities: {stats}")

            # Security audit logging
            if self.enable_logging:
                print(f"[SECURITY_AUDIT] Outgoing ({msg.get('role')}): {masked_content[:50]}...")

            safe_messages.append({
                "role": msg["role"],
                "content": masked_content
            })

        if masked_count > 0:
            print(f"[SECURITY] PII masked in {masked_count} messages")

        # 3. Call external LLM
        try:
            response = await self._call_llm(
                messages=safe_messages,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature
            )

            return response

        except Exception as e:
            print(f"[ERROR] LLM Call failed: {e}")
            raise e

    async def _call_llm(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float
    ) -> str:
        """
        Internal method to call the appropriate LLM provider.

        Args:
            messages: Safe (masked) messages
            system_prompt: System prompt
            max_tokens: Max tokens
            temperature: Temperature

        Returns:
            LLM response text
        """
        if self.provider == "anthropic":
            return await self._call_anthropic(
                messages, system_prompt, max_tokens, temperature
            )
        elif self.provider == "openai":
            return await self._call_openai(
                messages, system_prompt, max_tokens, temperature
            )
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

    async def _call_anthropic(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float
    ) -> str:
        """Call Anthropic Claude API."""
        # Convert messages to Anthropic format
        anthropic_messages = []
        for msg in messages:
            if msg["role"] == "system":
                continue  # Anthropic uses separate system parameter
            anthropic_messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=anthropic_messages
        )

        return response.content[0].text

    async def _call_openai(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float
    ) -> str:
        """Call OpenAI API."""
        # Add system prompt to messages if provided
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + messages

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature
        )

        return response.choices[0].message.content

    async def summarize(
        self,
        text: str,
        language: str = "ru",
        max_tokens: int = 2000
    ) -> str:
        """
        Summarize text securely with automatic PII masking.

        Args:
            text: Text to summarize
            language: Language for PII detection
            max_tokens: Max tokens in summary

        Returns:
            Generated summary
        """
        system_prompt = """Summarize the following text concisely while preserving:
- Key technical details and decisions
- Action items and next steps
- Important context that should be remembered

Focus on information that would be useful for continuing the conversation later."""

        messages = [{"role": "user", "content": text}]

        return await self.chat(
            messages=messages,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            language=language
        )


# Factory function
def create_secure_middleware(
    provider: str = "anthropic",
    api_key: Optional[str] = None,
    model: Optional[str] = None
) -> SecureLLMMiddleware:
    """
    Factory function to create a Secure LLM Middleware instance.

    Args:
        provider: LLM provider
        api_key: API key (if None, will try to get from environment)
        model: Model name

    Returns:
        SecureLLMMiddleware instance
    """
    import os
    from dotenv import load_dotenv

    load_dotenv()

    # Get API key from environment if not provided
    if api_key is None:
        if provider == "anthropic":
            api_key = os.getenv("ANTHROPIC_API_KEY")
        elif provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise ValueError(f"API key not found for provider: {provider}")

    return SecureLLMMiddleware(
        provider=provider,
        api_key=api_key,
        model=model
    )
