# CliniFact — Medical Research Assistant

A web-based AI chatbot that helps users search clinical trials and explore FDA drug information through natural language queries.

## Features

### 🧪 Clinical Trials
- Search by condition, phase, status, sponsor, location, intervention, and more
- Filter by enrollment, age group, sex, funder type, and date range
- Look up a specific study by NCT ID
- Server-side pagination — finds up to 100 results, shows 5 at a time

### 💊 FDA Drug Labels (Drugs@FDA)
- Search drug labels by brand name, generic name, or free text
- View indications, warnings, boxed warnings, dosage, side effects, and interactions
- Covers prescription, OTC, and veterinary drugs

### 📰 FDA Press Announcements
- Fetch the latest FDA press releases and "What's New: Drugs" feed
- Filter by keyword and date range
- Covers drug approvals, safety alerts, guidance documents, and policy news

### 📄 FDA Complete Response Letters (CRL)
- Search CRLs by company, application number, approval status, year, or keyword
- Automatic company alias resolution (e.g. Roche → Genentech)
- Dataset covers ~439 CRLs from 2002–2026

### General
- Natural language interface powered by GPT-4o
- Multi-agent orchestration (LangGraph) — routes each query to the right specialist agent
- Session-based conversation history
- Modern, responsive web interface

---

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Up Environment Variables

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=your_openai_api_key_here
```

### 3. Run the Application

```bash
python app.py
```

The server starts on `http://localhost:5001` (port 5001 avoids macOS AirPlay conflict on port 5000).

### 4. Open the Web Interface

```
http://localhost:5001
```

---

## Example Queries

### Clinical Trials
- "Find phase 3 breast cancer studies from Roche"
- "Are there recruiting diabetes trials in New York?"
- "Find Alzheimer's trials started in the last 6 months"
- "What is the enrollment number for NCT02586025?"
- "Show me pediatric oncology trials sponsored by NIH"

### FDA Drug Labels
- "What are the side effects and warnings for Humira?"
- "What is trastuzumab used for?"
- "Find FDA label information for Advil"
- "Search for prescription diabetes medications"

### FDA Press Announcements
- "What has the FDA announced this month?"
- "Any recent FDA cancer drug approvals?"
- "Show me FDA safety alerts from the last 3 months"

### Complete Response Letters
- "Show me Pfizer's complete response letters"
- "Which drugs were not approved by the FDA in 2024?"
- "Find CRLs mentioning manufacturing deficiencies"
- "Show me Roche's complete response letters"

---

## API Endpoints

### `POST /api/chat`
Send a message to the chatbot.

**Request:**
```json
{
  "message": "Find phase 3 breast cancer studies from Roche",
  "session_id": "session_1234567890",
  "mode": "default"
}
```

**Response:**
```json
{
  "response": "Found 12 clinical trials...",
  "session_id": "session_1234567890",
  "mode": "default"
}
```

### `POST /api/clear`
Clear conversation history for a session.

```json
{ "session_id": "session_1234567890" }
```

### `GET /api/health`
Check server health.

---

## Project Structure

```
ClinInfo/
├── app.py                          # Flask server (routes, session management)
├── main.py                         # All agent logic, tools, and LangGraph graph
├── prompts/
│   ├── orchestrator.txt            # Routing agent prompt
│   ├── trials_agent.txt            # Clinical trials agent prompt
│   ├── drugs_agent.txt             # FDA drugs/news/CRL agent prompt
│   ├── detail_agent.txt            # Single-trial detail agent prompt
│   └── chat_agent.txt              # General chat agent prompt
├── static/
│   ├── index.html                  # Frontend HTML
│   ├── style.css                   # Styling
│   └── script.js                   # Frontend JavaScript
├── clinicaltrials_api_schema.md    # ClinicalTrials.gov API reference
├── clinicaltrials_api_schema.json  # ClinicalTrials.gov API schema (JSON)
├── fda_api_schema.md               # FDA APIs reference (RSS, Drug Label, CRL)
├── fda_api_schema.json             # FDA APIs schema (JSON)
├── requirements.txt                # Python dependencies
├── .env                            # Environment variables (create this)
└── README.md                       # This file
```

---

## Architecture

```
User Message
     │
     ▼
Orchestrator Agent  ──routes to──▶  trials agent   → ClinicalTrials.gov API
  (GPT-4o)                      ├─▶  drugs agent    → openFDA Drug Label API
                                 │                  → FDA RSS feeds
                                 │                  → openFDA CRL API
                                 ├─▶  detail agent   → ClinicalTrials.gov (single study)
                                 └─▶  chat agent     → general conversation
```

Each specialist agent has access to dedicated tools and a prompt tuned to its domain. Results are cached server-side (UUID key) so users can paginate through large result sets.

---

## Technologies

| Layer | Tech |
|---|---|
| Backend | Python 3, Flask, Flask-CORS |
| AI Orchestration | LangGraph, LangChain |
| LLM | OpenAI GPT-4o |
| Frontend | HTML5, CSS3, Vanilla JavaScript |
| APIs | ClinicalTrials.gov v2, openFDA Drug Label, openFDA CRL, FDA RSS |

---

## Troubleshooting

### Server won't start
- Ensure `OPENAI_API_KEY` is set in `.env`
- Run `pip install -r requirements.txt` to install all dependencies
- Make sure port 5001 is not already in use

### No results found for clinical trials
- Try broadening the search (remove phase/status filters)
- Check spelling of the condition name
- Some very specific combinations may return 0 results from the API

### FDA CRL shows wrong company
- The CRL database stores the exact NDA/BLA applicant name (usually a subsidiary). For example, Roche filings appear under "Genentech". The app automatically resolves common aliases — if yours is missing, try searching by the subsidiary name directly.

### OpenAI API errors
- Verify your API key in `.env`
- Check you have sufficient API credits

---

## License

This project is for educational purposes.
