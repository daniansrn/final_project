import json
import os
from typing import Any, Dict, List, Optional

from llm_agent import generate_recipe_response


def load_substitutes() -> Dict[str, Any]:
    path = os.path.join(os.path.dirname(__file__), "substitutes.json")
    with open(path) as f:
        return json.load(f)


def find_substitutes(missing_ingredients: List[str]) -> Dict[str, Optional[Dict]]:
    """Look up substitutes for each missing ingredient. Tries exact then partial match."""
    data = load_substitutes()
    results = {}
    for item in missing_ingredients:
        key = item.strip().lower()
        if key in data:
            results[item] = data[key]
            continue
        # Partial match — find first key that contains or is contained by the query
        match = next((k for k in data if key in k or k in key), None)
        results[item] = data[match] if match else None
    return results


def build_substitution_prompt(recipe_data: Dict, missing: Dict[str, Optional[Dict]]) -> str:
    lines = [
        f"Recipe: {recipe_data.get('label', 'Unknown')}",
        "",
        "The user is missing these ingredients and needs substitution advice:",
    ]
    for ingredient, info in missing.items():
        if info:
            subs = ", ".join(info.get("substitutes", []))
            notes = info.get("notes", "")
            lines.append(f"- {ingredient}: possible substitutes — {subs}. {notes}")
        else:
            lines.append(f"- {ingredient}: not in substitution database — use your own knowledge.")

    lines += [
        "",
        "Reply with a short bullet list ONLY. For each missing ingredient, one bullet:",
        "• [ingredient] → [best substitute] — [one sentence on quantity or texture change if needed]",
        "Do NOT rewrite or repeat the recipe. Do NOT add intro, outro, or extra commentary.",
    ]
    return "\n".join(lines)


def get_substitution_advice(recipe_data: Dict, missing_ingredients: List[str]) -> str:
    """Main entry point: look up substitutes and generate LLM advice."""
    found = find_substitutes(missing_ingredients)
    prompt = build_substitution_prompt(recipe_data, found)
    # Reuse the recipe response generator with a substitution-focused prompt
    fake_recipe = dict(recipe_data)
    return generate_recipe_response(fake_recipe, prompt)
