import json
from python_a2a import A2AClient

async def get_a2a_tool(settings):
    a2a_agent_list = []
    for a2a_agent_url,a2a_agent_config in settings["a2aServers"].items():
        if a2a_agent_config["enabled"]:
            a2a_agent_list.append({"agent_url": a2a_agent_url, "agent_description": a2a_agent_config["description"], "agent_skills": a2a_agent_config["skills"]})
    if len(a2a_agent_list) > 0:
        a2a_agent_list = json.dumps(a2a_agent_list, ensure_ascii=False, indent=4)
        agent_tool = {
            "type": "function",
            "function": {
                "name": "a2a_tool_call",
                "description": f"Refer to the A2A agent configuration to call a specific A2A service and return the result. Currently available A2A servers: {a2a_agent_list}",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_url": {
                            "type": "string",
                            "description": "The URL of the A2A agent to call",
                        },
                        "query": {
                            "type": "string",
                            "description": "The question to send to the A2A agent",
                        }
                    },
                    "required": ["agent_url", "query"]
                }
            }
        }
        return agent_tool
    else:
        return None

async def a2a_tool_call(agent_url, query):
    client = A2AClient(agent_url)
    response = client.ask(query)
    return response
