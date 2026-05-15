# Multi-Provider LLM Support

This project supports multiple AI/LLM providers. You can easily switch between different models and providers based on your needs.

## Supported Providers

### 1. **Groq** (FREE - Recommended)
- **Cost**: Completely free
- **Speed**: Very fast
- **Best for**: Production use, cost-effective
- **Setup**: Add API key to `.env`

```env
LLM_PROVIDER=groq
GROQ_API_KEY=your_groq_api_key_here
```

**Available Models**:
- `llama3-70b-8192` (Most capable)
- `mixtral-8x7b-32768` (Balanced)
- `llama3-8b-8192` (Fastest)

**Get API Key**: https://console.groq.com

---

### 2. **OpenAI** (PAID)
- **Cost**: Pay per token (varies)
- **Speed**: Fast
- **Best for**: High-quality outputs, production
- **Setup**: Add API key to `.env`

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your_openai_api_key_here
```

**Available Models**:
- `gpt-4-turbo` (Most capable)
- `gpt-4` (Good quality)
- `gpt-3.5-turbo` (Fast, cheaper)

**Get API Key**: https://platform.openai.com/api-keys

---

### 3. **Anthropic** (PAID)
- **Cost**: Pay per token
- **Speed**: Fast
- **Best for**: High-quality reasoning, safety-focused
- **Setup**: Add API key to `.env`

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

**Available Models**:
- `claude-3-opus-20240229` (Most capable)
- `claude-3-sonnet-20240229` (Balanced)
- `claude-3-haiku-20240307` (Fastest)

**Get API Key**: https://console.anthropic.com

---

### 4. **Ollama** (FREE - Local)
- **Cost**: Completely free (runs locally)
- **Speed**: Variable (depends on hardware)
- **Best for**: Privacy, offline use, experimentation
- **Setup**: Install Ollama, then configure

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
```

**Available Models**:
- `llama2` (Good general model)
- `mistral` (Fast and capable)
- `neural-chat` (Optimized for chat)
- `dolphin-mixtral` (High performance)

**Get Ollama**: https://ollama.ai

---

## Switching Providers

### Via Environment Variable
Set `LLM_PROVIDER` in `.env`:

```env
LLM_PROVIDER=groq  # or openai, anthropic, ollama
```

### Via Web UI
1. Open the Streamlit app
2. Sidebar → AI Model Settings
3. Select provider from dropdown
4. Select model from the list
5. Click "Start Agent Workflow"

---

## Pricing Comparison

| Provider | Cost | Speed | Quality | Best For |
|----------|------|-------|---------|----------|
| **Groq** | FREE | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Production (recommended) |
| **OpenAI** | PAID | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | High-quality, premium |
| **Anthropic** | PAID | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | Reasoning, safety |
| **Ollama** | FREE | ⭐⭐⭐ | ⭐⭐⭐ | Local, private, testing |

---

## Installation Instructions

### For Groq (Default - FREE)
```bash
pip install -r requirements.txt
# Add GROQ_API_KEY to .env
```

### For OpenAI
```bash
pip install langchain-openai
# Add OPENAI_API_KEY to .env
```

### For Anthropic
```bash
pip install langchain-anthropic
# Add ANTHROPIC_API_KEY to .env
```

### For Ollama (Local)
```bash
# Download Ollama from https://ollama.ai
# Install and run: ollama serve
# No API key needed - runs locally
```

---

## Usage Examples

### Run with Groq (Default)
```bash
python main.py
# Or web UI: streamlit run app.py
```

### Run with OpenAI
```bash
export LLM_PROVIDER=openai
python main.py
```

### Run with local Ollama
```bash
# First, start Ollama: ollama serve
# Then run:
export LLM_PROVIDER=ollama
python main.py
```

---

## Troubleshooting

**"LLM API Key not set"** → Add the API key to `.env` for your chosen provider

**"Cannot connect to Ollama"** → Make sure `ollama serve` is running on localhost:11434

**"Model not found"** → Use only models available for your provider (see lists above)

**"Rate limited"** → Groq has free tier limits; upgrade or switch provider

---

## Performance Notes

- **Groq**: Fastest free option, excellent for production
- **OpenAI GPT-4**: Best quality but most expensive
- **Anthropic Claude**: Excellent reasoning, mid-range cost
- **Ollama**: Perfect for privacy and offline use, slower on CPU

---

## Recommended Setup

For maximum value with zero cost:
```env
LLM_PROVIDER=groq
GROQ_API_KEY=<your_free_groq_key>
```

This provides:
- ✅ Free tier available
- ✅ Very fast inference
- ✅ Production-ready quality
- ✅ Competitive with paid options
