import os
import re
from typing import Any, Dict, List, Optional

import requests

class EdamamClient:
    def __init__(self, app_id: str, app_key: str, api_url: Optional[str] = None, user_id: Optional[str] = None) -> None:
        self.app_id = app_id
        self.app_key = app_key
        self.api_url = api_url or "https://api.edamam.com/api/recipes/v2"
        self.user_id = user_id

    def search_recipes(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        user_ingredients = self._parse_ingredients(query)

        params = {
            "type": "public",
            "q": query,
            "app_id": self.app_id,
            "app_key": self.app_key,
            "to": limit,
        }
        headers = {}
        if self.user_id:
            headers["Edamam-Account-User"] = self.user_id

        response = requests.get(self.api_url, params=params, headers=headers, timeout=15)
        if response.status_code != 200:
            raise RuntimeError(
                f"Edamam request failed: {response.status_code} - {response.text.strip()}"
            )

        data = response.json()
        hits = data.get("hits", [])
        recipes = [self._normalize_hit(hit) for hit in hits if hit.get("recipe")]

        if user_ingredients:
            recipes = self._rank_by_ingredients(recipes, user_ingredients)

        return recipes

    def _parse_ingredients(self, query: str) -> List[str]:
        """Split the user query into individual ingredient tokens."""
        parts = re.split(r'\s+and\s+|,\s*|&\s*|\s+or\s+', query.lower())
        return [p.strip() for p in parts if p.strip() and len(p.strip()) > 1]

    def _rank_by_ingredients(
        self, recipes: List[Dict[str, Any]], user_ingredients: List[str]
    ) -> List[Dict[str, Any]]:
        """Sort recipes descending by how many user ingredients appear in their ingredient lines."""
        def score(recipe: Dict[str, Any]) -> int:
            text = " ".join(recipe.get("ingredientLines", [])).lower()
            return sum(1 for ing in user_ingredients if ing in text)

        return sorted(recipes, key=score, reverse=True)

    def _normalize_hit(self, hit: Dict[str, Any]) -> Dict[str, Any]:
        recipe = hit.get("recipe", {})
        # Extract clean food names from the structured ingredients list
        main_ingredients = [
            ing["food"]
            for ing in recipe.get("ingredients", [])
            if ing.get("food")
        ]
        return {
            "label": recipe.get("label", "Unknown Recipe"),
            "source": recipe.get("source", "Unknown source"),
            "url": recipe.get("url", ""),
            "image": recipe.get("image", ""),
            "yield": recipe.get("yield", ""),
            "calories": recipe.get("calories", 0),
            "dietLabels": recipe.get("dietLabels", []),
            "healthLabels": recipe.get("healthLabels", []),
            "ingredientLines": recipe.get("ingredientLines", []),
            "mainIngredients": main_ingredients,
            "cautions": recipe.get("cautions", []),
            "dishType": recipe.get("dishType", []),
            "totalTime": recipe.get("totalTime", 0),
        }
