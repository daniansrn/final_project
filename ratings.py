import json
import os
from typing import Dict

RATINGS_FILE = os.path.join(os.path.dirname(__file__), "ratings.json")


def load_ratings() -> Dict[str, dict]:
    if not os.path.exists(RATINGS_FILE):
        return {}
    with open(RATINGS_FILE) as f:
        return json.load(f)


def save_rating(recipe_url: str, stars: int) -> None:
    ratings = load_ratings()
    if recipe_url not in ratings:
        ratings[recipe_url] = {"total": 0, "count": 0}
    ratings[recipe_url]["total"] += stars
    ratings[recipe_url]["count"] += 1
    with open(RATINGS_FILE, "w") as f:
        json.dump(ratings, f, indent=2)


def get_average(recipe_url: str) -> float:
    entry = load_ratings().get(recipe_url, {})
    if not entry.get("count"):
        return 0.0
    return entry["total"] / entry["count"]


def get_count(recipe_url: str) -> int:
    return load_ratings().get(recipe_url, {}).get("count", 0)


def sort_by_rating(recipes: list) -> list:
    """Stable sort: rated recipes bubble up by avg rating; unrated keep original order."""
    return sorted(recipes, key=lambda r: get_average(r.get("url", "")), reverse=True)
