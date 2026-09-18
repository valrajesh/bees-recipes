"""Unit tests for Web extractor and HTML cleaner."""

import pytest
from app.services.extractors.web import WebExtractor
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
