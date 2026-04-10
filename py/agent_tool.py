import json
from py.get_setting import HOST,PORT
from openai import AsyncOpenAI
async def get_agent_tool(settings):
    tool_agent_list = []
    for agent_id,agent_config in settings['agents'].items():
        if agent_config['enabled']:
            tool_agent_list.append({"agent_id": agent_id, "agent_skill": agent_config["system_prompt"]})
    if len(tool_agent_list) > 0:
        tool_agent_list = json.dumps(tool_agent_list, ensure_ascii=False, indent=4)
        agent_tool = {
            "type": "function",
            "function": {
                "name": "agent_tool_call",
                "description": f"Call a specific Agent tool based on the agent_skill provided by the Agent and return the result. Currently available Agent tool IDs and their agent_skills: {tool_agent_list}",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_id": {
                            "type": "string",
                            "description": "The ID of the Agent tool to call",
                        },
                        "query": {
                            "type": "string",
                            "description": "The question to send to the Agent tool",
                        }
                    },
                    "required": ["agent_id", "query"]
                }
            }
        }
    else:
        agent_tool = None
    return agent_tool

async def agent_tool_call(agent_id, query):
    try:
        client = AsyncOpenAI(
            api_key="super-secret-key",
            base_url=f"http://{HOST}:{PORT}/v1"
        )
        response = await client.chat.completions.create(
            model=agent_id,
            messages=[
                {"role": "user", "content": query}
            ]
        )
        res = response.choices[0].message.content
        return str(res)
    except Exception as e:
        print(f"Error: {e}")
        return str(e)

