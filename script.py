#!/usr/bin/env python3

from documer.clients import DocumerConfig, Documer
from documer.agent_tools import list_directory, grep, find
import sys, asyncio, subprocess
import os, json

fn_dict = {
    "list_directory": list_directory,
    "find": find,
    "grep": grep
}

list_directory_dict = {
    #"type": "function", 
    "name": "list_directory",
    "description": "Returns a list of files and folders inside the specified folder. Same functionality as 'ls' command in linux.",
    "parameters": {
        "type": "object",
        "properties": {
            "path":{
                "type": "string",
                "description": "Full path of the targeted directory (eg., './repository/targeted_directory')."
            }
        },
        "required": ["path"]
    }
}

grep_dict = {
    #"type": "function", 
    "name": "grep",
    "description": "Searches file contents for a pattern. Returns matching lines with file paths.",
    "parameters": {
        "type": "object",
        "properties": {
            "pattern":{
                "type": "string",
                "description": "Text pattern to search for in file contents."
            }
        },
        "required": ["pattern"]
    }
}

find_dict = {
    #type": "function", 
    "name": "find",
    "description": "Finds files and directories by name. Returns matching paths.",
    "parameters": {
        "type": "object",
        "properties": {
            "pattern":{
                "type": "string",
                "description": "Name pattern to match (e.g., 'README', 'function_name')."
            }
        },
        "required": ["pattern"]
    }
}


async def main():
    try:
        repo =os.getenv('REPOSITORY')
        config = DocumerConfig( api_key=os.getenv('GEMINI_API_KEY'), sub_api_key=os.getenv('OPENAI_API_KEY'),repository_url=repo, model="gemini-3-flash-preview", sub_model="gpt-5-nano", tools=[list_directory_dict, grep_dict, find_dict], fn_dict=fn_dict, thinking_level="HIGH")

        documer = Documer(config)
        result = await documer.generate_documentation()
        print(json.dumps(result))
    finally:
        subprocess.run('rm -rf ./repository/*', shell=True)


asyncio.run(main())