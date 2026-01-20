# Clinical Trials Assistant Chatbot

A web-based chatbot that helps users search for clinical trials from ClinicalTrials.gov using natural language queries.

## Features

- 🔍 Search clinical trials by condition, phase, status, location, and more
- 💬 Natural language interface
- 📅 Date-based filtering (recent, last month, etc.)
- 🎨 Modern, responsive web interface
- 🔄 Session-based conversation history

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

#### Option 1: Run with Flask (Recommended)

```bash
python app.py
```

The server will start on `http://localhost:5001` (default port changed to avoid macOS AirPlay conflict)

#### Option 2: Run the CLI version

```bash
python main.py
```

### 4. Access the Web Interface

Open your browser and navigate to:
```
http://localhost:5001
```

**Note:** The default port is 5001 to avoid conflicts with macOS AirPlay Receiver (which uses port 5000). You can change the port by setting the `PORT` environment variable.

## Usage

### Web Interface

1. Open the web interface in your browser
2. Type your question in the input box (e.g., "Find phase 3 breast cancer studies")
3. Click send or press Enter
4. The chatbot will search ClinicalTrials.gov and return relevant trials

### Example Queries

- "Find phase 3 breast cancer studies"
- "Are there recruiting diabetes trials?"
- "Find recent cancer trials from the last month"
- "Search for Alzheimer's trials in New York"
- "Find adult clinical trials for diabetes"

## API Endpoints

### POST `/api/chat`
Send a message to the chatbot.

**Request:**
```json
{
  "message": "Find phase 3 breast cancer studies",
  "session_id": "session_1234567890"
}
```

**Response:**
```json
{
  "response": "Found 5 clinical trials for 'breast cancer'...",
  "session_id": "session_1234567890"
}
```

### POST `/api/clear`
Clear conversation history for a session.

**Request:**
```json
{
  "session_id": "session_1234567890"
}
```

### GET `/api/health`
Check API health status.

## Project Structure

```
Project/
├── app.py                 # Flask API server
├── main.py               # Chatbot logic and LangGraph setup
├── static/
│   ├── index.html        # Frontend HTML
│   ├── style.css         # Styling
│   └── script.js         # Frontend JavaScript
├── requirements.txt       # Python dependencies
├── .env                  # Environment variables (create this)
└── README.md            # This file
```

## Technologies Used

- **Backend**: Python, Flask, LangChain, LangGraph, OpenAI
- **Frontend**: HTML5, CSS3, JavaScript (Vanilla)
- **API**: ClinicalTrials.gov API v2

## Notes

- The chatbot uses OpenAI's GPT-4o model
- Clinical trials data is fetched from ClinicalTrials.gov API v2
- Some filters (phase, status) are applied client-side as the API doesn't support all query parameters
- The web interface uses session-based conversation history

## Troubleshooting

### API Connection Issues
- Make sure the Flask server is running (`python app.py`)
- Check that the API URL in `script.js` matches your server address
- Verify CORS is enabled in `app.py`

### OpenAI API Errors
- Check that your `OPENAI_API_KEY` is set correctly in `.env`
- Verify you have sufficient API credits

### No Results Found
- Try broadening your search (remove filters)
- Check that the condition name is spelled correctly
- Some filters may be too restrictive

## License

This project is for educational purposes.

