import base64
import os
import re

import requests
from py.get_setting import load_settings,get_host,get_port,UPLOAD_FILES_DIR
from openai import AsyncClient
import uuid

from py.llm_tool import get_image_base64, get_image_media_type
async def pollinations_image(prompt: str, width=512, height=512, model="flux"):
    settings = await load_settings()
    
    # Check if the provided values are default ones, if so, override them with settings
    if width == 512:
        width = settings["text2imgSettings"]["pollinations_width"]
    if height == 512:
        height = settings["text2imgSettings"]["pollinations_height"]
    if model == "flux":
        model = settings["text2imgSettings"]["pollinations_model"]
    
    # Convert prompt into a URL-compatible format
    prompt = prompt.replace(" ", "%20")
    url = f"https://image.pollinations.ai/prompt/{prompt}?width={width}&height={height}&model={model}&nologo=true&enhance=true&private=true&safe=true"
    res_data = requests.get(url).content
    image_id = str(uuid.uuid4())
    # Save the image to local UPLOAD_FILES_DIR with filename image_id, return local file path
    with open(f"{UPLOAD_FILES_DIR}/{image_id}.png", "wb") as f:
        f.write(res_data)
    return f"![image]({url})"

pollinations_image_tool = {
    "type": "function",
    "function": {
        "name": "pollinations_image",
        "description": "Generate images from English prompts and return a markdown image link. You must send the original markdown format to the user so they can see the image directly.\nWhen you need to send an image, place the image URL inside a markdown image tag, for example:\n\n![ImageName](ImageURL)\n\nThe image markdown must be on its own line and occupy a line by itself!",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "English prompt for generating the image, for example: A little girl in a red hat. You can enrich your prompt as much as possible for better results.",
                },
                "width": {
                    "type": "number",
                    "description": "Image width",
                    "default":512
                },
                "height": {
                    "type": "number",
                    "description": "Image height",
                    "default": 512
                },
                "model": {
                    "type": "string",
                    "description": "Model to use",
                    "default": "flux",
                    "enum": ["flux", "turbo"],
                }
            },
            "required": ["prompt"],
        },
    },
}

async def openai_image(prompt: str, size="auto"):
    settings = await load_settings()

    # Check if the provided values are default ones, if so, override them with settings
    if size == "auto":
        size = settings["text2imgSettings"]["size"]

    model = settings["text2imgSettings"]["model"]

    base_url = settings["text2imgSettings"]["base_url"]
    api_key = settings["text2imgSettings"]["api_key"]
    try:
        client = AsyncClient(api_key=api_key,base_url=base_url)
    
        response = await client.images.generate(prompt=prompt, size=size, model=model)
    except Exception as e:
        print(e)
        return f"ERROR: {e}"
    
    res_url = response.data[0].url
    res = f"![image]({res_url})"
    print(res)
    if res_url is None:
        res = response.data[0].b64_json
        HOST = get_host()
        if HOST == '0.0.0.0':
            HOST = '127.0.0.1'
        PORT = get_port()
        image_id = str(uuid.uuid4())
        # Save the image to local UPLOAD_FILES_DIR with filename image_id, return local file path
        with open(f"{UPLOAD_FILES_DIR}/{image_id}.png", "wb") as f:
            f.write(base64.b64decode(res))
        res = f"![image](http://{HOST}:{PORT}/uploaded_files/{image_id}.png)"
    else:
        res_data = requests.get(res_url).content
        image_id = str(uuid.uuid4())
        # Save the image to local UPLOAD_FILES_DIR with filename image_id, return local file path
        with open(f"{UPLOAD_FILES_DIR}/{image_id}.png", "wb") as f:
            f.write(res_data)
    return res
        
openai_image_tool = {
    "type": "function",
    "function": {
        "name": "openai_image",
        "description": "Generate images from English prompts and return a markdown image link. You must send the original markdown format to the user so they can see the image directly.\nWhen you need to send an image, place the image URL inside a markdown image tag, for example:\n\n![ImageName](ImageURL)\n\nThe image markdown must be on its own line and occupy a line by itself!",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "English prompt for generating the image, for example: A little girl in a red hat. You can enrich your prompt as much as possible for better results.",
                },
                "size": {
                    "type": "string",
                    "description": "Image size, defaults to auto",
                    "default": "auto",
                    "enum": ["auto","1024x1024", "1536x1024", "1024x1536", "256x256", "512x512", "1792x1024", "1024x1792"],
                }
            },
            "required": ["prompt"],
        },
    },
}

def process_image_content(text):
    # Regex to match content inside ![]()
    pattern = r'!\[.*?\]\((.*?)\)'

    def replace_match(match):
        content = match.group(1)

        # Check if it is base64 data
        if content.startswith('data:image'):
            # Extract base64 part (assumes format: data:image/xxx;base64,actual_data)
            base64_data = content.split(',', 1)[1]
            HOST = get_host()
            if HOST == '0.0.0.0':
                HOST = '127.0.0.1'
            PORT = get_port()
            image_id = str(uuid.uuid4())

            # Ensure upload directory exists
            os.makedirs(UPLOAD_FILES_DIR, exist_ok=True)

            # Save image to local disk
            file_path = f"{UPLOAD_FILES_DIR}/{image_id}.png"
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(base64_data))

            # Return new image link
            return f"![image](http://{HOST}:{PORT}/uploaded_files/{image_id}.png)"
        else:
            # If it is a regular URL, return the original match
            return match.group(0)

    # Use re.sub for replacement
    result = re.sub(pattern, replace_match, text)
    return result


async def openai_chat_image(prompt: str,img_url_list: list = []):
    settings = await load_settings()

    model = settings["text2imgSettings"]["model"]
    content = ""
    base_url = settings["text2imgSettings"]["base_url"]
    api_key = settings["text2imgSettings"]["api_key"]
    try:
        client = AsyncClient(api_key=api_key,base_url=base_url)
        if img_url_list:
            content = []
            for img_url in img_url_list:
                if img_url.startswith("http"):
                    base64_image = await get_image_base64(img_url)
                    media_type = await get_image_media_type(img_url)
                    img_url = f"data:{media_type};base64,{base64_image}"
                content.append({"type": "image_url", "image_url": {"url": img_url}})
            content.append({"type": "text", "text": prompt})
        else:
            content = prompt
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role":"user",
                    "content":content
                }
            ]
        )
    except Exception as e:
        print(e)
        return f"ERROR: {e}"
    
    if response:
        res = response.choices[0].message.content
        res = process_image_content(res)
    return res
        
openai_chat_image_tool = {
    "type": "function",
    "function": {
        "name": "openai_chat_image",
        "description": "Generate or edit images from English prompts and return a markdown image link. You must send the original markdown format to the user so they can see the image directly.\nWhen you need to send an image, place the image URL inside a markdown image tag, for example:\n\n![ImageName](ImageURL)\n\nThe image markdown must be on its own line and occupy a line by itself!",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "English prompt for generating or editing images, for example: `A little girl in a red hat` or `Change the girl's hat to white`. You can enrich your prompt as much as possible for better results.",
                },
                "img_url_list": {
                    "type": "array",
                    "description": "Optional field for image editing tasks. Each element in the list must be an image URL. URLs can be local files uploaded by the user, e.g., http://127.0.0.1:3456/1.jpg, or public image URLs.",
                },
            },
            "required": ["prompt"],
        },
    },
}