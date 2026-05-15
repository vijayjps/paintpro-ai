# Painting Company Lead Generation Agent

A fully autonomous, free multi-agent system built with CrewAI to help small painting companies generate high-quality leads.

## Features

- **Prospector Agent**: Finds potential homes needing painting services within configurable radius
- **Home Analyzer Agent**: Analyzes home exteriors and suggests optimal color schemes
- **Quote & Visual Agent**: Generates realistic quotes and AI-powered before/after images
- **Outreach Agent**: Creates personalized, value-first email campaigns
- **Multi-Provider LLM Support**: Switch between Groq, OpenAI, Anthropic, or Ollama
- **AI Image Generation**: Craiyon integration for realistic after-paint visualizations
- **Email Attachments**: Automatically includes AI-generated images in outreach emails
- **Human Approval Gate**: All emails reviewed and approved before sending
- **Web UI**: Streamlit-based interface for easy workflow management
- **Email History**: Track all previous runs and outputs
- **Geographic Targeting**: Search by location and radius for targeted lead generation

## Tech Stack

- **Framework**: CrewAI + LangChain
- **LLM Providers**: 
  - Groq (free tier - recommended)
  - OpenAI (paid)
  - Anthropic (paid)
  - Ollama (local, free)
- **Search**: DuckDuckGo Search
- **Email**: Brevo (Sendinblue, free tier - 300 emails/day)
- **Visuals**: Free AI tools (Craiyon for image generation)
- **Image Processing**: Pillow, OpenCV

## Setup Instructions

1. **Clone or Download** this project to your local machine.

2. **Install Python 3.11+** if not already installed.

3. **Create Virtual Environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

4. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
   Note: If `crewai` is not available on PyPI, install from source:
   ```bash
   pip install git+https://github.com/crewAIInc/crewAI.git
   ```

5. **Set Up Environment Variables**:
   - Copy `.env.example` to `.env`
   - Fill in your API keys based on your chosen LLM provider:
     - **Groq (FREE - Recommended)**: Get API key from [groq.com](https://groq.com)
     - **OpenAI (PAID)**: Get API key from [OpenAI](https://platform.openai.com)
     - **Anthropic (PAID)**: Get API key from [Anthropic](https://console.anthropic.com)
     - **Ollama (FREE - Local)**: Download from [ollama.ai](https://ollama.ai)
   - Get Brevo API key from [brevo.com](https://brevo.com) (free tier)
   - Verify your sender email in Brevo
   - Set your target location (e.g., "Springfield, IL")
   - See [LLM_PROVIDERS.md](LLM_PROVIDERS.md) for detailed provider setup

6. **For Visuals** (choose one):
   - **FacadeColorizer**: Web-based, no setup needed
   - **Remodel AI**: Sign up for free tier
   - **Local Stable Diffusion**: Follow instructions in `tools/visual_tools.py`

7. **Run the System**:
   - **Command Line**: `python main.py`
   - **Web UI**: `streamlit run app.py` (opens in browser)

## Usage

The system runs sequentially:
1. Prospector finds potential leads
2. Analyzer evaluates a selected home
3. Quote & Visual creates estimate and renders
4. Outreach drafts personalized email
5. Human reviews and approves before sending

## Configuration

Edit `.env` to change:
- Target location for lead search
- Email sender details
- Log level

## Legal Compliance

- All emails include unsubscribe links
- Honest sender information
- CAN-SPAM compliant
- Value-first approach (free color advice)

## Sample Output

See `sample_output.md` for an example of a complete run.

## Contributing

This is a free, open-source project. Feel free to improve and share!

## Disclaimer

Use responsibly. Respect privacy and local laws regarding lead generation.