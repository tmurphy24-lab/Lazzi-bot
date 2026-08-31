'''
Author:     Sai Vignesh Golla
LinkedIn:   https://www.linkedin.com/in/saivigneshgolla/

Copyright (c) 2024-2026 Sai Vignesh Golla

License:    MIT License
            https://opensource.org/license/mit

GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

------------------------------------------------------------------------------
Provider-agnostic AI layer built on LangChain.

A single code path serves OpenAI, any OpenAI-compatible endpoint (Ollama,
LM Studio, DeepSeek, vLLM, and similar), Anthropic-Messages-format services
(MiniMax) and Google Gemini. Pick the provider, model, key and URL in
`config/secrets.py`.

Public interface (used by runAiBot.py):
    create_ai_client()  -> AIClient | None
    extract_skills(client, job_description) -> dict
    answer_question(client, question, ...)  -> str
    close_ai_client(client) -> None
------------------------------------------------------------------------------
'''

from __future__ import annotations

import os
from typing import Optional

from pydantic import BaseModel, Field

from langchain.chat_models import init_chat_model

import config.secrets as cfg
from config.settings import showAiErrorAlerts
from modules.helpers import print_lg, critical_error_log, convert_to_json
from modules.ai.prompts import extract_skills_prompt, ai_answer_prompt

try:
    from pyautogui import confirm
except Exception:  # pyautogui may be unavailable in headless environments
    confirm = None


# Whether to keep popping up AI error dialogs (disabled once the user asks to pause them).
_alerts_enabled = bool(showAiErrorAlerts)


def _ai_error_alert(message: str, error: Exception, title: str = "AI Error") -> None:
    '''Log an AI error and (optionally) show a dismissible dialog, mirroring the rest of the tool.'''
    global _alerts_enabled
    if _alerts_enabled and confirm is not None:
        try:
            choice = confirm(f"{message}\n\n{error}\n", title, ["Pause AI alerts", "Okay, continue"])
            if choice == "Pause AI alerts":
                _alerts_enabled = False
        except Exception:
            pass
    critical_error_log(message, error)


def _resolve_provider(name: Optional[str]) -> str:
    '''
    Map the user-facing provider name to a LangChain model provider.
    Everything OpenAI-compatible (OpenAI, Ollama, LM Studio, DeepSeek, vLLM, ...)
    runs through the "openai" provider by pointing the URL at the right server.
    Anthropic-Messages-format services (real Anthropic, MiniMax's native API)
    run through "anthropic" the same way.
    '''
    n = (name or "openai").strip().lower()
    if n in ("gemini", "google", "google_genai", "google-genai"):
        return "google_genai"
    if n in ("anthropic", "claude", "minimax"):
        return "anthropic"
    return "openai"


def _msg_text(message) -> str:
    '''Extract plain text from a LangChain message (handles str content and content-block lists).'''
    text = getattr(message, "text", None)
    if callable(text):
        try:
            text = text()
        except Exception:
            text = None
    if isinstance(text, str) and text:
        return text
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text") or block.get("content") or "")
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)


class AIClient:
    '''Small holder for the chat model.'''
    def __init__(self, model):
        self.model = model


def create_ai_client() -> Optional[AIClient]:
    '''
    Build the chat model from `config/secrets.py`.
    Returns an `AIClient`, or `None` if AI is turned off or setup fails.
    '''
    if not cfg.use_AI:
        print_lg("AI is turned off (use_AI = False in config/secrets.py). Skipping AI setup.")
        return None
    try:
        provider = _resolve_provider(cfg.ai_provider)
        model_name = cfg.llm_model
        api_key = (getattr(cfg, "llm_api_key", "") or "").strip()
        temperature = getattr(cfg, "llm_temperature", None)

        kwargs = {}
        # Some newer models only accept their default temperature; leave it unset unless the user opts in.
        if temperature is not None:
            kwargs["temperature"] = temperature

        if provider == "google_genai":
            if api_key and api_key.lower() != "not-needed":
                os.environ.setdefault("GOOGLE_API_KEY", api_key)
            model = init_chat_model(model_name, model_provider="google_genai", **kwargs)
        elif provider == "anthropic":
            base_url = (getattr(cfg, "llm_api_url", "") or "").strip()
            kwargs["api_key"] = api_key or "not-needed"
            if base_url:
                kwargs["base_url"] = base_url
            model = init_chat_model(model_name, model_provider="anthropic", **kwargs)
        else:
            base_url = (getattr(cfg, "llm_api_url", "") or "").strip()
            # OpenAI-compatible servers accept any key; use a placeholder when none is given.
            kwargs["api_key"] = api_key or "not-needed"
            if base_url:
                kwargs["base_url"] = base_url
            model = init_chat_model(model_name, model_provider="openai", **kwargs)

        print_lg("---- AI CLIENT READY ----")
        print_lg(f"Provider: {cfg.ai_provider}   |   Model: {model_name}")
        print_lg("Change these anytime in ./config/secrets.py")
        print_lg("-------------------------")
        return AIClient(model)
    except Exception as e:
        _ai_error_alert(
            "Could not start the AI client. Check your provider, model name, API key and URL in config/secrets.py.",
            e,
        )
        return None


def close_ai_client(client: Optional[AIClient]) -> None:
    '''LangChain chat models hold no long-lived connection to close; kept for interface symmetry.'''
    return None


# --------------------------------------------------------------------------- #
# Skill extraction (structured output)
# --------------------------------------------------------------------------- #
class ExtractedSkills(BaseModel):
    '''Skills extracted from a job description and grouped into five buckets.'''
    tech_stack: list[str] = Field(default_factory=list, description="Programming languages, frameworks, libraries, databases and tools")
    technical_skills: list[str] = Field(default_factory=list, description="Technical expertise beyond specific tools (system design, data engineering, ...)")
    other_skills: list[str] = Field(default_factory=list, description="Non-technical / soft skills (communication, leadership, teamwork, ...)")
    required_skills: list[str] = Field(default_factory=list, description="Skills explicitly listed as required or expected")
    nice_to_have: list[str] = Field(default_factory=list, description="Skills listed as preferred or beneficial but not mandatory")


def extract_skills(client: Optional[AIClient], job_description: str, stream: bool = False) -> dict:
    '''
    Extract and classify skills from a job description.
    Returns a dict with the five skill buckets, or an ``{"error": ...}`` dict on failure.
    '''
    if not client or not job_description:
        return {"error": "AI client unavailable or empty job description."}
    prompt = extract_skills_prompt.format(job_description)
    try:
        structured = client.model.with_structured_output(ExtractedSkills)
        result = structured.invoke(prompt)
        return result.model_dump()
    except Exception as e:
        # Some local or older models don't support structured output — fall back to plain JSON parsing.
        print_lg("Structured skill extraction unavailable, falling back to plain parsing.", e)
        try:
            return convert_to_json(_msg_text(client.model.invoke(prompt)))
        except Exception as e2:
            _ai_error_alert("Could not extract skills from the job description.", e2)
            return {"error": str(e2)}


# --------------------------------------------------------------------------- #
# Question answering
# --------------------------------------------------------------------------- #
def _build_answer_prompt(question, user_information_all, job_description, about_company, options) -> str:
    prompt = ai_answer_prompt.format(user_information_all or "N/A", question or "")
    if job_description and job_description != "Unknown":
        prompt += f"\n\nJob description:\n{job_description}"
    if about_company and about_company != "Unknown":
        prompt += f"\n\nAbout the company:\n{about_company}"
    if options:
        prompt += "\n\nAnswer with exactly one of these options:\n" + "\n".join(f"- {o}" for o in options)
    return prompt


def _snap_to_option(raw: str, options: list) -> str:
    '''Match the model's free-text answer to one of the allowed options.'''
    for opt in options:                       # exact
        if raw == opt:
            return opt
    low = raw.lower()
    for opt in options:                       # case-insensitive
        if low == opt.lower():
            return opt
    for opt in options:                       # substring (either direction)
        if opt.lower() in low or low in opt.lower():
            return opt
    return raw


def answer_question(
    client: Optional[AIClient],
    question: str,
    options: Optional[list] = None,
    question_type: str = "text",
    job_description: Optional[str] = None,
    about_company: Optional[str] = None,
    user_information_all: Optional[str] = None,
    stream: bool = False,
) -> str:
    '''
    Generate an answer to a single application-form question.

    Free-text questions are returned as-is; select questions are snapped to
    one of the allowed options. Returns the answer string, or "" if AI is
    unavailable or the call fails.
    '''
    if not client or not question:
        return ""
    try:
        prompt = _build_answer_prompt(question, user_information_all, job_description, about_company, options)
        raw = _msg_text(client.model.invoke(prompt)).strip()
        is_select = question_type in ("single_select", "multiple_select")
        answer = _snap_to_option(raw, options or []) if is_select else raw
        print_lg(f'AI answered "{question}" -> "{answer}"')
        return answer
    except Exception as e:
        _ai_error_alert("Could not generate an AI answer for a question.", e)
        return ""
