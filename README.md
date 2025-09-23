# Resume Analyzer REST API

Production-ready REST API for PDF resume analysis and document classification using OpenAI.

## Features
- Single and batch prompt extraction
- Document classification (resume likelihood, toxicity)
- Hybrid prompt system (custom prompts + templates)
- Parallel processing with 250ms staggered starts
- Rate limiting (per API key and per user, configurable via `config.py`)
- Job tracking with progress monitoring
- Automatic cleanup after 60 minutes (database + per-request logs)

## Quick Start

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

   > Most runtime defaults are defined in `app/config.py`.  
   > Environment variables can override them.

3. **Prepare prompts**
   ```bash
   mkdir -p prompts
   # Add your template files inside `prompts/`
   ```

4. **Run the API**
   ```bash
   # Development (reload enabled)
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

   # Production (uses __main__ guard in app/main.py)
   python -m app.main
   ```

   On startup (`main.py`), the following happens automatically:
   - SQLite database initialized (`init_database`)
   - Cleanup schedulers started (`start_cleanup_scheduler`, `start_prl_cleanup_scheduler`)

5. **Explore the API**
   - Interactive Swagger docs: [http://localhost:8000/docs](http://localhost:8000/docs)
   - Health check: [http://localhost:8000/health](http://localhost:8000/health)

## API Endpoints

- `POST /extract/single` – Single prompt extraction
- `POST /extract/batch` – Batch parallel extraction
- `POST /classify` – Document classification
- `GET /jobs/{job_id}` – Job status
- `GET /jobs/{job_id}/result` – Job results
- `GET /health` – Health check
- `GET /` – Root endpoint (API version info)

## Configuration

Runtime settings are controlled via two layers:
1. **Environment variables** (see `.env.example` for supported values)
2. **Defaults in `app/config.py`**

Examples of configurable settings:
- `DATABASE_URL` – SQLite path (default `resume_analyzer.db`)
- `OPENAI_RPM_PER_KEY` – Requests per minute limit per API key (default `480`)
- `OPENAI_RPM_FAIL_FAST` – Fail fast on limit (`1`) or block until free (`0`)
- `OPENAI_RPM_MAX_DELAY_MS` – Maximum blocking delay (default 3600000 ms = 1h)
- `OPENAI_MAX_CONCURRENCY_PER_KEY` – Cap concurrent requests (default `20`)
- `OPENAI_REDIS_URL` – Optional Redis URL for distributed rate limiting
