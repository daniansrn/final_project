import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
import openai

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
        "Never use LaTeX notation such as \\frac{}{} or any math markup. Plain text only. "
        "When an ingredient is marked [MISSING], always add a 'Substitute:' line directly beneath it. "
        "If substitute options are provided, use them. "
        "If the tag says 'no database entry', draw on your own culinary knowledge to confidently recommend "
        "the best substitute — never leave it blank or say you don't know. "
        "Format: \"Substitute: [suggestion] can be used in the same amount.\" or similar one-sentence advice."
    )


def _build_user_prompt(recipe_data: Dict[str, Any], user_query: str, target_servings: Optional[int] = None, substitutions: Optional[Dict[str, Any]] = None) -> str:
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
        if substitutions:
            ing_lower = ingredient.lower()
            for missing_key, info in substitutions.items():
                if missing_key.lower() in ing_lower:
                    if info:
                        subs = ", ".join(info.get("substitutes", [])[:3])
                        notes = info.get("notes", "")
                        lines.append(f"    [MISSING — substitutes: {subs}. {notes}]")
                    else:
                        lines.append(f"    [MISSING — no database entry, apply your culinary knowledge to suggest the best substitute]")
                    break

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


def _call_openai(messages: List[Dict[str, str]], model: str = "gpt-3.5-turbo", temperature: float = 0.8, max_tokens: int = 700) -> str:
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


def parse_user_query(raw_input: str) -> Dict[str, Any]:
    """Parse natural language input into a clean API search query and meal intent."""
    system = (
        "Extract recipe search parameters from the user's message. "
        "Return ONLY a JSON object with exactly three fields:\n"
        '  "search_query": short ingredient-focused query for a recipe API (e.g. "banana milk"), '
        "ingredients only, no conversational words\n"
        '  "meal_intent": classify the user\'s request as exactly one of: '
        '"food" (they want solid meals, snacks, baked goods — anything you eat), '
        '"drink" (they want beverages, smoothies, juices), '
        '"any" (no preference stated)\n'
        '  "exclude_labels": list of any specific recipe name keywords to exclude beyond the meal intent. '
        "Empty list if none.\n"
        "Return only the JSON object, no markdown, no explanation."
    )
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": raw_input},
    ]
    raw = _call_openai(messages, temperature=0.0, max_tokens=200)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {"search_query": raw_input, "meal_intent": "any", "exclude_labels": []}


def generate_raw_response(
    system_prompt: str,
    user_content: str,
    temperature: float = 0.8,
    max_tokens: int = 700,
) -> str:
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    return _call_openai(messages, temperature=temperature, max_tokens=max_tokens)


def generate_recipe_response(
    recipe_data: Dict[str, Any],
    user_prompt: str,
    history: Optional[List[Dict[str, str]]] = None,
    model: str = "gpt-3.5-turbo",
    temperature: float = 0.8,
    target_servings: Optional[int] = None,
    substitutions: Optional[Dict[str, Any]] = None,
) -> str:
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": _build_system_prompt()},
    ]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": _build_user_prompt(recipe_data, user_prompt, target_servings, substitutions)})
    return _call_openai(messages, model=model, temperature=temperature, max_tokens=1500)
