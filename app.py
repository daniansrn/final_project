import streamlit as st
from dotenv import load_dotenv

from edamam_client import EdamamClient
from llm_agent import generate_recipe_response
from main import load_configuration
from ratings import save_rating, get_average, get_count
from substitution_agent import find_substitutes, build_substitution_prompt, get_substitution_advice

PAGE_SIZE = 5

load_dotenv()
config = load_configuration()

st.set_page_config(page_title="Scraps to Snacks", page_icon="♻️", layout="centered")


@st.cache_resource
def get_client() -> EdamamClient:
    return EdamamClient(
        app_id=config["edamam_app_id"],
        app_key=config["edamam_app_key"],
        api_url=config["edamam_api_url"],
        user_id=config["edamam_account_user"],
    )


client = get_client()

for key, default in [
    ("all_recipes", None),
    ("page", 0),
    ("selected_recipe", None),
    ("recipe_response", None),
    ("substitution_response", None),
    ("serving_choice", None),
    ("user_query", ""),
    ("rated", False),
]:
    if key not in st.session_state:
        st.session_state[key] = default


def reset() -> None:
    st.session_state.all_recipes = None
    st.session_state.page = 0
    st.session_state.substitution_response = None
    st.session_state.serving_choice = None
    st.session_state.selected_recipe = None
    st.session_state.recipe_response = None
    st.session_state.user_query = ""
    st.session_state.rated = False


def star_display(avg: float) -> str:
    filled = round(avg)
    return "⭐" * filled + "☆" * (5 - filled)


# Step 1: Ingredient input
if st.session_state.all_recipes is None:
    st.title("Scraps to Snacks")
    st.caption("Tell me what ingredients or leftovers you have and I'll find you a recipe.")

    with st.form("search_form"):
        query = st.text_input("What ingredients do you have?", placeholder="e.g. milk, eggs, bread")
        submitted = st.form_submit_button("Find Recipes", use_container_width=True)

    if submitted and query.strip():
        with st.spinner("Searching recipes..."):
            try:
                recipes = client.search_recipes(query.strip(), limit=20)
                if not recipes:
                    st.warning("No recipes found. Try different ingredients.")
                else:
                    st.session_state.all_recipes = sorted(
                        recipes, key=lambda r: r.get("totalTime") or 9999
                    )
                    st.session_state.user_query = query.strip()
                    st.session_state.page = 0
                    st.rerun()
            except Exception as exc:
                st.error(f"Error: {exc}")

# Step 2: Recipe list with pagination
elif st.session_state.selected_recipe is None:
    all_recipes = st.session_state.all_recipes
    page = st.session_state.page
    total = len(all_recipes)
    page_recipes = all_recipes[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    has_next = (page + 1) * PAGE_SIZE < total

    start = page * PAGE_SIZE + 1
    end = min(start + PAGE_SIZE - 1, total)

    st.title("Scraps to Snacks")
    st.subheader(f"Recipes {start}–{end} of {total}")
    st.caption(f'Results for: *"{st.session_state.user_query}"*')

    for i, recipe in enumerate(page_recipes):
        label = recipe.get("label", "Unknown")
        source = recipe.get("source", "")
        total_time = recipe.get("totalTime")
        time_text = f"{total_time} min" if total_time else "Time N/A"
        main_ingredients = ", ".join(recipe.get("mainIngredients", [])[:3]) or "—"
        calories = round(recipe.get("calories", 0))
        cautions = [c for c in recipe.get("cautions", []) if c.upper() != "SULFITES"]
        url = recipe.get("url", "")
        avg = get_average(url)
        count = get_count(url)
        rating_text = f"{star_display(avg)} ({count} review{'s' if count != 1 else ''})" if count else "No reviews yet"

        with st.container(border=True):
            col_info, col_btn = st.columns([4, 1])
            with col_info:
                st.markdown(f"**{label}** — {source}")
                st.caption(f"Main ingredients: {main_ingredients}  |  {time_text}  |  ~{calories} kcal")
                st.caption(rating_text)
                if cautions:
                    st.warning(f"Allergen cautions: {', '.join(cautions)}", icon="⚠️")
            with col_btn:
                if st.button("Select", key=f"select_{page}_{i}_{label}"):
                    st.session_state.selected_recipe = recipe
                    st.session_state.rated = False
                    st.rerun()

    st.divider()
    col_back, col_next, col_new = st.columns(3)
    with col_back:
        if page > 0:
            if st.button("← Back Page", use_container_width=True):
                st.session_state.page -= 1
                st.rerun()
    with col_next:
        if has_next:
            if st.button("Next Page →", use_container_width=True):
                st.session_state.page += 1
                st.rerun()
    with col_new:
        if st.button("New Search", use_container_width=True):
            reset()
            st.rerun()

    # Scroll to top button fixed at bottom right
    st.html("""
        <style>
            #scroll-top-btn {
                position: fixed;
                bottom: 2rem;
                right: 2rem;
                background-color: #ff4b4b;
                color: white;
                border: none;
                border-radius: 50%;
                width: 48px;
                height: 48px;
                font-size: 22px;
                cursor: pointer;
                box-shadow: 0 2px 8px rgba(0,0,0,0.3);
                z-index: 9999;
            }
            #scroll-top-btn:hover { background-color: #cc0000; }
        </style>
        <button id="scroll-top-btn" onclick="window.parent.scrollTo({top:0,behavior:'smooth'})">↑</button>
    """)

# Step 3: Generate and show the recipe
else:
    selected = st.session_state.selected_recipe
    st.title(selected.get("label", "Recipe"))

    # Serving size slider
    original_servings = int(selected.get("yield") or 2)
    slider_options = [1, 2, 4, 6, 8]

    if st.session_state.serving_choice is None:
        st.session_state.serving_choice = original_servings if original_servings in slider_options else 2

    chosen = st.select_slider(
        "Serving size:",
        options=slider_options,
        value=st.session_state.serving_choice,
        format_func=lambda x: "Solo (1)" if x == 1 else f"Serves {x}",
    )

    if chosen != st.session_state.serving_choice:
        st.session_state.serving_choice = chosen
        st.session_state.recipe_response = None
        st.rerun()

    target_servings = chosen if chosen != original_servings else None

    # Generate recipe
    if st.session_state.recipe_response is None:
        with st.spinner("Generating recipe..."):
            try:
                response = generate_recipe_response(
                    selected,
                    st.session_state.user_query,
                    target_servings=target_servings,
                )
                st.session_state.recipe_response = response
            except Exception as exc:
                st.error(f"Error generating recipe: {exc}")
                st.stop()
        st.rerun()

    st.markdown(st.session_state.recipe_response)
    st.divider()

    # Nutrition & allergen info
    calories = round(selected.get("calories", 0))
    servings = selected.get("yield") or 1
    cal_per_serving = round(calories / servings) if servings else calories
    diet_labels = selected.get("dietLabels", [])
    cautions = [c for c in selected.get("cautions", []) if c.upper() != "SULFITES"]

    allergy_keywords = {"free", "vegan", "vegetarian", "kosher", "halal"}
    allergy_labels = [
        h for h in selected.get("healthLabels", [])
        if any(kw in h.lower() for kw in allergy_keywords)
    ]

    st.subheader("Nutrition & Allergen Info")
    col1, col2, col3 = st.columns(3)
    col1.metric("Calories (total)", f"{calories} kcal")
    col2.metric("Per serving", f"{cal_per_serving} kcal")
    col3.metric("Servings", servings)

    if diet_labels:
        st.markdown("**Diet labels:** " + "  ".join(f"`{d}`" for d in diet_labels))
    if allergy_labels:
        st.markdown("**Safe for:** " + "  ".join(f"`{h}`" for h in allergy_labels))
    if cautions:
        st.error("**Allergen cautions:** " + ", ".join(cautions), icon="⚠️")
    else:
        st.success("No allergen cautions listed for this recipe.", icon="✅")

    st.divider()

    # Substitution box
    st.subheader("Missing an ingredient?")
    with st.form("substitution_form"):
        missing_input = st.text_input(
            "What are you missing?",
            placeholder="e.g. butter, eggs, milk",
        )
        sub_submitted = st.form_submit_button("Get Substitutes", use_container_width=True)

    if sub_submitted and missing_input.strip():
        missing = [i.strip() for i in missing_input.replace(" and ", ",").split(",") if i.strip()]
        with st.spinner("Finding substitutes..."):
            try:
                advice = get_substitution_advice(selected, missing)
                st.session_state.substitution_response = advice
            except Exception as exc:
                st.error(f"Could not get substitution advice: {exc}")
        st.rerun()

    if st.session_state.substitution_response:
        st.info(st.session_state.substitution_response)

    st.divider()

    # Rating widget
    st.subheader("Rate this recipe")
    url = selected.get("url", "")
    avg = get_average(url)
    count = get_count(url)
    if count:
        st.caption(f"Current rating: {star_display(avg)} — {avg:.1f}/5 from {count} review{'s' if count != 1 else ''}")

    if not st.session_state.rated:
        stars = st.select_slider(
            "Your rating:",
            options=[1, 2, 3, 4, 5],
            format_func=lambda x: "⭐" * x,
        )
        if st.button("Submit Rating"):
            save_rating(url, stars)
            st.session_state.rated = True
            st.rerun()
    else:
        st.success("Thanks for your rating! It will influence future search rankings.", icon="✅")

    st.divider()
    if st.button("New Search", use_container_width=True):
        reset()
        st.rerun()
