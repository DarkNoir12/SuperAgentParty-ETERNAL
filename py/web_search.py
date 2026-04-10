import asyncio
import json
import os
import time
from bs4 import BeautifulSoup
from langchain_community.tools import DuckDuckGoSearchResults
import requests
from tavily import TavilyClient
from py.get_setting import load_settings
from py.load_files import check_robots_txt

async def DDGsearch_async(query):
    settings = await load_settings()
    def sync_search():
        max_results = settings['webSearch']['duckduckgo_max_results'] or 10
        try:
            dds = DuckDuckGoSearchResults(num_results=max_results,output_format="json")
            results = dds.invoke(query)
            return results
        except Exception as e:
            print(f"An error occurred: {e}")
            return ""

    try:
        # Use default executor to run synchronous operations in a separate thread
        return await asyncio.get_event_loop().run_in_executor(None, sync_search)
    except Exception as e:
        print(f"Event loop error: {e}")
        return ""
    
duckduckgo_tool = {
    "type": "function",
    "function": {
        "name": "DDGsearch_async",
        "description": "Get information from DuckDuckGo search results using keywords.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The keyword(s) to search. Multiple keywords can be separated by spaces.",
                },
            },
            "required": ["query"],
        },
    },
}

async def searxng_async(query,categories="general"):
    settings = await load_settings()
    def sync_search(query):
        max_results = settings['webSearch']['searxng_max_results'] or 10
        api_url = settings['webSearch']['searxng_url'] or "http://127.0.0.1:8080"
        engines = settings['webSearch']['searxng_engines'] or None
        is_select = settings['webSearch']['searxng_is_select'] or False
        headers = {"User-Agent": "Mozilla/5.0"}
        params = {
            "q": query, 
            "categories": categories,
            "count": max_results
        }
        if engines and is_select:
            params["engines"] = engines

        try:
            response = requests.get(api_url + "/search", headers=headers, params=params)
            html_content = response.text

            soup = BeautifulSoup(html_content, 'html.parser')
            results = []

            for result in soup.find_all('article', class_='result'):
                title = result.find('h3').get_text() if result.find('h3') else 'No title'
                
                # Fix: use correct selector
                link_elem = result.find('a', class_='url_header')
                if not link_elem:
                    # Fallback: get link from h3
                    h3 = result.find('h3')
                    link_elem = h3.find('a') if h3 else None
                
                link = link_elem['href'] if link_elem and link_elem.get('href') else 'No link'
                
                snippet = result.find('p', class_='content').get_text() if result.find('p', class_='content') else 'No snippet'
                
                results.append({
                    'title': title,
                    'link': link,
                    'snippet': snippet
                })

            return json.dumps(results, indent=2, ensure_ascii=False)
            
        except Exception as e:
            print(f"Search error: {e}")
            return f"Search error: {e}"

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, sync_search, query)
    except Exception as e:
        print(f"Async error: {e}")
        return f"Async error: {e}"

searxng_tool = {
    "type": "function",
    "function": {
        "name": "searxng_async",
        "description": "Use the open-source SearXNG meta search engine to retrieve web information.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keywords, supporting natural language and multi-keyword combined queries.",
                },
                "categories": {
                    "type": "string",
                    "description": "Search category. Choose the most appropriate category based on user intent. Options: 'general' (general/default, suitable for most encyclopedia and common knowledge queries), 'news' (news, suitable for recent events), 'images' (images, suitable for finding pictures), 'videos' (videos, suitable for finding video resources), 'it' (IT technology, suitable for code errors, programming related), 'science' (science, suitable for academic papers and scientific materials).",
                    "enum": ["general", "news", "images", "videos", "it", "science"],
                    "default": "general"
                },
            },
            "required": ["query"],
        },
    },
}

async def bochaai_search_async(query):
    settings = await load_settings()
    def sync_search():
        max_results = settings['webSearch']['bochaai_max_results'] or 10
        api_key = settings['webSearch'].get('bochaai_api_key', "")
        
        if not api_key:
            return "API key not configured"

        url = "https://api.bochaai.com/v1/web-search"
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        payload = json.dumps({
            "query": query,
            "summary": True,
            "count": max_results
        })

        try:
            response = requests.post(url, headers=headers, data=payload, timeout=30)
            if response.status_code == 200:
                result_data = response.json()
                
                # Parse new API response format
                formatted_results = []
                search_results = result_data.get('data', {}).get('webPages', {}).get('value', [])

                for item in search_results:
                    # Build richer result information
                    formatted_item = {
                        'title': item.get('name', 'No title'),
                        'link': item.get('url', ''),
                        'displayUrl': item.get('displayUrl', ''),
                        'snippet': item.get('snippet', 'No summary'),
                        'siteName': item.get('siteName', 'Unknown source'),
                    }
                    # Auto-generate concise source name
                    if not formatted_item['siteName']:
                        formatted_item['siteName'] = formatted_item['displayUrl'].split('//')[-1].split('/')[0]
                    formatted_results.append(formatted_item)
                
                return json.dumps(formatted_results, indent=2, ensure_ascii=False)
            else:
                return f"Request failed with status code: {response.status_code}, response: {response.text}"
        except Exception as e:
            print(f"BochaAI search error: {str(e)}")
            return ""

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, sync_search)
    except Exception as e:
        print(f"Async execution error: {e}")
        return ""

bochaai_tool = {
    "type": "function",
    "function": {
        "name": "bochaai_search_async",
        "description": "Retrieve web information through the BochaAI intelligent search API, supporting deep semantic understanding.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language query string for search, supporting complex semantics and long sentences (e.g., key points from Alibaba's latest financial report)",
                }
            },
            "required": ["query"],
        },
    }
}

async def Tavily_search_async(query):
    settings = await load_settings()
    def sync_search():
        max_results = settings['webSearch']['tavily_max_results'] or 10
        try:
            api_key = settings['webSearch'].get('tavily_api_key', "")
            client = TavilyClient(api_key)
            response = client.search(
                query=query,
                max_results=max_results
            )
            return json.dumps(response, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Tavily search error: {e}")
            return ""

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, sync_search)
    except Exception as e:
        print(f"Async execution error: {e}")
        return ""

tavily_tool = {
    "type": "function",
    "function": {
        "name": "Tavily_search_async",
        "description": "Retrieve high-quality web information through the Tavily professional search API, especially suitable for obtaining real-time data and professional analysis.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword or natural language query string for search",
                }
            },
            "required": ["query"],
        },
    },
}

from langchain_community.utilities import BingSearchAPIWrapper

async def Bing_search_async(query):
    settings = await load_settings()
    def sync_search():
        max_results = settings['webSearch']['bing_max_results'] or 10
        try:
            api_key = settings['webSearch'].get('bing_api_key', "")
            bing_search_url = settings['webSearch'].get('bing_search_url', "")
            client = BingSearchAPIWrapper(bing_subscription_key=api_key,bing_search_url=bing_search_url)
            response = client.results(query=query,num_results=max_results)
            return json.dumps(response, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Bing search error: {e}")
            return ""

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, sync_search)
    except Exception as e:
        print(f"Async execution error: {e}")
        return ""


bing_tool = {
    "type": "function",
    "function": {
        "name": "Bing_search_async",
        "description": "Retrieve web information through the Bing Search API.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword or natural language query string for search",
                }
            },
            "required": ["query"],
        },
    }
}

from langchain_google_community import GoogleSearchAPIWrapper

async def Google_search_async(query):
    settings = await load_settings()
    def sync_search():
        max_results = settings['webSearch']['google_max_results'] or 10
        try:
            api_key = settings['webSearch'].get('google_api_key', "")
            google_cse_id = settings['webSearch'].get('google_cse_id', "")
            client = GoogleSearchAPIWrapper(google_api_key=api_key,google_cse_id=google_cse_id)
            response = client.results(query=query,num_results=max_results)
            return json.dumps(response, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Google search error: {e}")
            return ""

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, sync_search)
    except Exception as e:
        print(f"Async execution error: {e}")
        return ""


google_tool = {
    "type": "function",
    "function": {
        "name": "Google_search_async",
        "description": "Retrieve web information through the Google Search API.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword or natural language query string for search",
                }
            },
            "required": ["query"],
        }
    }
}

from langchain_community.tools import BraveSearch

async def Brave_search_async(query):
    settings = await load_settings()
    def sync_search():
        max_results = settings['webSearch']['brave_max_results'] or 10
        try:
            api_key = settings['webSearch'].get('brave_api_key', "")
            client = BraveSearch.from_api_key(api_key=api_key, search_kwargs={"count": max_results})
            response = client.run(query)
            return response
        except Exception as e:
            print(f"Brave search error: {e}")
            return ""

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, sync_search)
    except Exception as e:
        print(f"Async execution error: {e}")
        return ""
    
brave_tool = {
    "type": "function",
    "function": {
        "name": "Brave_search_async",
        "description": "Retrieve web information through the Brave Search API.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword or natural language query string for search",
                }
            },
            "required": ["query"],
        },
    }
}

from langchain_exa import ExaSearchResults
async def Exa_search_async(query):
    settings = await load_settings()
    def sync_search():
        max_results = settings['webSearch']['exa_max_results'] or 10
        try:
            api_key = settings['webSearch'].get('exa_api_key', "")
            client = ExaSearchResults(exa_api_key=api_key)
            response = client._run(
                query=query,
                num_results=max_results,
            )
            # Check the type of response
            if type(response) == list or type(response) == dict:
                return json.dumps(response, indent=2, ensure_ascii=False)
            elif type(response) == str:
                return response
        except Exception as e:
            print(f"Exa search error: {e}")
            return ""

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, sync_search)
    except Exception as e:
        print(f"Async execution error: {e}")
        return ""

exa_tool = {
    "type": "function", 
    "function": {
        "name": "Exa_search_async",
        "description": "Retrieve web information through the Exa Search API.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword or natural language query string for search",
                }
            },
            "required": ["query"],
            }
    }
}

from langchain_community.utilities import GoogleSerperAPIWrapper

async def Serper_search_async(query):
    settings = await load_settings()
    def sync_search():
        max_results = settings['webSearch']['serper_max_results'] or 10
        try:
            api_key = settings['webSearch'].get('serper_api_key', "")
            client = GoogleSerperAPIWrapper(serper_api_key=api_key,k=max_results)
            response = client.results(query)
            return json.dumps(response, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Serper search error: {e}")
            return ""

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, sync_search)
    except Exception as e:
        print(f"Async execution error: {e}")
        return ""
    
serper_tool = {
    "type": "function",
    "function": {
        "name": "Serper_search_async",
        "description": "Retrieve web information through the Serper Search API.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword or natural language query string for search",
                }
            },
            "required": ["query"],
        },
    }
}

async def jina_crawler_async(original_url):
    settings = await load_settings()
    def sync_crawler():
        detail_url = "https://r.jina.ai/"
        url = f"{detail_url}{original_url}"
        try:
            jina_api_key = settings['webSearch'].get('jina_api_key', "")
            if jina_api_key:
                headers = {
                    'Authorization': f'Bearer {jina_api_key}',
                }
                response = requests.get(url, headers=headers)
            else:
                response = requests.get(url)
            if response.status_code == 200:
                return response.text
            else:
                return f"Failed to fetch web page info for {original_url}, status code: {response.status_code}"
        except requests.RequestException as e:
            return f"Failed to fetch web page info for {original_url}, error: {str(e)}"

    try:
        if not await check_robots_txt(original_url):
            raise PermissionError(f"Compliance denied: Target website disallows scraping")
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, sync_crawler)
    except Exception as e:
        print(f"Async execution error: {e}")
        return str(e)

jina_crawler_tool = {
    "type": "function",
    "function": {
        "name": "jina_crawler_async",
        "description": "Retrieve web page content for a specified URL through Jina AI's web scraping API. The URL can be a link from search engine results or a URL provided by the user. Do not pass URLs starting with localhost or intranet addresses, as Jina will not be able to access them.",
        "parameters": {
            "type": "object",
            "properties": {
                "original_url": {
                    "type": "string",
                    "description": "The original URL to be crawled.",
                },
            },
            "required": ["original_url"],
        },
    },
}

class Crawl4AiTester:
    def __init__(self, base_url: str = "http://localhost:11235"):
        self.base_url = base_url

    def submit_and_wait(self, request_data: dict,headers: dict = None, timeout: int = 300) -> dict:
        # Submit crawl job
        response = requests.post(f"{self.base_url}/crawl", json=request_data,headers=headers)
        task_id = response.json()["task_id"]
        print(f"Task ID: {task_id}")

        # Poll for result
        start_time = time.time()
        while True:
            if time.time() - start_time > timeout:
                raise TimeoutError(f"Task {task_id} timeout")

            result = requests.get(f"{self.base_url}/task/{task_id}",headers=headers)
            status = result.json()

            if status["status"] == "completed":
                return status

            time.sleep(2)

async def Crawl4Ai_search_async(original_url):
    settings = await load_settings()
    def sync_search():
        try:
            tester = Crawl4AiTester()
            api_key = settings['webSearch'].get('Crawl4Ai_api_key', "test_api_code")
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
            request = {
                "urls": original_url,
                "priority": 10
            }
            result = tester.submit_and_wait(request, headers=headers)
            return result['result']['markdown']
        except Exception as e:
            return f"Failed to fetch web page info for {original_url}, error: {str(e)}"

    try:
        if not await check_robots_txt(original_url):
            raise PermissionError(f"Compliance denied: Target website disallows scraping")
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, sync_search)
    except Exception as e:
        print(f"Async execution error: {e}")
        return str(e)

Crawl4Ai_tool = {
    "type": "function",
    "function": {
        "name": "Crawl4Ai_search_async",
        "description": "Crawl web page content from a specified URL through the Crawl4Ai service, returning text in Markdown format.",
        "parameters": {
            "type": "object",
            "properties": {
                "original_url": {
                    "type": "string",
                    "description": "The target URL address to be crawled.",
                }
            },
            "required": ["original_url"],
        },
    },
}

from typing import Optional, Dict, Any

# ============== 2. Firecrawl ==============

class FirecrawlClient:
    """
    Firecrawl API client
    Supports official API and self-deployed instances
    """
    
    def __init__(self, base_url: str, api_key: Optional[str] = None):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.headers = {
            'Content-Type': 'application/json',
        }
        if api_key:
            self.headers['Authorization'] = f'Bearer {api_key}'
    
    def _get_api_path(self, endpoint: str) -> str:
        """Automatically determine API version path based on base URL"""
        if '/v2/' in self.base_url:
            # Official API v2
            return f"{self.base_url}/{endpoint}"
        elif '/v1/' in self.base_url:
            # Self-deployed is usually v1
            return f"{self.base_url}/{endpoint}"
        else:
            # Default appended path
            return f"{self.base_url}/{endpoint}"
    
    def scrape(self, url: str, formats: list = None, **kwargs) -> Dict[str, Any]:
        """
        Single page scrape (Scrape)
        """
        formats = formats or ["markdown"]
        endpoint = self._get_api_path("scrape")
        
        payload = {
            "url": url,
            "formats": formats,
            **kwargs
        }
        
        response = requests.post(
            endpoint,
            headers=self.headers,
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        return response.json()
    
    def crawl(self, url: str, limit: int = 10, **kwargs) -> str:
        """
        Full site crawl (Crawl) - asynchronous job, requires polling
        """
        # Submit crawl task
        submit_endpoint = self._get_api_path("crawl")
        payload = {
            "url": url,
            "limit": limit,
            **kwargs
        }
        
        submit_resp = requests.post(
            submit_endpoint,
            headers=self.headers,
            json=payload,
            timeout=30
        )
        submit_resp.raise_for_status()
        job_data = submit_resp.json()
        
        if not job_data.get("success"):
            raise Exception(f"Failed to submit crawl job: {job_data}")
        
        job_id = job_data.get("id")
        check_url = job_data.get("url") or f"{self.base_url}/crawl/{job_id}"
        
        # Poll and wait for completion
        max_wait = 300  # 5 minute timeout
        interval = 2
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            status_resp = requests.get(
                check_url,
                headers=self.headers,
                timeout=30
            )
            status_resp.raise_for_status()
            status_data = status_resp.json()
            
            if status_data.get("status") == "completed":
                return status_data
            elif status_data.get("status") == "failed":
                raise Exception(f"Crawl job failed: {status_data.get('error', 'Unknown error')}")
            
            time.sleep(interval)
        
        raise TimeoutError(f"Crawl job {job_id} timeout after {max_wait}s")
    
    def search(self, query: str, limit: int = 5, scrape_options: dict = None) -> Dict[str, Any]:
        """
        Search (Search)
        """
        endpoint = self._get_api_path("search")
        
        payload = {
            "query": query,
            "limit": limit
        }
        if scrape_options:
            payload["scrapeOptions"] = scrape_options
        
        response = requests.post(
            endpoint,
            headers=self.headers,
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        return response.json()
    
    def map(self, url: str, search: str = None) -> Dict[str, Any]:
        """
        Site map (Map)
        """
        endpoint = self._get_api_path("map")
        
        payload = {"url": url}
        if search:
            payload["search"] = search
        
        response = requests.post(
            endpoint,
            headers=self.headers,
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        return response.json()


async def firecrawl_search_async(original_url: str, query: str = None) -> str:
    """
    Firecrawl main function
    Supports multiple modes: scrape (single page), crawl (full site), search, map (site map)
    """
    settings = await load_settings()
    
    def sync_crawler():
        try:
            # Get configuration
            base_url = settings['webSearch'].get('firecrawl_url', 'https://api.firecrawl.dev/v2')
            api_key = settings['webSearch'].get('firecrawl_api_key', '')
            mode = settings['webSearch'].get('firecrawl_mode', 'scrape')
            
            # Initialize client
            client = FirecrawlClient(base_url, api_key)
            
            # Execute different operations based on mode
            if mode == 'scrape':
                # Single page scrape
                result = client.scrape(
                    original_url,
                    formats=["markdown", "html"],
                    onlyMainContent=True  # Only get main content
                )
                
                if result.get("success") and result.get("data"):
                    data = result["data"]
                    markdown = data.get("markdown", "")
                    metadata = data.get("metadata", {})
                    title = metadata.get("title", "Untitled page")
                    
                    return f"# {title}\n\n{markdown}"
                else:
                    return f"Firecrawl scrape failed: {result.get('error', 'Unknown error')}"
            
            elif mode == 'crawl':
                # Full site crawl
                result = client.crawl(
                    original_url,
                    limit=10,  # Limit pages to avoid overly long results
                    scrapeOptions={
                        "formats": ["markdown"],
                        "onlyMainContent": True
                    }
                )
                
                if result.get("status") == "completed":
                    pages = result.get("data", [])
                    total = result.get("total", 0)
                    
                    content_parts = [f"# Site Crawl Results\n\nRetrieved {total} pages:\n"]
                    
                    for i, page in enumerate(pages[:5], 1):  # Show at most 5 pages
                        md = page.get("markdown", "")
                        meta = page.get("metadata", {})
                        title = meta.get("title", f"Page {i}")
                        url = meta.get("sourceURL", original_url)
                        
                        content_parts.append(f"\n## {title}\n{md[:2000]}...\n[Source]({url})")
                    
                    return "\n".join(content_parts)
                else:
                    return f"Firecrawl crawl failed: {result.get('error', 'Unknown error')}"
            
            elif mode == 'search':
                # Search mode - when query is passed instead of URL
                search_query = query or original_url  # If no separate query, use URL as query
                result = client.search(
                    search_query,
                    limit=5,
                    scrape_options={"formats": ["markdown"]}
                )
                
                if result.get("success") and result.get("data"):
                    items = result["data"]
                    content_parts = [f"# Search Results: {search_query}\n"]
                    
                    for i, item in enumerate(items, 1):
                        title = item.get("title", "No title")
                        url = item.get("url", "")
                        desc = item.get("description", "")
                        markdown = item.get("markdown", "")
                        
                        content_parts.append(f"\n## {i}. {title}\n{desc}\n")
                        if markdown:
                            content_parts.append(f"{markdown[:1500]}...")
                        content_parts.append(f"[Source]({url})")
                    
                    return "\n".join(content_parts)
                else:
                    return f"Firecrawl search failed: {result.get('error', 'Unknown error')}"
            
            elif mode == 'map':
                # Site map mode
                result = client.map(original_url)
                
                if result.get("success") and result.get("links"):
                    links = result["links"]
                    content_parts = [f"# Site Map: {original_url}\n\nFound {len(links)} links:\n"]
                    
                    for link in links[:20]:  # Limit display count
                        title = link.get("title", "No title")
                        url = link.get("url", "")
                        desc = link.get("description", "")
                        content_parts.append(f"- [{title}]({url}) - {desc}")
                    
                    return "\n".join(content_parts)
                else:
                    return f"Firecrawl map generation failed: {result.get('error', 'Unknown error')}"
            
            else:
                return f"Unknown Firecrawl mode: {mode}"
                
        except requests.RequestException as e:
            return f"Firecrawl request failed: {str(e)}"
        except Exception as e:
            return f"Firecrawl processing failed: {str(e)}"

    try:
        # Firecrawl self-deployed versions usually don't need to check robots.txt (handled internally by the service)
        # But official API versions are recommended to keep the check
        settings = await load_settings()
        base_url = settings['webSearch'].get('firecrawl_url', '')
        
        # If using official API, check robots.txt
        if 'api.firecrawl.dev' in base_url:
            if not await check_robots_txt(original_url):
                raise PermissionError(f"Compliance denied: Target website disallows scraping")
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, sync_crawler)
    except Exception as e:
        print(f"Async execution error: {e}")
        return str(e)


firecrawl_tool = {
    "type": "function",
    "function": {
        "name": "firecrawl_search_async",
        "description": "Retrieve web page content through the Firecrawl service. Supports single page scrape, full site crawl, search, and site map modes. Can handle JavaScript-rendered pages and returns structured Markdown content.",
        "parameters": {
            "type": "object",
            "properties": {
                "original_url": {
                    "type": "string",
                    "description": "URL address or search query (when in search mode).",
                },
                "query": {
                    "type": "string",
                    "description": "Optional, specific search term when using search mode. If not provided, original_url will be used as the query.",
                }
            },
            "required": ["original_url"],
        },
    },
}

from bs4 import BeautifulSoup
import re

async def simple_fetch_async(url):
    """
    Improved web page scraping tool, returns structured cleaned content
    Supports scraping intranet and extranet pages
    """
    def sync_fetch():
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                return response.text
            else:
                return None, f"Failed to fetch web page info for {url}, status code: {response.status_code}"
        except requests.RequestException as e:
            return None, f"Failed to fetch web page info for {url}, error: {str(e)}"
    
    def clean_and_extract(html_content):
        """Extract and clean HTML content, return structured data"""
        if not html_content:
            return None
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Remove unnecessary tags
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe', 'noscript']):
            tag.decompose()
        
        structured_content = {
            'title': '',
            'sections': []
        }
        
        # Extract page title
        title_tag = soup.find('title')
        if title_tag:
            structured_content['title'] = title_tag.get_text().strip()
        
        # Extract main content area (prioritize main, article, or div with id/class containing content)
        main_content = soup.find('main') or soup.find('article') or \
                      soup.find('div', {'id': re.compile(r'content|main', re.I)}) or \
                      soup.find('div', {'class': re.compile(r'content|main|article', re.I)}) or \
                      soup.body or soup
        
        # Extract all headings and paragraphs
        for element in main_content.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p']):
            text = element.get_text(separator=' ', strip=True)
            
            # Clean text: remove extra whitespace
            text = re.sub(r'\s+', ' ', text).strip()
            
            # Filter out too short content (may be noise)
            if len(text) < 3:
                continue
            
            if element.name.startswith('h'):
                # Heading
                level = int(element.name[1])
                structured_content['sections'].append({
                    'type': 'heading',
                    'level': level,
                    'content': text
                })
            else:
                # Paragraph
                structured_content['sections'].append({
                    'type': 'paragraph',
                    'content': text
                })
        
        return structured_content
    
    try:
        # Check robots.txt compliance
        if not await check_robots_txt(url):
            return {
                'error': 'PermissionError',
                'message': 'Compliance denied: Target website disallows scraping'
            }
        
        loop = asyncio.get_event_loop()
        html_content = await loop.run_in_executor(None, sync_fetch)
        
        if isinstance(html_content, tuple):
            # Returns error message
            return {
                'error': 'FetchError',
                'message': html_content[1]
            }
        
        # Clean and extract structured content
        structured_data = clean_and_extract(html_content)
        
        if not structured_data or not structured_data['sections']:
            return {
                'error': 'ParseError',
                'message': 'Unable to extract valid content from page'
            }
        
        return structured_data
        
    except Exception as e:
        return {
            'error': 'UnexpectedError',
            'message': str(e)
        }


# OpenAI function definition
simple_fetch_tool = {
    "type": "function",
    "function": {
        "name": "simple_fetch_async",
        "description": "Crawl web page content from a specified URL. Supports both intranet and extranet addresses.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL address to be crawled.",
                },
            },
            "required": ["url"],
        },
    },
}

async def markdown_new_async(original_url):
    """
    Convert web page to Markdown format using the markdown.new service
    """
    
    def sync_crawler():
        # Construct markdown.new service URL
        detail_url = "https://markdown.new/"
        url = f"{detail_url}{original_url}"
        
        try:
            # Add basic User-Agent to avoid blocking
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            # Make request
            response = requests.get(url, headers=headers, timeout=60)
            
            if response.status_code == 200:
                # markdown.new returns plain text markdown content by default
                return response.text
            else:
                return f"Failed to fetch web page info for {original_url}, status code: {response.status_code}"
                
        except requests.RequestException as e:
            return f"Failed to fetch web page info for {original_url}, error: {str(e)}"

    try:
        # Check robots.txt compliance (consistent with your original logic)
        if not await check_robots_txt(original_url):
            raise PermissionError(f"Compliance denied: Target website disallows scraping")
            
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, sync_crawler)
    except Exception as e:
        print(f"Async execution error in markdown_new: {e}")
        return str(e)
    
markdown_new_tool = {
    "type": "function",
    "function": {
        "name": "markdown_new_async",
        "description": "Retrieve web page content from a specified URL through the markdown.new service, automatically converting it to structured Markdown text. This tool is very lightweight and efficient, suitable for extranet links. Do not pass localhost or intranet addresses (they will be inaccessible).",
        "parameters": {
            "type": "object",
            "properties": {
                "original_url": {
                    "type": "string",
                    "description": "The original URL to be crawled. Must be a complete URL starting with http or https.",
                },
            },
            "required": ["original_url"],
        },
    },
}