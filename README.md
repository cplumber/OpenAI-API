# Resume Analyzer REST API

Production-ready REST API for PDF resume analysis and document classification using OpenAI.

## Features
- Single and batch prompt extraction
- Document classification (resume likelihood, toxicity)
- Hybrid prompt system (custom prompts + templates)
- Parallel processing with 250ms staggered starts
- Rate limiting (20 jobs/API key, 5 jobs/user)
- Job tracking with progress monitoring
- Automatic cleanup after 60 minutes

## Quick Start
1. Install dependencies:
   pip install -r requirements.txt

2. Set up environment:
   cp .env.example .env
   # Edit .env with your settings

3. Create prompts directory and add template files

4. Run the API:
   python -m app.main

## API Endpoints
- POST /extract/single - Single prompt extraction
- POST /extract/batch - Batch parallel extraction
- POST /classify - Document classification
- GET /jobs/{job_id} - Job status
- GET /jobs/{job_id}/result - Job results
- GET /health - Health check

## Documentation
Visit http://localhost:8000/docs for interactive API documentation.
