from pathlib import Path
from google import genai
import os
import json, asyncio, subprocess
from google.genai import types
from openai import AsyncOpenAI
from pydantic import BaseModel
from .tools import has_function_calls, get_function_calls, collect_api_items, switch_to_paths, check_if_path, check_token_count
from .utils import check_api_percentage, check_api_path


class PathResponse(BaseModel):
    path: str

class DocumerConfig:
    def __init__(self, api_key, sub_api_key, repository_url, model, sub_model, tools, fn_dict, thinking_level):
        self.api_key = api_key
        self.sub_api_key = sub_api_key
        self.repository_url = repository_url
        self.model = model
        self.sub_model = sub_model
        self.root_directory = Path(__file__).resolve().parent.parent
        self.repo_name = repository_url.rsplit('/')[-1]
        self.owner = repository_url.rsplit('/')[-2]
        self.slug = '/'.join([self.owner, self.repo_name])
        self.tools = types.Tool(function_declarations=tools)
        self.fn_dict = fn_dict
        self.thinking_level = thinking_level

class Documer:
    def __init__(self, config):
        self.config = config
        self.agents = DocumerAgent(config)

    def initialize_repo(self):
        subprocess.run(['git', 'clone', '--depth', '1', self.config.repository_url, f'./repository/{self.config.repo_name}'])
        subprocess.run(['bash', 'filter_repo.sh', f'./repository/{self.config.repo_name}'])
        os.chdir(f'repository/{self.config.repo_name}')

    

class DocumerAgent:
    def __init__(self, config):
        self.config = config
        self.gemini_client = genai.Client(api_key=config.api_key)
        self.openai_client = AsyncOpenAI(api_key=config.sub_api_key)
    
    async def src_architect_agent(self):
        with open(f"{self.config.root_directory}/prompts/src_architect_agent.md", 'r') as f:
            prompt_raw = f.read()
        prompt = prompt_raw.replace("{{slug}}", self.config.slug)
        gemini_config = types.GenerateContentConfig(tools=self.config.tools[:1], 
            thinking_config=types.ThinkingConfig(
                include_thoughts=True,
                thinking_level=self.config.thinking_level
            )
        )
        chat = self.gemini_client.aio.chats.create(model=self.config.model, config=gemini_config)
        response = await chat.send_message(
            prompt
        )
        while has_function_calls(response):
            calls = get_function_calls(response)
            function_response_parts = []

            tasks = [self.config.fn_dict[call['name']](**call['args']) for call in calls]
            results = await asyncio.gather(*tasks)
            for i, call in enumerate(calls):
                function_response = types.Part.from_function_response(
                    name=call['name'],
                    response={"result": results[i]}
                )
                function_response_parts.append(function_response)

            response = await chat.send_message(function_response_parts)
        
        return response.candidates[0].content.parts[0].text

    async def planner_agent(self, report):
        schema = {
  "type": "object",
  "properties": {
    "plan": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "title": {
            "type": "string"
          },
          "concept": {
            "type": "string"
          },
          "api_items": {
            "type": "array",
            "items": {
              "type": "string"
            }
          }
        },
        "required": ["title", "concept"],
        "propertyOrdering": ["title", "concept", "api_items"]
      }
    }
  },
  "required": ["plan"],
  "propertyOrdering": ["plan"]
}
        with open(f"{self.config.root_directory}/prompts/planner_agent.md", 'r') as f:
            prompt_raw = f.read()
        prompt = prompt_raw.replace("{{report}}", report).replace("{{repository}}", self.config.repository_url)
        gemini_config = types.GenerateContentConfig(
        tools=[
            types.Tool(google_search=types.GoogleSearch()),
            types.Tool(url_context=types.UrlContext())
        ], 
        thinking_config=types.ThinkingConfig(
            include_thoughts=False,
            thinking_level=self.config.thinking_level
        ),
        response_mime_type="application/json",
        response_schema=schema
        )
        chat = self.gemini_client.aio.chats.create(model=self.config.model, config=gemini_config)
        response = await chat.send_message(
            prompt
        )
        plan = json.loads(response.candidates[0].content.parts[0].text)
        return plan["plan"]
    
    async def src_path_extractor_agent(self, report):
        prompt = f"Based on the text, output the source code path {report}"
        schema = { "type": "object", "properties": { "path": { "type": "string" } }, "required": [ "path" ], "propertyOrdering": [ "path" ] }

        gemini_config = types.GenerateContentConfig(
            tools=[
                types.Tool(google_search=types.GoogleSearch()),
                types.Tool(url_context=types.UrlContext())
            ], 
            thinking_config=types.ThinkingConfig(
                include_thoughts=False,
                thinking_level=self.config.thinking_level
            ),
            response_mime_type="application/json",
            response_schema=schema
        )
        chat = self.gemini_client.aio.chats.create(model=self.model, config=gemini_config)
        response = await chat.send_message(
            prompt
        )
        path = json.loads(response.candidates[0].content.parts[0].text)
        if path["path"] == "/":
            src = '.'
        else:
            src = path["path"]

        return src
    
    async def symbol_file_agent(self, symbol):
        results = subprocess.run(f"rg -i '{symbol}'", shell=True, capture_output=True, text=True).stdout
        token_count = await check_token_count(results)
        if not token_count:
            results = subprocess.run(f"rg -i '{symbol}' --files-with-matches", shell=True, capture_output=True, text=True).stdout
        with open(f"{self.config.root_directory}/symbol_getter.md") as f:
            prompt_raw = f.read()
        prompt = prompt_raw.replace("{{symbol}}", symbol).replace('{{repository}}', self.config.slug).replace("{{grep_results}}", results)
        response = await self.config.gemini_client.responses.parse(
            model=self.config.sub_model,
            input=prompt,
            text_format=PathResponse
        )
        path = response.output_parsed.path
        return {symbol: path}

    async def symbol_web_agent(self, symbol):
        with open(f"{self.config.root_directory}/prompts/symbol_search.md") as f:
            prompt_raw = f.read()
        prompt = prompt_raw.replace("{{symbol}}", symbol).replace('{{repository}}', self.config.slug)
        response = await self.config.gemini_client.responses.create(
            model=self.config.model,
            input=prompt,
            tools=[
                {
                    "type": "web_search"
                }
            ]
        )
        text = response.output_text
        return {symbol: text}
    
    async def semantic_search_agent(self, symbol, concept, title):
        with open(f"{self.config.root_directory}/prompts/semantic_search_agent.md") as f:
            prompt_raw = f.read()
        prompt = prompt_raw.replace("{{slug}}", self.config.slug).replace("{{symbol}}", symbol).replace("{{concept}}", concept).replace("{{title}}", title)
        chat = self.gemini_client.aio.chats.create(model=self.config.model)
        response = await chat.send_message(
            prompt
        )
        items = json.loads(response.candidates[0].content.parts[0].text)
        results = []
        for k, v in items.values():
            result = subprocess.run(f"rg -i '{v}'", shell=True, capture_output=True, text=True).stdout
            results.append(*result)
        path = await self.symbol_file_agent(results)
        return path
    
    async def page_gen(self, prompt_raw, section,):
        schema = {
  "type": "object",
  "properties": {
    "blocks": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "type": {
            "type": "string",
            "enum": [
              "h1",
              "h2",
              "h3",
              "p",
              "list",
              "code_block"
            ]
          },
          "content": {
            "type": "string",
            "maxLength": 1000
          },
          "ordered": {
            "type": "boolean"
          },
          "items": {
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "code": {
            "type": "string"
          },
          "variant": {
            "type": "string",
            "enum": [
              "info",
              "warning",
              "danger",
              "tip",
              "note"
            ]
          },
          "title": {
            "type": "string",
            "maxLength": 80
          }
        },
        "required": [
          "type"
        ],
        "propertyOrdering": [
          "type",
          "content",
          "ordered",
          "items",
          "code",
          "variant",
          "title"
        ]
      }
    }
  },
  "required": [
    "blocks"
  ],
  "propertyOrdering": [
    "blocks"
  ]
}
        api_items = []
        for d in section["api_items"]:
            for k, v in d.items():
                if Path(v).exists():
                    with open(v, 'r') as f:
                        file_content = f.read()
                    api_items.append({k: file_content})
        prompt = prompt_raw.replace('{{slug}}', self.congif.slug).replace('{{title}}', section["title"]).replace('{{concept}}', section["concept"]).replace('{{api_items}}', str(api_items))
        gemini_config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(
                include_thoughts=False,
                thinking_level=self.config.thinking_level
            ),
            response_mime_type="application/json",
            response_schema=schema
        )
        chat = self.gemini_client.aio.chats.create(model=self.congif.model, config=gemini_config)
        response = await chat.send_message(
            prompt
        )
        page = json.loads(response.candidates[0].content.parts[0].text)
        return page