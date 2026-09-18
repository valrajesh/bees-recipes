"""HTML content extraction and sanitization utility for LLM recipe extraction."""

import re
from bs4 import BeautifulSoup
from app.utils.logger import logger


def clean_html_for_llm(html_content: str, max_chars: int = 15000) -> str:
    """Strips boilerplate, scripts, styles, and navigation tags from HTML.
    
    Extracts high-density recipe text and metadata to minimize token usage
    and maximize extraction accuracy for Azure OpenAI.
    """
    if not html_content or not html_content.strip():
        return ""

    try:
        soup = BeautifulSoup(html_content, "html.parser")

        # Extract title and OpenGraph metadata
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()

        meta_desc = ""
        og_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
        if og_desc and og_desc.get("content"):
            meta_desc = og_desc["content"].strip()

        # Remove irrelevant noise elements
        noise_selectors = [
            "script", "style", "nav", "footer", "header", "aside", "noscript",
            "iframe", "svg", "form", "button", "input", ".ad", ".advertisement",
            ".sidebar", ".cookie-banner", ".popup", ".social-share", ".newsletter-signup"
        ]
        for tag in soup.find_all(noise_selectors):
            tag.decompose()

        # Look for targeted recipe containers if present
        recipe_container = (
            soup.find(attrs={"itemtype": re.compile(r"schema\.org/Recipe", re.I)})
            or soup.find(class_=re.compile(r"recipe|wprm-recipe|tasty-recipes|easyrecipe", re.I))
            or soup.find("article")
            or soup.find("main")
            or soup.body
        )

        target = recipe_container if recipe_container else soup

        # Extract clean text preserving structural line breaks
        lines = []
        if title:
            lines.append(f"Title: {title}")
        if meta_desc:
            lines.append(f"Description: {meta_desc}\n")

        # Iterate over text blocks
        for element in target.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "span", "div"]):
            text = element.get_text(separator=" ", strip=True)
            if text and len(text) > 2:
                # Add bullet for list items to assist LLM step parsing
                if element.name == "li":
                    lines.append(f"- {text}")
                elif element.name in ["h1", "h2", "h3", "h4"]:
                    lines.append(f"\n### {text}\n")
                else:
                    lines.append(text)

        raw_text = "\n".join(lines)

        # De-duplicate excessive newlines and spaces
        cleaned = re.sub(r"\n{3,}", "\n\n", raw_text)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()

        # Trim safely to token window
        if len(cleaned) > max_chars:
            cleaned = cleaned[:max_chars] + "\n\n[Content truncated for length...]"

        return cleaned

    except Exception as e:
        logger.warning(f"Error cleaning HTML: {e}. Falling back to basic text extraction.")
        # Fallback to basic regex stripping
        clean_text = re.sub(r"<[^>]+>", " ", html_content)
        clean_text = re.sub(r"\s+", " ", clean_text).strip()
        return clean_text[:max_chars]
