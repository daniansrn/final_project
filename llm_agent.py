import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
import openai
import requests

load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)


def _build_system_prompt() -> str:
    return (
        "You are a helpful recipe assistant. "
        "When given recipe data, present the recipe in a clear, readable format for the user. "
        "Include: recipe name, servings, total time (if available), a numbered ingredient list, "
        "and step-by-step cooking instructions inferred from the ingredients. "
        "Do not invent ingredients beyond what is listed. "
        "Keep your response concise and practical. Do not add extra commentary before or after the recipe. "
        "IMPORTANT: Always write quantities as plain text fractions like 1/2, 1/4, 3/4, 1/3. "
        "Never use LaTeX notation such as \\frac{}{} or any math markup. Plain text only."
    )


def _build_user_prompt(recipe_data: Dict[str, Any], user_query: str, target_servings: Optional[int] = None) -> str:
    original_servings = recipe_data.get("yield", 1) or 1
    lines = [
        f"User query: {user_query}",
        "Recipe data:",
        f"- Name: {recipe_data.get('label', 'Unknown')}",
        f"- Source: {recipe_data.get('source', 'Unknown')}",
        f"- URL: {recipe_data.get('url', '')}",
        f"- Original servings: {original_servings}",
    ]

    total_time = recipe_data.get("totalTime")
    if total_time:
        lines.append(f"- Total time: {total_time} minutes")

    diet_labels = recipe_data.get("dietLabels", [])
    if diet_labels:
        lines.append(f"- Diet labels: {', '.join(diet_labels)}")

    health_labels = recipe_data.get("healthLabels", [])
    if health_labels:
        lines.append(f"- Health labels: {', '.join(health_labels)}")

    lines.append("- Ingredients:")
    for ingredient in recipe_data.get("ingredientLines", []):
        lines.append(f"  - {ingredient}")

    cautions = recipe_data.get("cautions", [])
    if cautions:
        lines.append(f"- Cautions: {', '.join(cautions)}")

    if target_servings and target_servings != original_servings:
        lines.append(
            f"\nIMPORTANT: Scale this recipe to serve exactly {target_servings} person(s) instead of {original_servings}. "
            f"Divide ALL ingredient quantities by {original_servings} and multiply by {target_servings}. "
            f"Express quantities as simple readable fractions like 1/4, 1/2, 3/4, 1/3, 2/3 — "
            f"do NOT use LaTeX, decimal numbers, or math notation like \\frac{{}}{{}}. "
            f"Show the adjusted quantities clearly. Keep cooking times the same unless the change is significant."
        )

    lines.append("\nPlease present this as a complete, easy-to-follow recipe with numbered steps.")
    return "\n".join(lines)


def generate_recipe_response(
    recipe_data: Dict[str, Any],
    user_prompt: str,
    history: Optional[List[Dict[str, str]]] = None,
    model: str = "gpt-3.5-turbo",
    temperature: float = 0.8,
    target_servings: Optional[int] = None,
) -> str:
    provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": _build_system_prompt()},
    ]

    if history:
        for item in history:
            messages.append(item)

    messages.append({"role": "user", "content": _build_user_prompt(recipe_data, user_prompt, target_servings)})

    if provider == "groq":
        return _generate_groq_response(messages, temperature=temperature, max_tokens=1500)

    if provider == "ollama":
        return _generate_ollama_response(messages, temperature=temperature, max_tokens=1500)

    return _generate_openai_response(messages, model=model, temperature=temperature, max_tokens=1500)


def _generate_openai_response(
    messages: List[Dict[str, str]],
    model: str,
    temperature: float = 0.8,
    max_tokens: int = 700,
) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY is not set in the environment.")

    client = openai.OpenAI(api_key=api_key)
    completion = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    return completion.choices[0].message.content.strip()



def _generate_ollama_response(
    messages: List[Dict[str, str]],
    temperature: float = 0.8,
    max_tokens: int = 1500,
) -> str:
    api_url = os.getenv("OLLAMA_API_URL", "http://127.0.0.1:11434/v1/chat/completions")
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    response = requests.post(api_url, json=payload, timeout=60)
    if response.status_code != 200:
        raise RuntimeError(f"Ollama request failed: {response.status_code} - {response.text.strip()}")

    return response.json()["choices"][0]["message"]["content"].strip()


def _generate_groq_response(
    messages: List[Dict[str, str]],
    temperature: float = 0.8,
    max_tokens: int = 1500,
) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError("GROQ_API_KEY is not set in the environment.")

    payload = {
        "model": "llama3-8b-8192",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Groq request failed: {response.status_code} - {response.text.strip()}")

    return response.json()["choices"][0]["message"]["content"].strip()
