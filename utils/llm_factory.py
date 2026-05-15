"""
LLM Factory - Pluggable LLM provider system for CrewAI 1.x.
Supports: Groq (free), Gemini (free), OpenAI (paid), Anthropic (paid), Ollama (local free).
Uses crewai.LLM (LiteLLM-backed) — LangChain LLM objects are not compatible with CrewAI 1.x.
"""

import os
from dotenv import load_dotenv
from crewai import LLM

load_dotenv()


def get_llm(provider=None, model=None) -> LLM:
    provider = provider or os.getenv("LLM_PROVIDER", "groq")

    if provider == "groq":
        return _get_groq_llm(model)
    elif provider == "gemini":
        return _get_gemini_llm(model)
    elif provider == "openai":
        return _get_openai_llm(model)
    elif provider == "anthropic":
        return _get_anthropic_llm(model)
    elif provider == "cerebras":
        return _get_cerebras_llm(model)
    elif provider == "ollama":
        return _get_ollama_llm(model)
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


def _get_groq_llm(model=None) -> LLM:
    # LiteLLM routes groq/ prefix to Groq's API automatically
    model = model or os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY not set in environment")
    return LLM(
        model=f"groq/{model}",
        api_key=api_key,
        temperature=0.7,
        max_retries=6,       # retry up to 6x on rate limit
        timeout=120,
    )


def _get_gemini_llm(model=None) -> LLM:
    # Google Gemini — 1M tokens/day free via Google AI Studio
    # crewai native Gemini provider uses bare model names (no gemini/ prefix)
    model = model or "gemini-2.0-flash"
    # strip litellm-style prefix if present
    model = model.replace("gemini/", "")
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY not set in environment")
    return LLM(model=model, api_key=api_key, temperature=0.7)


def _get_openai_llm(model=None) -> LLM:
    model = model or "gpt-4o"
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set in environment")
    return LLM(model=model, api_key=api_key, temperature=0.7)


def _get_anthropic_llm(model=None) -> LLM:
    model = model or "anthropic/claude-3-5-sonnet-20241022"
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set in environment")
    return LLM(model=model, api_key=api_key, temperature=0.7)


def _get_cerebras_llm(model=None) -> LLM:
    model = model or "llama3.1-8b"
    # strip cerebras/ prefix if already present
    model = model.replace("cerebras/", "")
    api_key = os.getenv("CEREBRAS_API_KEY")
    if not api_key:
        raise ValueError("CEREBRAS_API_KEY not set in environment")
    return LLM(
        model=f"cerebras/{model}",
        api_key=api_key,
        temperature=0.7,
        max_retries=4,
        timeout=120,
    )


def _get_ollama_llm(model=None) -> LLM:
    model = model or "ollama/llama3"
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    return LLM(model=model, base_url=base_url, temperature=0.7)


def get_available_models(provider=None):
    provider = provider or os.getenv("LLM_PROVIDER", "groq")
    models = {
        "groq": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
        ],
        "gemini": [
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-2.5-flash",
        ],
        "openai": [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
        ],
        "anthropic": [
            "anthropic/claude-3-5-sonnet-20241022",
            "anthropic/claude-3-5-haiku-20241022",
            "anthropic/claude-3-opus-20240229",
        ],
        "cerebras": [
            "llama3.1-8b",
            "llama3.3-70b",
        ],
        "ollama": [
            "ollama/llama3",
            "ollama/mistral",
            "ollama/llama2",
        ],
    }
    return models.get(provider, [])


def get_provider_info():
    return {
        "groq": {
            "name": "Groq",
            "cost": "FREE",
            "speed": "Very Fast",
            "note": "100K tokens/day free. Get key: console.groq.com"
        },
        "gemini": {
            "name": "Google Gemini",
            "cost": "FREE",
            "speed": "Fast",
            "note": "1M tokens/day free. Get key: aistudio.google.com"
        },
        "openai": {
            "name": "OpenAI",
            "cost": "PAID",
            "speed": "Fast",
            "note": "Requires API key and payment"
        },
        "anthropic": {
            "name": "Anthropic (Claude)",
            "cost": "PAID",
            "speed": "Fast",
            "note": "Requires API key and payment"
        },
        "cerebras": {
            "name": "Cerebras",
            "cost": "FREE",
            "speed": "Ultra Fast",
            "note": "2000 tokens/sec free tier. Get key: cloud.cerebras.ai"
        },
        "ollama": {
            "name": "Ollama (Local)",
            "cost": "FREE",
            "speed": "Variable",
            "note": "Runs locally, requires Ollama installation"
        },
    }
