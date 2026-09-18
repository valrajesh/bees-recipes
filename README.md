# BEES-Recipes Extraction API 🐝🍳

Production-ready, high-performance FastAPI service that accepts URLs from multiple platforms (**Standard Web Pages**, **YouTube Videos/Shorts**, and **Instagram Posts/Reels**) and produces normalized, structured JSON recipes containing granular ingredients and ordered step-by-step instructions.

---

## 🌟 Key Features

1. **Multi-Platform URL Extractor Routing**:
   - **YouTube URLs (`youtube.com`, `youtu.be`)**: Extracts video ID, fetches transcripts/subtitles via `youtube-transcript-api` (supporting manual, auto-generated, and translated transcripts), retrieves video metadata/description fallback via oEmbed and page DOM, and feeds text into Azure OpenAI Structured Outputs.
   - **Instagram URLs (`instagram.com/p/`, `instagram.com/reel/`)**: Extracts shortcode, retrieves post/reel caption via social crawler OpenGraph and `instaloader` fallback, and parses recipe details with Azure OpenAI Structured Outputs.
   - **Facebook URLs (`facebook.com`, `fb.watch`)**: Extracts post/reel captions and OpenGraph metadata from Facebook posts and feeds text into Azure OpenAI Structured Outputs.
   - **TikTok URLs (`tiktok.com/@user/video/`, `vm.tiktok.com`, `vt.tiktok.com`)**: Extracts video caption and metadata via official oEmbed API and OpenGraph social crawlers, structured with Azure OpenAI.
   - **Standard Web URLs**: Dual-pipeline extraction:
     - **Fast-Path**: High-speed Schema.org JSON-LD parsing via `recipe-scrapers`.
     - **Intelligent Fallback**: DOM sanitization (stripping scripts, ads, menus, styles) + LLM extraction via Azure OpenAI Structured Outputs.
2. **Structured Outputs with Azure OpenAI**:
   - Uses `openai.AzureOpenAI` with `client.beta.chat.completions.parse()` enforcing strict Pydantic models.
   - Outputs standardized ingredients (`amount`, `unit`, `name`, `notes`, `original_text`), numbered instructions, prep/cook/total times, servings, cuisine, category, nutrition, and chef's tips.
3. **Azure Cosmos DB Persistence**:
   - Automatically stores extracted structured recipes in Azure Cosmos DB (`recipes_db` / `recipes` container).
   - Generates deterministic, queryable document IDs (`rec_<hash>`), partitioned by `/source_type`.
   - Supports Managed Identity (`DefaultAzureCredential`) or standard primary key authentication.
   - Provides endpoints to list and retrieve stored recipes.
4. **Enterprise APIM & Azure OpenAI Support**:
   - Compatible with direct Azure OpenAI endpoints and enterprise API Management (APIM) gateways.
   - Supports APIM subscription key headers and environment variable aliases matching internal Bees services (`AZUREOPENAI_APIM_API_ENDPOINT`, `AZUREOPENAI_APIM_API_KEY`, etc.).
5. **Asynchronous & Non-Blocking**:
   - I/O scraping, Cosmos DB persistence, and OpenAI calls are safely dispatched to thread pools to maintain non-blocking FastAPI concurrency.

---

## 🏗️ Project Structure

```
bees-recipes/
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI application factory & middleware
│   ├── config.py                   # Environment settings & Azure OpenAI configuration
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── recipe.py               # Pydantic data models (Request, Response, LLM Schemas)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── llm_service.py          # Azure OpenAI client using parse() structured outputs
│   │   ├── extractor_router.py     # Router dispatching URLs to platform extractors
│   │   └── extractors/
│   │       ├── __init__.py
│   │       ├── base.py             # BaseExtractor interface
│   │       ├── youtube.py          # YouTube video & shorts transcript extractor
│   │       ├── instagram.py        # Instagram post & reel caption extractor
│   │       └── web.py              # Web page Schema.org scraper & LLM fallback
│   ├── api/
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       └── endpoints.py        # /extract-recipe, /supported-platforms, /health
│   └── utils/
│       ├── __init__.py
│       ├── logger.py               # Structured logging
│       └── html_cleaner.py         # Token-saving HTML sanitization
├── tests/
│   ├── test_schemas.py             # Validation of Pydantic models
│   ├── test_youtube.py             # YouTube extractor unit tests
│   ├── test_instagram.py           # Instagram extractor unit tests
│   ├── test_web.py                 # Web scraper and HTML cleaner tests
│   └── test_api.py                 # FastAPI endpoint integration tests
├── .env.example                    # Environment configuration template
├── requirements.txt                # Production & test dependencies
├── main.py                         # Root execution entrypoint
└── README.md
```

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.10+
- Azure OpenAI instance (with `gpt-4o` deployment) or APIM gateway

### 2. Environment Setup

```bash
# Clone and enter directory
cd bees-recipes

# Create virtual environment
python -m venv venv

# Activate virtual environment (Windows PowerShell)
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure `.env`

Copy `.env.example` to `.env` and fill in your Azure OpenAI / APIM details:

```env
AZURE_OPENAI_ENDPOINT=https://your-resource-name.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key-here
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o
AZURE_OPENAI_API_VERSION=2024-08-01-preview
```

*(Alternatively, APIM environment variables `AZUREOPENAI_APIM_API_ENDPOINT`, `AZUREOPENAI_APIM_API_KEY`, `AZUREOPENAI_API_LLM` are supported out-of-the-box).*

### 4. Run the API Server

```bash
python main.py
# or
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Interactive Swagger documentation is available at:
👉 **`http://localhost:8000/docs`**

---

## 📡 API Endpoints

### 1. Extract Recipe
`POST /api/v1/extract-recipe`

**Request Body:**
```json
{
  "url": "https://plantbasedjuniors.com/lemon-chia-chickpea-balls/",
  "force_llm": false
}
```

**YouTube Example:**
```json
{
  "url": "https://www.youtube.com/shorts/h8MHptcwKwk"
}
```

**Instagram Example:**
```json
{
  "url": "https://www.instagram.com/reel/C1234567890/"
}
```

**Response Payload (`200 OK`):**
```json
{
  "success": true,
  "title": "Lemon Chia Chickpea Balls",
  "description": "Zesty, no-bake energy balls packed with protein and fiber.",
  "source_url": "https://plantbasedjuniors.com/lemon-chia-chickpea-balls/",
  "source_type": "web",
  "extraction_method": "schema_scraper",
  "cuisine": "American",
  "category": "Snack",
  "servings": "14 balls",
  "prep_time_minutes": 15,
  "cook_time_minutes": 0,
  "total_time_minutes": 15,
  "difficulty": "Easy",
  "ingredients": [
    {
      "name": "chickpeas",
      "amount": 1.0,
      "unit": "can",
      "notes": "drained and rinsed (15 oz)",
      "original_text": "1 can chickpeas, drained and rinsed"
    },
    {
      "name": "chia seeds",
      "amount": 2.0,
      "unit": "tbsp",
      "notes": null,
      "original_text": "2 tbsp chia seeds"
    },
    {
      "name": "lemon zest",
      "amount": 1.0,
      "unit": "tbsp",
      "notes": "from fresh organic lemon",
      "original_text": "1 tbsp lemon zest"
    },
    {
      "name": "pure maple syrup",
      "amount": 0.25,
      "unit": "cup",
      "notes": null,
      "original_text": "1/4 cup pure maple syrup"
    }
  ],
  "instructions": [
    {
      "step_number": 1,
      "instruction": "Add all ingredients into a high-speed food processor.",
      "timer_minutes": null,
      "ingredients_used": ["chickpeas", "chia seeds", "lemon zest", "pure maple syrup"]
    },
    {
      "step_number": 2,
      "instruction": "Pulse until a uniform dough-like consistency is achieved.",
      "timer_minutes": 2,
      "ingredients_used": []
    },
    {
      "step_number": 3,
      "instruction": "Roll into 14 bite-sized balls and refrigerate for at least 30 minutes before serving.",
      "timer_minutes": 30,
      "ingredients_used": []
    }
  ],
  "nutrition": {
    "calories": 95,
    "protein_g": 3.2,
    "carbohydrates_g": 14.5,
    "fat_g": 2.1,
    "fiber_g": 2.8,
    "sugar_g": 4.0,
    "serving_size": "1 ball"
  },
  "tips_and_notes": [
    "Store in an airtight container in the refrigerator for up to 1 week, or freeze up to 3 months."
  ],
  "substitutions": [
    "Maple syrup can be replaced with honey or agave nectar."
  ],
  "raw_ingredients_text": [
    "1 can chickpeas, drained and rinsed",
    "2 tbsp chia seeds",
    "1 tbsp lemon zest",
    "1/4 cup pure maple syrup"
  ],
  "raw_instructions_text": [
    "1. Add all ingredients into a high-speed food processor.",
    "2. Pulse until a uniform dough-like consistency is achieved.",
    "3. Roll into 14 bite-sized balls and refrigerate for at least 30 minutes before serving."
  ],
  "extracted_at": "2026-09-17T12:00:00.000000+00:00"
}
```

---

### 2. Supported Platforms
`GET /api/v1/supported-platforms`

Returns the capabilities and supported regex structures for all integrated platforms.

---

### 3. Health Check
`GET /health` or `GET /api/v1/health`

Returns service status and Azure OpenAI connectivity status.

---

## 🧪 Running Tests

Run the full automated test suite with `pytest`:

```bash
pytest -v
```

---

## 🛡️ Error Handling & Status Codes

| Status Code | Meaning | Example Scenario |
|---|---|---|
| **200 OK** | Success | Recipe successfully scraped and formatted |
| **400 Bad Request** | Invalid Input | Malformed URL or non-supported format |
| **422 Unprocessable** | Content Unavailable | YouTube video has disabled captions; Instagram post is private |
| **502 Bad Gateway** | Upstream Error | Azure OpenAI authentication failure or network connectivity issue |
| **500 Internal Error** | Server Error | Unhandled server error |
