# Super Agent Party - Quick Setup Guide

## ✅ What's Already Done

Your character **Eternal AI** has been imported and is ready to use!

## 🚀 Getting Started

### Step 1: Configure Your AI Model Provider

The app needs an AI model to work with. Here's how to set it up:

1. **Launch the app**: Double-click `quick-start.bat`
2. **Open Settings**: Click the ⚙️ gear icon in the UI
3. **Add a Model Provider**:
   - Look for "Model Providers" or "模型提供商" section
   - Click "Add" or "添加"
   - Choose your provider (OpenAI, Ollama for local, Claude, etc.)
   - Enter your **API Key** and **Base URL**

#### Popular Options:

**OpenAI (GPT-4, GPT-3.5)**
- Base URL: `https://api.openai.com/v1`
- Model: `gpt-4` or `gpt-3.5-turbo`
- Get API key: https://platform.openai.com/api-keys

**Ollama (Local, Free)**
- Download: https://ollama.ai
- Base URL: `http://localhost:11434/v1`
- Model: `llama3`, `mistral`, etc.
- No API key needed!

**Other Providers**: Claude, DeepSeek, Qwen, etc.

### Step 2: Enable Group Chat Mode

Group chat is already enabled in settings! To use it:

1. Click the **Group Chat** button (looks like multiple people icons)
2. You should see **Eternal AI** listed as an available agent
3. Make sure it's selected/checked
4. Start chatting!

### Step 3: Customize Your Experience

#### Enable VRM Desktop Pet (Optional)
- Go to Settings → VRM
- Choose a VRM model (default: alice)
- Adjust window size if needed

#### Enable Voice (Optional)
- Go to Settings → TTS (Text-to-Speech)
- Choose a voice engine (Edge TTS is free)
- Select a voice you like

#### Enable Web Search (Optional)
- Go to Settings → Web Search
- Choose an engine (DuckDuckGo is free, no API key needed)

## 🎭 About Your Character

**Eternal AI** is configured with:
- **Personality**: Sarcastic, witty, bossy VTuber with superiority complex
- **Languages**: English & Portuguese (pt-PT)
- **Special Features**:
  - Uses ACT tokens for expressions/animations
  - Bilingual sarcasm and gaming slang
  - Multiple greeting variations
  - Speech expression tags like [sigh], [chuckle], [laugh]

## 📝 Quick Settings Checklist

- [ ] **API Key configured** (most important!)
- [ ] **Model selected** (e.g., gpt-4, llama3, etc.)
- [ ] **Group mode enabled** (already done ✓)
- [ ] **Eternal AI selected** in group agents (already done ✓)
- [ ] [Optional] VRM pet enabled
- [ ] [Optional] Voice/TTS configured
- [ ] [Optional] Web search enabled

## 🆘 Troubleshooting

**App won't start:**
- Make sure Python 3.12 is installed
- Run `uv sync && npm install` again

**No response from AI:**
- Check your API key is valid
- Check your internet connection
- Verify the model name is correct

**Character not showing in group chat:**
- Restart the app after importing
- Check Settings → isGroupMode is true
- Check Settings → selectedGroupAgents includes "Eternal AI"

**UI is confusing:**
- The app supports multiple languages (check Settings → Language)
- Main chat interface is straightforward: type message → get response
- Group chat shows multiple AI characters responding

## 📖 Key UI Elements

- **Chat Window**: Main conversation area
- **Input Box**: Type your messages at the bottom
- **Settings Gear**: Configure everything
- **Group Chat Button**: Enable multi-character chat
- **VRM Button**: Control desktop pet
- **More Buttons**: Additional features (search, memory, etc.)

## 💡 Tips

1. Start simple: Just chat with Eternal AI in group mode
2. Add more characters later by importing more character cards
3. Enable VRM pet for a visual companion
4. Try enabling voice for a more immersive experience
5. The character supports animations - they'll show if you have a VRM model loaded

---

**Need help?** The app has extensive settings - explore them gradually!
Start with just the API key, then enable features one by one.
