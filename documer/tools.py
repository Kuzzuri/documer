import os
from pathlib import Path
from collections import defaultdict
import tiktoken

def has_function_calls(response):
    if not response.candidates or not response.candidates[0].content:
        return False
    
    parts = response.candidates[0].content.parts

    if not parts:
        return False
    
    for part in parts:
        if part.function_call:
            return True
    return False

def get_function_calls(response):
    function_calls = []
    
    if not response.candidates:
        return function_calls
    
    parts = response.candidates[0].content.parts
    
    for part in parts:
        if part.function_call:
            function_calls.append({
                'name': part.function_call.name,
                'args': dict(part.function_call.args)
            })
    
    return function_calls

async def collect_api_items(plan):
    api_items = set()
    for part in plan:
        items = part['api_items']
        api_items.update(items)
    return api_items

async def switch_to_paths(plan, d):
    cwd = os.getcwd()
    for item in plan:
        c = 0
        for i in item["api_items"]:
            if Path(os.path.join(cwd, d[i])).exists():
                path_joined = os.path.join(cwd, d[i])
            else:
                path_joined = os.path.join(cwd, d[i].split('/', 1)[-1])
            item["api_items"][c] = {item["api_items"][c]: path_joined}
            c += 1
    return plan

async def check_if_path(symbol):
    if Path(symbol).exists():
        return symbol
    else:
        return False
    
async def check_token_count(text, model="gpt-5-nano"):
    encoding = tiktoken.encoding_for_model(model)
    tokens = encoding.encode(text)
    token_count = len(tokens)
    if token_count > 24000:
        return False
    else:
        return True

