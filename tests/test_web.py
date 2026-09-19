"""Unit tests for Web extractor and HTML cleaner."""

from unittest.mock import AsyncMock, patch
import pytest
from app.schemas.recipe import IngredientModel, InstructionModel, LLMRecipeExtraction, LocalizedText
from app.services.extractors.web import WebExtractor
from app.services.llm_service import llm_service
from app.utils.html_cleaner import clean_html_for_llm


@pytest.fixture
def web_extractor():
    return WebExtractor()


def test_web_url_detection(web_extractor):
    assert web_extractor.can_handle("https://plantbasedjuniors.com/lemon-chia-chickpea-balls/") is True
    assert web_extractor.can_handle("http://allrecipes.com/recipe/12345") is True
    assert web_extractor.can_handle("ftp://files.com/recipe.txt") is False


def test_ingredient_line_parsing(web_extractor):
    ing1 = web_extractor._parse_ingredient_line("1 can (15 oz) chickpeas, drained")
    assert ing1.amount == 1.0
    assert ing1.unit.singular == "can"
    assert "chickpeas" in ing1.name.singular

    ing2 = web_extractor._parse_ingredient_line("2 tbsp chia seeds")
    assert ing2.amount == 2.0
    assert ing2.unit.singular == "tbsp"
    assert "chia seeds" in ing2.name.singular

    ing3 = web_extractor._parse_ingredient_line("1/2 cup pure maple syrup")
    assert ing3.amount == 0.5
    assert ing3.unit.singular == "cup"
    assert "pure maple syrup" in ing3.name.singular


def test_instruction_steps_parsing(web_extractor):
    raw_instructions = [
        "1. Place all ingredients into food processor.",
        "Step 2: Pulse until combined.",
        "Roll into balls and chill."
    ]
    steps = web_extractor._parse_instructions(raw_instructions)
    assert len(steps) == 3
    assert steps[0].description == "Place all ingredients into food processor."
    assert steps[1].description == "Pulse until combined."
    assert steps[2].description == "Roll into balls and chill."


def test_html_cleaner():
    sample_html = """
    <html>
      <head>
        <title>Delicious Lemon Balls</title>
        <meta name="description" content="Quick vegan protein snack.">
        <script>console.log('tracking');</script>
        <style>.hide { display: none; }</style>
      </head>
      <body>
        <nav><a href="/">Home</a></nav>
        <div class="sidebar">Sidebar ad</div>
        <article>
          <h1>Lemon Balls</h1>
          <ul>
            <li>1 can chickpeas</li>
            <li>2 tbsp chia seeds</li>
          </ul>
          <p>Pulse in a food processor until smooth.</p>
        </article>
        <footer>Copyright 2026</footer>
      </body>
    </html>
    """
    cleaned = clean_html_for_llm(sample_html)
    assert "Delicious Lemon Balls" in cleaned
    assert "1 can chickpeas" in cleaned
    assert "tracking" not in cleaned
    assert "Sidebar ad" not in cleaned
    assert "Copyright" not in cleaned


@pytest.mark.asyncio
async def test_web_llm_fallback_retries_title_when_core_fields_empty(web_extractor):
    html = """
    <html>
      <head><title>Cabbage Carbonara</title></head>
      <body><main><p>This page requires JavaScript.</p></main></body>
    </html>
    """
    incomplete = LLMRecipeExtraction(
        name="Cabbage Carbonara",
        instructions=[],
        ingredients=[],
    )
    complete = LLMRecipeExtraction(
        name="Cabbage Carbonara",
        instructions=[InstructionModel(title="", description="Roast cabbage and mix with sauce.", ingredients=[])],
        ingredients=[IngredientModel(amount=1.0, name=LocalizedText(singular="cabbage", plural="cabbages"))],
    )

    with patch.object(web_extractor, "_fetch_html", return_value=html), patch(
        "app.services.extractors.web.scrape_html",
        side_effect=Exception("schema missing")
    ), patch.object(
        llm_service,
        "extract_recipe_structured_async",
        new=AsyncMock(side_effect=[incomplete, complete])
    ) as mock_extract:
        response = await web_extractor.extract_recipe("https://example.com/cabbage-carbonara")

    assert mock_extract.await_count == 2
    retry_text = mock_extract.await_args_list[1].args[0]
    assert "RECIPE TITLE OR PAGE TITLE: Cabbage Carbonara" in retry_text
    assert response.recipeDetail.extractionMethod == "llm_title_inferred"
    assert len(response.recipeDetail.ingredients) == 1
    assert len(response.recipeDetail.instructions) == 1
