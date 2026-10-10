# ConceptBridge — AI-Powered Learning Platform

ConceptBridge is an AI-powered learning application designed to help learners understand concepts, connect related ideas, and improve through adaptive practice.

Instead of stopping at an explanation, ConceptBridge generates learning content, evaluates answers, and provides feedback with follow-up challenges.

## Features

- **AI-Generated Lessons:** Generate lessons on a chosen topic at Beginner, Intermediate, or Advanced level.
- **Concept Connections:** Explore relationships between concepts through visual diagrams.
- **Adaptive Practice:** Submit answers to challenges and receive AI-generated feedback.
- **Follow-up Challenges:** Practice further based on the evaluation of your previous answer.
- **Learning Progress:** View recent activity and topics due for review.
- **Local Data Storage:** Store generated lessons and practice attempts in an SQLite database.

## Tech Stack

- Python
- Streamlit
- Google Gen AI SDK (Gemini)
- Pydantic
- SQLite
- Mermaid.js for concept diagrams

## Getting Started

### Prerequisites

- Python installed on your computer
- A Google Gemini API key
- Internet access for AI requests and externally loaded resources

### 1. Clone the Repository

```bash
git clone https://github.com/shreshtaparshi/ConceptBridge.git
cd ConceptBridge
```

### 2. Create a Virtual Environment

```bash
python -m venv .venv
```

Activate it in Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure the Gemini API Key

Create a folder named `.streamlit` in the project directory if it does not already exist. Inside it, create a file named `secrets.toml`.

Add the following line:

```toml
GEMINI_API_KEY = "your_gemini_api_key_here"
```

Replace the placeholder with your own API key.

**Security:** Never commit or publish your actual API key. The local secrets file is excluded through `.gitignore`.

### 5. Run the Application

```bash
streamlit run app.py
```

Streamlit will provide a local URL where you can open ConceptBridge in your browser.

## Data Storage

ConceptBridge uses SQLite to store lessons and practice attempts locally in `conceptbridge.db`. This database file is excluded from Git.

## Notes

- AI lesson generation and answer evaluation require a valid API key, network access, and an available Gemini model with sufficient quota.
- Concept diagrams and some cover images rely on external online resources.
- This project is under development, and AI responses may vary depending on model availability.

## Author

Developed by **Shreshta Parshi**.
