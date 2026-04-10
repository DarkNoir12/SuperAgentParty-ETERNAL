from py.get_setting import load_settings

async def auto_behavior(behaviorType="delay", time="00:00:00",prompt="",days=[],repeatNumber=1,isInfiniteLoop=False):
    # Load settings
    settings = await load_settings()
    if behaviorType == "time":
        settings["behaviorSettings"]["behaviorList"].append(
            {
                "enabled": True,
                "trigger": {
                    "type": "time",
                    "time":{
                        "timeValue": time, 
                        "days": days
                    },
                    "noInput":{
                        "latency": 30, 
                    },
                    "cycle":{
                        "cycleValue": "00:00:30", 
                        "repeatNumber": 1, 
                        "isInfiniteLoop": False, 
                    }
                },
                "action": {
                    "type": "prompt",
                    "prompt": "Time's up, "+prompt,
                    "random":{
                        "events":[""],
                        "type":"random",
                        "orderIndex":0,
                    }
                }
            }
        )
    elif behaviorType == "delay":
        settings["behaviorSettings"]["behaviorList"].append(
            {
                "enabled": True,
                "trigger": {
                    "type": "cycle",
                    "time":{
                        "timeValue": "00:00:00",
                        "days": []
                    },
                    "noInput":{
                        "latency": 30,
                    },
                    "cycle":{
                        "cycleValue": time,
                        "repeatNumber": repeatNumber,
                        "isInfiniteLoop": isInfiniteLoop,
                    }
                },
                "action": {
                    "type": "prompt",
                    "prompt": "Time's up, "+prompt,
                    "random":{
                        "events":[""],
                        "type":"random",
                        "orderIndex":0,
                    }
                }
            }
        )
    settings["behaviorSettings"]['enabled'] = True
    return settings


auto_behavior_tool = {
    "type": "function",
    "function": {
        "name": "auto_behavior",
        "description": "Use this tool when you need to automatically execute certain behaviors at a specific time or after a delay. For example, you can set up automatic greeting messages at a specific time every day, or set up automatic execution of certain tasks at a specific time.",
        "parameters": {
            "type": "object",
            "properties": {
                "behaviorType": {
                    "type": "string",
                    "description": "The behavior type, either 'time' or 'delay'; 'time' means execute at a specific time (e.g., remind me about a meeting at 3 o'clock), 'delay' means execute after a time interval (e.g., remind me about a meeting in 5 minutes)",
                    "enum": ["time", "delay"],
                },
                "time": {
                    "type": "string",
                    "description": "Time in HH:MM:SS format (24-hour). For 'time' type, it indicates execution at this time point. For 'delay' type, it indicates the interval before execution",
                },
                "prompt": {
                    "type": "string",
                    "description": "Task description, e.g., Please remind the user about the meeting immediately, Please send a greeting message to the user immediately",
                },
                "days": {
                    "type": "array",
                    "description": "For 'time' type, indicates which days to execute. For example: [1, 2] means execute on Monday and Tuesday, [0] means only on Sunday, [] means no repetition, [1, 2, 3, 4, 5, 6, 0] means execute every day",
                    "items": {
                        "type": "number",
                        "enum": [0, 1, 2, 3, 4, 5, 6],
                    },
                    "default": [],
                },
                "repeatNumber": {
                    "type": "number",
                    "description": "For 'delay' type, indicates the number of repetitions. For example: 3 means repeat 3 times. repeatNumber can only be between 1 and 100",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 1,
                },
                "isInfiniteLoop": {
                    "type": "boolean",
                    "description": "For 'delay' type, indicates whether to loop infinitely. For example: True means infinite loop, False means no looping",
                    "default": False,
                }
            },
            "required": ["prompt", "behaviorType", "time"],
        },
    },
}

    