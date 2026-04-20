import os
import sys
from pathlib import Path
from typing import List, Dict, Optional, Union

from dotenv import load_dotenv

from edamam_client import EdamamClient
from llm_agent import generate_recipe_response
from substitution_agent import get_substitution_advice


PAGE_SIZE = 5


def load_configuration() -> Dict[str, str]:
    load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)
    return {
        "llm_provider": os.getenv("LLM_PROVIDER", "openai").strip().lower(),
        "openai_api_key": os.getenv("OPENAI_API_KEY", "").strip(),
        "edamam_app_id": os.getenv("EDAMAM_APP_ID", "").strip(),
        "edamam_app_key": os.getenv("EDAMAM_APP_KEY", "").strip(),
        "edamam_account_user": os.getenv("EDAMAM_ACCOUNT_USER", "").strip(),
        "edamam_api_url": os.getenv("EDAMAM_API_URL", "https://api.edamam.com/api/recipes/v2").strip(),
    }


def assert_configuration(config: Dict[str, str]) -> None:
    missing = []
    required = ["edamam_app_id", "edamam_app_key"]
    if config.get("llm_provider") == "openai":
        required.append("openai_api_key")

    for key in required:
        if not config.get(key):
            missing.append(key)

    if missing:
        print("Missing configuration:")
        for key in missing:
            print(f"  - {key}")
        print("Copy .env.example to .env and add your credentials.")
        sys.exit(1)


def print_welcome() -> None:
    print("\nAI Recipe Chatbot")
    print("Tell the agent what ingredients, leftovers, or nearly expired items you have.")
    print("Enter 'exit', 'quit', or 'q' to stop.\n")


def display_recipe_choices(page_recipes: List[Dict[str, str]], page: int, total: int) -> None:
    start = page * PAGE_SIZE + 1
    end = min(start + PAGE_SIZE - 1, total)
    print(f"\nRecipes {start}–{end} of {total}:")
    for index, recipe in enumerate(page_recipes, start=1):
        label = recipe.get("label", "Unknown recipe")
        source = recipe.get("source", "Unknown source")
        total_time = recipe.get("totalTime")
        time_text = f"{total_time} min" if total_time else "Time not available"
        main_ingredients = recipe.get("mainIngredients", [])
        ingredients_preview = ", ".join(main_ingredients[:3]) if main_ingredients else "—"
        print(f"{index}. {label} — {source}")
        print(f"   Main ingredients: {ingredients_preview}")
        print(f"   Time: {time_text}")
    print()


def prompt_recipe_selection(
    page_recipes: List[Dict[str, str]], has_next: bool
) -> Union[Dict[str, str], str, None]:
    next_hint = ", 'next page'" if has_next else ""
    prompt = f"Choose 1–{len(page_recipes)}{next_hint}, 'new search', or 'exit': "
    while True:
        choice = input(prompt).strip()
        if not choice:
            continue

        lower = choice.lower()
        if lower in {"exit", "quit", "q"}:
            return None
        if lower == "new search":
            return "new"
        if lower == "next page":
            if has_next:
                return "next"
            print("No more pages — you're on the last one.")
            continue

        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(page_recipes):
                return page_recipes[index - 1]

        print(f"Please enter a number 1–{len(page_recipes)}{next_hint}, 'new search', or 'exit'.")


def main() -> None:
    config = load_configuration()
    assert_configuration(config)

    client = EdamamClient(
        app_id=config["edamam_app_id"],
        app_key=config["edamam_app_key"],
        api_url=config["edamam_api_url"],
        user_id=config["edamam_account_user"],
    )

    print_welcome()
    history: List[Dict[str, str]] = []

    while True:
        try:
            user_query = input("Ingredients or leftovers> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if not user_query:
            continue

        if user_query.lower() in {"exit", "quit", "q"}:
            print("Goodbye!")
            break

        try:
            all_recipes = client.search_recipes(user_query, limit=20)
        except Exception as exc:
            print(f"Error retrieving recipes: {exc}")
            continue

        if not all_recipes:
            print("No recipes found for that query. Try another set of ingredients.")
            continue

        # Paginate through results in batches of PAGE_SIZE
        page = 0
        selected_recipe = None

        while True:
            page_recipes = all_recipes[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
            if not page_recipes:
                print("No more recipes available. Try a new search.")
                break

            has_next = (page + 1) * PAGE_SIZE < len(all_recipes)
            display_recipe_choices(page_recipes, page, len(all_recipes))
            selection = prompt_recipe_selection(page_recipes, has_next)

            if selection is None:
                print("Goodbye!")
                sys.exit(0)
            if selection == "new":
                break
            if selection == "next":
                page += 1
                continue

            selected_recipe = selection
            break

        if selected_recipe is None:
            continue

        # Substitution check
        missing_input = input("Missing any ingredients? List them (or press Enter to skip): ").strip()
        if missing_input:
            missing = [i.strip() for i in missing_input.replace(" and ", ",").split(",") if i.strip()]
            print("\nFinding substitutes...\n")
            try:
                get_substitution_advice(selected_recipe, missing)
                print()
            except Exception as exc:
                print(f"Could not get substitution advice: {exc}")
            input("\nPress Enter to continue to the full recipe...")

        print(f"\nGenerating a complete recipe for: {selected_recipe.get('label')}\n")

        try:
            assistant_response = generate_recipe_response(selected_recipe, user_query, history=history)
            print(assistant_response)
            print()
        except Exception as exc:
            print(f"Error generating recipe response: {exc}")
            continue

        print("Enjoy your meal!")
        break


if __name__ == "__main__":
    main()
