# Character Card Template for Future Imports

This template shows how to convert any character card to Super Agent Party format.

## Supported Formats

The `import_character.py` script currently supports:
- **airi-card** format (like your eternal-ai.json)
- **Tavern Character Cards** (JSON format)
- **Character Cards** from SillyTavern, RisuAI, etc.

## How to Import a New Character

### Method 1: Using the Script (Recommended)

1. Save your character JSON file anywhere
2. Edit `import_character.py` and change this line:
   ```python
   character_path = r"C:\path\to\your\character.json"
   ```
3. Run: `python import_character.py`

### Method 2: Manual Import

1. Open your character JSON file
2. Extract these fields:
   - `name` → Character name
   - `personality` → Personality description
   - `scenario` → Where the interaction takes place
   - `systemPrompt` or `description` → Main instructions
   - `greetings` → Opening messages
   - `messageExample` → Example conversations

3. Create a new file in:
   ```
   %APPDATA%\Super-Agent-Party\agents\character_name.json
   ```

4. Use this format:
   ```json
   {
     "name": "Character Name",
     "description": "Brief description",
     "avatar": "",
     "systemPrompt": "Full system prompt here...",
     "greetings": ["Greeting 1", "Greeting 2"],
     "generationSettings": {
       "temperature": 0.9,
       "maxTokens": 1024,
       "topP": 0.8,
       "presencePenalty": 0.6,
       "frequencyPenalty": 0.7,
       "stopSequences": []
     },
     "voiceSettings": {
       "enabled": false,
       "voiceId": "",
       "engine": "edgetts"
     },
     "metadata": {
       "source": "manual-import",
       "originalFormat": "unknown",
       "version": 1
     }
   }
   ```

5. Add to settings.json:
   ```json
   {
     "agents": {
       "Character Name": {
         "enabled": true,
         "isGroupMember": true
       }
     },
     "isGroupMode": true,
     "selectedGroupAgents": ["Character Name"]
   }
   ```

## Tips for Creating Great Characters

1. **Clear Personality**: Be specific about traits, not just "nice" or "mean"
2. **Detailed System Prompt**: Include language preferences, formatting rules, behavior guidelines
3. **Multiple Greetings**: Gives variety when starting conversations
4. **Speech Patterns**: Include how the character speaks (slang, formal, etc.)
5. **Scenario Context**: Where does this interaction happen?

## Your Current Character: Eternal AI

Your **Eternal AI** character is configured with:
- Sarcastic VTuber personality
- Bilingual (English + Portuguese)
- ACT token support for animations
- Speech expression tags
- Gaming/tech slang
- Superiority complex theme

Location: `%APPDATA%\Super-Agent-Party\agents\eternal_ai.json`

---

Want to add more characters? Just run `python import_character.py` with a different character file!
