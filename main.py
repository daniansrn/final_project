import os
import sys
from pathlib import Path
from typing import List, Dict, Optional, Union

from colorama import Fore, Style, init as colorama_init
from dotenv import load_dotenv

from edamam_client import EdamamClient
from llm_agent import generate_recipe_response, parse_user_query
from ratings import save_rating, get_average, get_count
from substitution_agent import find_substitutes


colorama_init(autoreset=True)

PAGE_SIZE = 5
SERVING_OPTIONS = [1, 2, 4, 6, 8]

_DRINK_DISH_TYPES = {"drinks"}
_DRINK_LABEL_KEYWORDS = {
    "smoothie", "milkshake", "shake", "juice", "beverage", "latte",
    "milk drink", "cocktail", "punch", "frappe", "slushie", "spritzer",
    "lemonade", "eggnog", "hot chocolate", "cider",
}


def _is_drink(recipe: Dict) -> bool:
    dish_types = {dt.lower() for dt in recipe.get("dishType", [])}
    label = recipe.get("label", "").lower()
    return bool(dish_types & _DRINK_DISH_TYPES) or any(kw in label for kw in _DRINK_LABEL_KEYWORDS)


def load_configuration() -> Dict[str, str]:
    load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)
    return {
        "openai_api_key": os.getenv("OPENAI_API_KEY", "").strip(),
        "edamam_app_id": os.getenv("EDAMAM_APP_ID", "").strip(),
        "edamam_app_key": os.getenv("EDAMAM_APP_KEY", "").strip(),
        "edamam_account_user": os.getenv("EDAMAM_ACCOUNT_USER", "").strip(),
        "edamam_api_url": os.getenv("EDAMAM_API_URL", "https://api.edamam.com/api/recipes/v2").strip(),
    }


def assert_configuration(config: Dict[str, str]) -> None:
    missing = []
    required = ["edamam_app_id", "edamam_app_key", "openai_api_key"]

    for key in required:
        if not config.get(key):
            missing.append(key)

    if missing:
        print("Missing configuration:")
        for key in missing:
            print(f"  - {key}")
        print("Copy .env.example to .env and add your credentials.")
        sys.exit(1)


def display_allergen_info(recipe: Dict) -> None:
    calories = round(recipe.get("calories", 0))
    servings = recipe.get("yield") or 1
    cal_per_serving = round(calories / servings) if servings else calories
    diet_labels = recipe.get("dietLabels", [])
    cautions = [c for c in recipe.get("cautions", []) if c.upper() != "SULFITES"]
    allergy_keywords = {"free", "vegan", "vegetarian", "kosher", "halal"}
    allergy_labels = [
        h for h in recipe.get("healthLabels", [])
        if any(kw in h.lower() for kw in allergy_keywords)
    ]

    print("\n===== Nutrition & Allergen Info =====")
    print(f"  Calories (total): {calories} kcal  |  Per serving: {cal_per_serving} kcal  |  Servings: {servings}")
    if diet_labels:
        print(f"  Diet labels: {', '.join(diet_labels)}")
    if allergy_labels:
        print(f"  Safe for: {', '.join(allergy_labels)}")
    if cautions:
        print(f"  ⚠  Allergen cautions: {', '.join(cautions)}")
    else:
        print("  No allergen cautions listed for this recipe.")
    print()


def prompt_rating(recipe_url: str) -> None:
    count = get_count(recipe_url)
    avg = get_average(recipe_url)
    if count:
        stars = round(avg)
        print(f"  Current rating: {'★' * stars}{'☆' * (5 - stars)} — {avg:.1f}/5 from {count} review{'s' if count != 1 else ''}")
    while True:
        raw = input("Rate this recipe [1-5] (or press Enter to skip): ").strip()
        if not raw:
            return
        if raw.isdigit() and 1 <= int(raw) <= 5:
            save_rating(recipe_url, int(raw))
            print("  Rating saved. Thanks!")
            return
        print("  Please enter a number between 1 and 5.")


def prompt_serving_size(original_servings: int) -> int:
    default = original_servings if original_servings in SERVING_OPTIONS else 2
    options_str = ", ".join(str(o) for o in SERVING_OPTIONS)
    while True:
        raw = input(f"Serving size [{options_str}] (default {default}): ").strip()
        if not raw:
            return default
        if raw.isdigit() and int(raw) in SERVING_OPTIONS:
            return int(raw)
        print(f"  Please enter one of: {options_str}")


def print_welcome() -> None:
    print("\nSnackBot - AI Recipe Assistant")
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
        cautions = [c for c in recipe.get("cautions", []) if c.upper() != "SULFITES"]
        print(Fore.LIGHTMAGENTA_EX + f"{index}. {label}" + Style.RESET_ALL + f" — {source}")
        print(f"   Main ingredients: {ingredients_preview}")
        print(f"   Time: {time_text}")
        if cautions:
            print(Fore.RED + f"   ⚠  Allergen cautions: {', '.join(cautions)}")
    print()


def prompt_recipe_selection(
    page_recipes: List[Dict[str, str]], has_next: bool
) -> Union[Dict[str, str], str, None]:
    next_hint = "  np=next page" if has_next else ""
    prompt = f"Choose 1–{len(page_recipes)}{next_hint}  ns=new search  q=quit: "
    while True:
        choice = input(prompt).strip().lower()
        if not choice:
            continue

        if choice in {"q", "quit", "exit"}:
            return None
        if choice == "ns":
            return "new"
        if choice == "np":
            if has_next:
                return "next"
            print("No more pages — you're on the last one.")
            continue

        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(page_recipes):
                return page_recipes[index - 1]

        print(f"  Please enter 1–{len(page_recipes)}{', np' if has_next else ''}, ns, or q.")


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
            user_query = input("Ingredients or leftovers: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if not user_query:
            continue

        if user_query.lower() in {"exit", "quit", "q"}:
            print("Goodbye!")
            break

        allergy_input = input("Any allergies to avoid? (e.g. gluten, dairy — or press Enter to skip): ").strip()
        user_allergies = (
            [a.strip().lower() for a in allergy_input.replace(" and ", ",").split(",") if a.strip()]
            if allergy_input else []
        )

        parsed = parse_user_query(user_query)
        search_query = parsed.get("search_query", user_query)
        meal_intent = parsed.get("meal_intent", "any")
        extra_exclude = [t.lower() for t in parsed.get("exclude_labels", [])]

        try:
            all_recipes = client.search_recipes(search_query, limit=20)
        except Exception as exc:
            print(f"Error retrieving recipes: {exc}")
            continue

        if meal_intent == "food":
            all_recipes = [r for r in all_recipes if not _is_drink(r)]
        elif meal_intent == "drink":
            all_recipes = [r for r in all_recipes if _is_drink(r)]

        if extra_exclude:
            all_recipes = [
                r for r in all_recipes
                if not any(term in r.get("label", "").lower() for term in extra_exclude)
            ]

        if user_allergies:
            all_recipes = [
                r for r in all_recipes
                if not any(
                    allergy in caution.lower()
                    for allergy in user_allergies
                    for caution in r.get("cautions", [])
                )
            ]

        if not all_recipes:
            print("No recipes found matching your ingredients and allergy restrictions. Try again.")
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

        display_allergen_info(selected_recipe)

        original_servings = int(selected_recipe.get("yield") or 2)
        chosen_servings = prompt_serving_size(original_servings)
        target_servings = chosen_servings if chosen_servings != original_servings else None

        print("\nIngredients:")
        for i, line in enumerate(selected_recipe.get("ingredientLines", []), start=1):
            print(f"  {i}. {line}")
        print()

        missing_input = input("Missing any ingredients? List them (or press Enter to skip): ").strip()
        substitutions = None
        if missing_input:
            missing = [i.strip() for i in missing_input.replace(" and ", ",").split(",") if i.strip()]
            substitutions = find_substitutes(missing)

        print(f"\nGenerating recipe for: {selected_recipe.get('label')}\n")

        try:
            assistant_response = generate_recipe_response(
                selected_recipe, user_query, history=history,
                target_servings=target_servings, substitutions=substitutions,
            )
            print(assistant_response)
            print()
        except Exception as exc:
            print(f"Error generating recipe response: {exc}")
            continue

        print("Enjoy your meal!")
        prompt_rating(selected_recipe.get("url", ""))
        break


if __name__ == "__main__":
    main()
