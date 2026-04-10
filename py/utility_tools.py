import asyncio
from datetime import datetime
import json
from zoneinfo import ZoneInfo  # Python built-in module
import aiohttp
import requests
from tzlocal import get_localzone
from py.get_setting import load_settings
import wikipediaapi
import arxiv
from typing import Dict, List, Optional
# Get local timezone (tzinfo type)
local_timezone = get_localzone()  # Returns a tzinfo type

async def time_async(timezone: str = None):
    # If timezone is not provided, use local timezone
    tz = ZoneInfo(timezone) if timezone else local_timezone

    # Get current time (with timezone info)
    now = datetime.now(tz=tz)

    # Format output
    time_message = f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S')}, Timezone: {tz}"
    return time_message

time_tool = {
    "type": "function",
    "function": {
        "name": "time_async",
        "description": "Get current time (with timezone info)",
        "parameters": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "Current timezone, defaults to local timezone. Format: Asia/Shanghai",
                },
            },
            "required": [],
        },
    },
}

async def _get_lat_lon(city: str) -> Dict[str, float]:
    """Return {"latitude": xx, "longitude": yy, "timezone": "Asia/Shanghai"}"""
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": city, "count": 1, "language": "en"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                raise RuntimeError("Geocoding request failed")
            data = await resp.json()
    if not data.get("results"):
        raise RuntimeError(f"City not found: {city}")
    r = data["results"][0]
    return {
        "latitude": r["latitude"],
        "longitude": r["longitude"],
        "timezone": r.get("timezone", "Asia/Shanghai"),
    }


async def _call_open_meteo(lat: float, lon: float, timezone: str, forecast: bool, days: int):
    """When forecast=True returns 7-day forecast, otherwise returns current weather"""
    if forecast:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min,weathercode",
            "timezone": timezone,
            "forecast_days": days,
        }
    else:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "current_weather": "true",
            "timezone": timezone,
        }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                raise RuntimeError("Weather API request failed")
            return await resp.json()


_WCODE_MAP = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def _desc(code: int) -> str:
    return _WCODE_MAP.get(code, "Unknown")


async def get_weather_async(city: str, forecast: bool = False, days: int = 1) -> str:
    """
    Query city weather (current or forecast) -- using Open-Meteo
    """
    try:
        # 4.1 Get lat/lon
        geo = await _get_lat_lon(city)

        # 4.2 Get weather data
        data = await _call_open_meteo(
            geo["latitude"], geo["longitude"], geo["timezone"], forecast, days
        )

        # 4.3 Format output, keeping the original string template style
        if forecast:
            daily = data["daily"]
            result = [
                f"{days}-day weather forecast for {city}:",
                "Overview: Based on Open-Meteo global model",
                "Severity: None",
                "Daily forecast:",
            ]
            for i in range(days):
                date = daily["time"][i]
                tmax = daily["temperature_2m_max"][i]
                tmin = daily["temperature_2m_min"][i]
                code = daily["weathercode"][i]
                result.append(
                    f"- {date}: Day {tmax}°C/{_desc(code)}, Night {tmin}°C/{_desc(code)}"
                )
            return "\n".join(result)

        else:
            cw = data["current_weather"]
            return (
                f"Current weather for {city}:\n"
                f"Temperature: {cw['temperature']}°C\n"
                f"Conditions: {_desc(cw['weathercode'])}\n"
                f"Humidity: Not available\n"
                f"Wind speed: {cw['windspeed']} km/h"
            )

    except Exception as e:
        return f"Error querying weather: {str(e)}"
    
weather_tool = {
    "type": "function",
    "function": {
        "name": "get_weather_async",
        "description": "Query city weather (current or forecast)",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City name, e.g., Beijing, New York",
                },
                "forecast": {
                    "type": "boolean",
                    "description": "Whether to return forecast (false for current weather)",
                    "default": False
                },
                "days": {
                    "type": "integer",
                    "description": "Number of forecast days (1 to 7)",
                    "default": 1,
                    "minimum": 1,
                    "maximum": 7
                },
            },
            "required": ["city"],
        },
    },
}

async def get_location_coordinates_async(city: str) -> str:
    """
    Query city coordinates and location info (using Open-Meteo GeoCoding)
    Returns format identical to the original for seamless replacement.
    """
    try:
        # 1. Request Open-Meteo geocoding
        url = "https://geocoding-api.open-meteo.com/v1/search"
        params = {"name": city, "count": 1, "language": "en"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return f"Error querying location info: HTTP {resp.status}"
                data = await resp.json()

        if not data.get("results"):
            return f"Unable to find location info for city: {city}"

        r = data["results"][0]

        # 2. Format string consistent with original
        return (
            f"Location info for {city}:\n"
            f"Name: {r.get('name', 'Unknown')} ({r.get('name', 'Unknown')})\n"
            f"Country: {r.get('country', 'Unknown')}\n"
            f"Admin region: {r.get('admin1', 'Unknown')}\n"
            f"Coordinates: {r.get('latitude', 'Unknown')}, {r.get('longitude', 'Unknown')}\n"
            f"Timezone: {r.get('timezone', 'Unknown')}"
        )

    except Exception as e:
        return f"Error querying location info: {str(e)}"

location_tool = {
    "type": "function",
    "function": {
        "name": "get_location_coordinates_async",
        "description": "Query city coordinates and location info",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City name, e.g., Beijing, New York",
                },
            },
            "required": ["city"],
        },
    },
}

async def get_weather_by_city_async(city: str,lang:str="en-US",product:str="astro") -> str:
    """
    Get 7timer weather data by city name (JSON + image URL)

    :param city: City name (e.g., "Beijing", "New York")
    :param lang: Language code (default "en-US")
    :param product: Product type (default "astro")
    :return: Formatted string containing JSON data and image URL
    """
    try:
        # 1. Get city coordinates
        location_info = await get_location_coordinates_async(city)

        # Parse coordinates (assumes return format contains "Coordinates: lat, lon")
        if "Coordinates:" not in location_info:
            return f"Unable to get coordinates for {city}"

        # Extract coordinates (example parsing logic, may need adjustment)
        geo_part = location_info.split("Coordinates:")[1].split("\n")[0].strip()
        lat, lon = map(float, geo_part.split(","))

        # 2. Call 7timer API to get weather data
        base_url = "http://www.7timer.info/bin/astro.php"

        # Get image URL
        img_params = {
            "lon": lon,
            "lat": lat,
            "ac": 0,
            "lang": lang,
            "unit": "metric",
            "tzshift": 0,
        }
        img_url = f"{base_url}?{'&'.join([f'{k}={v}' for k, v in img_params.items()])}"

        # Get JSON data
        data_params = {
            "lon": lon,
            "lat": lat,
            "ac": 0,
            "product": product,
            "lang": lang or "en",
            "unit": "metric",
            "output": "json",
            "tzshift": 0,
        }
        data_response = requests.get(base_url, params=data_params)
        data_response.raise_for_status()
        weather_data = data_response.json()

        # 3. Return formatted result
        return f"{json.dumps(weather_data, ensure_ascii=False)}\n![image]({img_url})"

    except Exception as e:
        return f"Error getting weather data: {str(e)}"


timer_weather_tool = {
    "type": "function",
    "function": {
        "name": "get_weather_by_city_async",
        "description": "Detailed weather information including weather chronology image. Get 7timer weather data by city name (JSON + image URL). Return image URL in ![image](image_url) format",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City name, e.g., Beijing, New York",
                },
                "lang": {
                    "type": "string",
                    "description": "Language code, e.g., en-US, zh-CN",
                },
                "product": {
                    "type": "string",
                    "description": "Product type, default is astro. Options: astro, civil. astro returns 3-day (72 hours) 3-hourly forecast. civil returns 7-day forecast (2-4 time points per day)",
                    "enum": ["astro", "civil"]
                }
            },
            "required": ["city"],
        },
    },
}



async def get_wikipedia_summary_and_sections(
    topic: str,
    language: str = "en"
) -> str:
    """
    Get summary and all section titles from Wikipedia for a given topic (returned as string)

    :param topic: Topic to query
    :param language: Language code, default "en" (English)
    :param user_agent: Custom user agent
    :return: String containing summary and section list, or error message if page does not exist
    """
    wiki_wiki = wikipediaapi.Wikipedia(
        language=language,
        extract_format=wikipediaapi.ExtractFormat.WIKI,
        user_agent="super-agent-party"
    )

    page = wiki_wiki.page(topic)

    if not page.exists():
        return f"Wikipedia page for '{topic}' not found (language: {language})"

    result = {
        "title": page.title,
        "summary": page.summary,
        "URL": page.fullurl,
        "sections": [section.title for section in page.sections]
    }

    return json.dumps(result, ensure_ascii=False, indent=2)

wikipedia_summary_tool = {
    "type": "function",
    "function": {
        "name": "get_wikipedia_summary_and_sections",
        "description": "Get summary and all section titles from Wikipedia for a given topic",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Topic name to query",
                },
                "language": {
                    "type": "string",
                    "description": "Language code, e.g., en (English), zh (Chinese)",
                    "default": "en"
                },
            },
            "required": ["topic"],
        },
    },
}

async def get_wikipedia_section_content(
    topic: str,
    section_title: str,
    language: str = "en"
) -> str:
    """
    Get detailed content of a specific section from Wikipedia for a given topic (returned as string)

    :param topic: Topic to query
    :param section_title: Section title
    :param language: Language code, default "en" (English)
    :param user_agent: Custom user agent
    :return: String containing section content, or error message if page or section does not exist
    """
    wiki_wiki = wikipediaapi.Wikipedia(
        language=language,
        extract_format=wikipediaapi.ExtractFormat.WIKI,
        user_agent="super-agent-party"
    )

    page = wiki_wiki.page(topic)

    if not page.exists():
        return f"Wikipedia page for '{topic}' not found (language: {language})"

    for section in page.sections:
        if section.title == section_title:
            result = {
                "topic": page.title,
                "section_title": section.title,
                "content": section.text,
                "URL": page.fullurl
            }
            return json.dumps(result, ensure_ascii=False, indent=2)

    return f"Section titled '{section_title}' not found in '{topic}' page"

wikipedia_section_tool = {
    "type": "function",
    "function": {
        "name": "get_wikipedia_section_content",
        "description": "Get detailed content of a specific section from Wikipedia. You must first call get_wikipedia_summary_and_sections to get the section list",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Topic name to query",
                },
                "section_title": {
                    "type": "string",
                    "description": "Section title to retrieve",
                },
                "language": {
                    "type": "string",
                    "description": "Language code, e.g., en (English), zh (Chinese)",
                    "default": "en"
                }
            },
            "required": ["topic", "section_title"],
        },
    },
}



async def search_arxiv_papers(
    query: str,
    max_results: int = 5,
    sort_by: str = "relevance",
    sort_order: str = "descending",
    return_fields: Optional[List[str]] = None
) -> str:
    """
    Search arXiv papers and return structured results

    :param query: Search keyword or query string
    :param max_results: Maximum number of results to return (default 5)
    :param sort_by: Sort method ("relevance", "submittedDate", "lastUpdatedDate")
    :param sort_order: Sort order ("ascending" or "descending")
    :param return_fields: List of fields to return
    :return: JSON formatted search results
    """
    # Set default return fields
    default_fields = [
        "title", "authors", "summary", "published",
        "pdf_url", "doi", "primary_category"
    ]
    return_fields = return_fields or default_fields

    # Wrap synchronous operation as async
    def sync_search():
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion(sort_by),
            sort_order=arxiv.SortOrder(sort_order)
        )
        return list(search.results())

    results = []
    try:
        # Execute synchronous operation in thread pool
        papers = await asyncio.to_thread(sync_search)

        for result in papers:
            paper_info = {
                "title": result.title,
                "authors": [author.name for author in result.authors],
                "summary": result.summary,
                "published": str(result.published),
                "pdf_url": result.pdf_url,
                "doi": result.doi or "",
                "primary_category": result.primary_category,
                "entry_id": result.entry_id
            }
            # Filter fields
            filtered = {k: v for k, v in paper_info.items() if k in return_fields}
            results.append(filtered)

        if not results:
            return json.dumps({"error": f"No papers found for '{query}'"}, ensure_ascii=False)

        return json.dumps({
            "query": query,
            "count": len(results),
            "results": results
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": f"Search failed: {str(e)}"}, ensure_ascii=False)

arxiv_tool = {
    "type": "function",
    "function": {
        "name": "search_arxiv_papers",
        "description": "Search arXiv academic paper database, get paper titles, authors, abstracts, PDF links, etc.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keywords or query string in English, e.g., 'quantum machine learning' or 'ti:transformer AND cat:cs.CL'",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Number of results to return (1-100)",
                    "default": 5
                },
                "sort_by": {
                    "type": "string",
                    "enum": ["relevance", "submittedDate", "lastUpdatedDate"],
                    "description": "Sort method",
                    "default": "relevance"
                },
                "sort_order": {
                    "type": "string",
                    "enum": ["ascending", "descending"],
                    "description": "Sort order",
                    "default": "descending"
                },
                "return_fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specify return fields, e.g., ['title','authors','pdf_url']",
                }
            },
            "required": ["query"],
        },
    },
}