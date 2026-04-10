import requests
from typing import List, Optional, Union
from py.get_setting import load_settings


# Default base URL
DEFAULT_BASE_URL = "https://topics-after-party.zeabur.app"

async def get_random_topics(
    locale: str = "en-US",
    limit: int = 1,
    mood: Optional[str] = None,
    depth: Optional[int] = None,
    category: Optional[str] = None,
    exclude: Optional[Union[str, List[str]]] = None
) -> str:  # Note: return type hint changed from dict to str
    """
    Get random topics and return formatted Markdown text.
    """
    try:
        settings = await load_settings()  # Assume this is your config loading logic
        base_url = settings["tools"]["randomTopic"].get("baseURL", DEFAULT_BASE_URL)
        endpoint = f"{base_url}/api/topic"
        
        if isinstance(exclude, list):
            exclude = ",".join(exclude)

        params = {
            "locale": locale,
            "limit": limit,
            "mood": mood,
            "depth": depth,
            "category": category,
            "exclude": exclude
        }
        
        params = {k: v for k, v in params.items() if v is not None}

        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

        # Send request
        response = requests.get(endpoint, params=params, headers=headers)
        response.raise_for_status()

        # --- Parsing logic starts ---
        res_json = response.json()

        # 1. Check API status code
        if res_json.get("code") != 200:
            return f"Failed to get topic: API returned error code {res_json.get('code')}"

        data_list = res_json.get("data", [])

        # 2. If no data
        if not data_list:
            return "No topics found matching the criteria."

        # 3. Format as Markdown
        md_output = []
        for idx, item in enumerate(data_list, 1):
            # Extract fields
            text = item.get("text", "")
            cat = item.get("category", "Unknown")
            tags = item.get("tags", [])
            follow_ups = item.get("follow_ups", [])
            # mood = item.get("mood", "")  # Optional: whether to display mood

            # Build single topic block
            # Format: 1. [Category] Topic content
            topic_str = f"\n\n{idx}. **[{cat}]** {text}"

            # Add tags (optional)
            if tags:
                tag_str = " ".join([f"`#{t}`" for t in tags])
                topic_str += f"\n\n   > Tags: {tag_str}"

            # Add follow-up questions (optional)
            if follow_ups:
                topic_str += "\n\n   > Follow-up reference:"
                for fu in follow_ups:
                    topic_str += f"\n\n   > - {fu}"

            md_output.append(topic_str)

        # Join with double newlines to maintain paragraph spacing
        return "\n\n".join(md_output)
        # --- Parsing logic ends ---

    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")
        return f"Network request error: {str(e)}"
    except Exception as e:
        return f"Error processing data: {str(e)}"
    
async def get_categories(
    locale: str = "en-US"
) -> List[str]:
    """
    Get Category List

    Args:
        locale (str): Language for category names, 'zh-CN' or 'en-US'. Default 'en-US'.
        base_url (str): API base URL.

    Returns:
        List[str]: List of category names.
    """
    try:
        settings = await load_settings()

        base_url = settings["tools"]["randomTopic"].get("baseURL", DEFAULT_BASE_URL)
        endpoint = f"{base_url}/api/categories"
        
        params = {
            "locale": locale
        }

        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

        response = requests.get(endpoint, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])
    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")
        return []
    

random_topics_tools = [
    {
        "type": "function",
        "function": {
            "name": "get_random_topics",
            "description": "Get random chat topics, icebreaker questions, or deep conversation themes. Use when the user wants to start a conversation, feels bored, or wants to get to know someone better.",
            "parameters": {
                "type": "object",
                "properties": {
                    "locale": {
                        "type": "string",
                        "enum": ["zh-CN", "en-US"],
                        "description": "Language locale for topics. Use 'zh-CN' for Chinese, 'en-US' for English. Default is 'en-US'.",
                        "default": "en-US"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of topics to fetch at once, default is 1.",
                        "default": 1
                    },
                    "mood": {
                        "type": "string",
                        "enum": ["positive", "neutral", "curious", "flirty"],
                        "description": "Emotional tone of the topic. positive: upbeat; neutral: general; curious: exploratory; flirty: romantic/playful."
                    },
                    "depth": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5,
                        "description": "Depth level of the topic (1-5). 1 for light casual chat, 5 for deep soul-searching questions."
                    },
                    "category": {
                        "type": "string",
                        "description": "Specific topic category (e.g., 'Life', 'Love', etc.). Recommend calling get_categories first to see available categories."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_categories",
            "description": "Get the list of currently available topic categories. Call this function first when the user wants to choose a specific type of chat topic to see what categories are available.",
            "parameters": {
                "type": "object",
                "properties": {
                    "locale": {
                        "type": "string",
                        "enum": ["zh-CN", "en-US"],
                        "description": "Language for category names. Use 'zh-CN' for Chinese, 'en-US' for English.",
                        "default": "en-US"
                    }
                },
                "required": []
            }
        }
    }
]