from pathlib import Path
from google import genai
import os, asyncio
import json, asyncio, subprocess
from google.genai import types
from openai import AsyncOpenAI
from pydantic import BaseModel
from .tools import has_function_calls, get_function_calls, collect_api_items, switch_to_paths, check_if_path, check_token_count
from .utils import check_api_percentage, check_api_path, log_retry
import httpx
from anthropic import AsyncAnthropic
import tenacity
from tenacity import retry, stop_after_attempt, retry_if_exception_type


class PathResponse(BaseModel):
    path: str

class DocumerConfig:
    def __init__(self, id, api_key, sub_api_key, validator_api_key, repository_url, model, sub_model, tools, fn_dict, thinking_level, token, agent_model):
        self.id = id
        self.api_key = api_key
        self.sub_api_key = sub_api_key
        self.repository_url = repository_url
        self.model = model
        self.sub_model = sub_model
        self.root_directory = Path.cwd()
        self.repo_name = repository_url.rsplit('/')[-1]
        self.owner = repository_url.rsplit('/')[-2]
        self.slug = '/'.join([self.owner, self.repo_name])
        self.tools = tools
        self.fn_dict = fn_dict
        self.thinking_level = thinking_level
        self.token = token
        self.agent_model = agent_model
        self.validator_api_key = validator_api_key

class Documer:
    def __init__(self, config):
        self.config = config
        self.agents = DocumerAgent(config)
        self.url = 'http://127.0.0.1:8000/documentation/pages/'
        self.obj_url = f'http://127.0.0.1:8000/documentation/?id={self.config.id}'
    
    async def generate_documentation(self):
        async with httpx.AsyncClient() as Client:
            print(f'UPDATE:Analyzing Repository', flush=True)
            self.initialize_repo()
            print(f'UPDATE:Generating Documentation Plan', flush=True)
            if self.config.agent_model == 'D1M':
                plan, src = await self.generate_plan_pro(Client)
            else:
                plan, src = await self.generate_plan(Client)
            print(f'UPDATE:Reading the code', flush=True)
            os.chdir(src)
            plan_final = await self.get_symbol_files(plan)
            results = await self.doc_generator(plan_final)
            tasks = [self.post_page(Client, r, self.config.token) for r in results]
            result = await asyncio.gather(*tasks, return_exceptions=True)
            await self.post_status(Client, self.config.token)

    def initialize_repo(self):
        subprocess.run(
    ['git', 'clone', '--depth', '1', self.config.repository_url, f'./repository/{self.config.repo_name}'],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL
)
        subprocess.run(['bash', 'filter_repo.sh', f'./repository/{self.config.repo_name}'])
        os.chdir(f'repository/{self.config.repo_name}')

    async def generate_plan(self, Client):
        report = await self.agents.src_architect_agent()
        tasks = [self.agents.planner_agent(report), self.agents.src_path_extractor_agent(report)]
        plan, src = await asyncio.gather(*tasks)
        await self.post_plan(Client, plan, self.config.token)
        return plan["plan"], src

    async def generate_plan_pro(self, Client):
        report = await self.agents.src_architect_agent()
        tasks = [self.agents.planner_agent(report, False), self.agents.src_path_extractor_agent(report)]
        plan_raw, src = await asyncio.gather(*tasks)
        plan = await self.agents.validate_plan(plan_raw["plan"])
        await self.post_plan(Client, plan, self.config.token)
        return plan["plan"], src

    async def get_symbol_files(self, plan):
        sets = await collect_api_items(plan)
        percentage = check_api_percentage(sets)
        if percentage:
            tasks = [self.get_symbols_fallback_web(s) for s in sets]
        else:
            tasks = [self.get_symbols_fallback_semantic(s) for s in sets]
        symbols = await asyncio.gather(*tasks)
        plan_with_content = await self.add_plan_contents(plan, symbols)
        return plan_with_content
    
    async def get_symbols_fallback_web(self, symbol):
        symbol_json = await self.agents.symbol_file_agent(symbol)
        cwd = os.getcwd()
        if Path(os.path.join(cwd, symbol_json[symbol])).exists():
            file_path = os.path.join(cwd, symbol_json[symbol])
            with open(file_path, 'r') as f:
                file_content = f.read()
        elif Path(os.path.join(cwd, symbol_json[symbol].split('/', 1)[-1])).exists():
            file_path = os.path.join(cwd, symbol_json[symbol].split('/', 1)[-1])
            with open(file_path, 'r') as f:
                file_content = f.read()
        else:
            file_text = await self.agents.symbol_web_agent(symbol)
            file_content = file_text[symbol]
        return {symbol: file_content}

    async def get_symbols_fallback_semantic(self, symbol):
        symbol_json = await self.agents.symbol_file_agent(symbol)
        cwd = os.getcwd()
        if Path(os.path.join(cwd, symbol_json[symbol])).exists():
            file_path = os.path.join(cwd, symbol_json[symbol])
            with open(file_path, 'r') as f:
                file_content = f.read()
        elif Path(os.path.join(cwd, symbol_json[symbol].split('/', 1)[-1])).exists():
            file_path = os.path.join(cwd, symbol_json[symbol].split('/', 1)[-1])
            with open(file_path, 'r') as f:
                file_content = f.read()
        else:
            file_text = await self.agents.symbol_semantic_agent(symbol)
            file_path = next(iter(file_text.values()))
            try:
                with open(file_path, 'r') as f:
                    file_content = f.read()
            except FileNotFoundError:
                return {symbol: "this api item could not be found in the repository"}
        return {symbol: file_content}

    async def add_plan_contents(self, plan, symbols):
        symbols_dict = {list(d.keys())[0]: list(d.values())[0] for d in symbols}
        for item in plan:
            item["api_items"] = {api: symbols_dict[api] for api in item["api_items"]}
        return plan

    async def doc_generator(self, plan):
        with open(f"{self.config.root_directory}/prompts/page_generator_agent.md", "r") as f:
            prompt_raw = f.read()
        tasks = [self.agents.page_generator_agent(p, prompt_raw) for p in plan]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results
    
    async def post_page(self, client, page, token):
        payload = {"content": page, "title": "shmbala", "documentation": self.config.id}
        headers = {"Content-Type": "application/json", "Authorization": f'Bearer {token}'}
        r = await client.post(self.url, json=payload, headers=headers)
        r.raise_for_status()
        # print(r.json())

    async def post_plan(self, client, plan, token):
        payload = {"plan": plan}
        headers = {"Content-Type": "application/json", "Authorization": f'Bearer {token}'}
        r = await client.patch(self.obj_url, json=payload, headers=headers)
        r.raise_for_status()
        # print(r.json())

    async def post_status(self, client, token):
        payload = {"status": True}
        headers = {"Content-Type": "application/json", "Authorization": f'Bearer {token}'}
        r = await client.patch(self.obj_url, json=payload, headers=headers)
        r.raise_for_status()
        # print(r.json())

class DocumerAgent:
    def __init__(self, config):
        self.config = config
        self.gemini_client = genai.Client(api_key=config.api_key)
        self.openai_client = AsyncOpenAI(api_key=config.sub_api_key)
        self.claude_client = AsyncAnthropic(api_key=config.validator_api_key)
    
    @retry(stop=stop_after_attempt(3), retry=retry_if_exception_type(KeyError), after=log_retry)
    async def src_architect_agent(self):
        with open(f"{self.config.root_directory}/prompts/src_architect_agent.md", 'r') as f:
            prompt_raw = f.read()
        prompt = prompt_raw.replace("{{slug}}", self.config.slug)
        gemini_config = types.GenerateContentConfig(tools=[types.Tool(function_declarations=self.config.tools[:1])],
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

    async def planner_agent(self, report, stream=True):
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
        response = ''
        response_stream = await chat.send_message_stream(
            prompt
        )
        async for chunk in response_stream:
            if chunk.text:
                response += chunk.text
                escaped = chunk.text.replace('\n', ' ')
                if(stream):
                    print(f'PLAN_CHUNK:{escaped}', flush=True)
        plan_data = json.loads(response)
        return plan_data
    
    @retry(stop=stop_after_attempt(3), retry=retry_if_exception_type(FileNotFoundError), after=log_retry)
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
        chat = self.gemini_client.aio.chats.create(model=self.config.model, config=gemini_config)
        response = await chat.send_message(
            prompt
        )
        path = json.loads(response.candidates[0].content.parts[0].text)
        if path["path"] == "/":
            src = '.'
        else:
            src = path["path"]

        if not os.path.exists(src):
            raise FileNotFoundError(f"Path does not exist: {src}")

        return src
    
    async def symbol_file_agent(self, symbol):
        results = subprocess.run(f"rg -i '{symbol}'", shell=True, capture_output=True, text=True).stdout
        token_count = await check_token_count(results)
        if not token_count:
            results = subprocess.run(f"rg -i '{symbol}' --files-with-matches", shell=True, capture_output=True, text=True).stdout
        with open(f"{self.config.root_directory}/prompts/symbol_file_agent.md") as f:
            prompt_raw = f.read()
        prompt = prompt_raw.replace("{{symbol}}", symbol).replace('{{repository}}', self.config.slug).replace("{{grep_results}}", results)
        response = await self.openai_client.responses.parse(
            model=self.config.sub_model,
            input=prompt,
            text_format=PathResponse
        )
        path = response.output_parsed.path
        return {symbol: path}

    async def symbol_web_agent(self, symbol):
        with open(f"{self.config.root_directory}/prompts/symbol_web_agent.md") as f:
            prompt_raw = f.read()
        prompt = prompt_raw.replace("{{symbol}}", symbol).replace('{{repository}}', self.config.slug)
        response = await self.openai_client.responses.create(
            model=self.config.sub_model,
            input=prompt,
            tools=[
                {
                    "type": "web_search"
                }
            ]
        )
        text = response.output_text
        return {symbol: text}
    
    async def symbol_semantic_agent(self, symbol, concept=None, title=None):
        schema = {
  "type": "object",
  "properties": {
    "items": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "term": {
            "type": "string"
          }
        },
        "required": ["term"]
      }
    }
  },
  "required": ["items"]
}
        with open(f"{self.config.root_directory}/prompts/symbol_semantic_agent.md") as f:
            prompt_raw = f.read()
        prompt = prompt_raw.replace("{{slug}}", self.config.slug).replace("{{symbol}}", symbol)
        # .replace("{{concept}}", concept).replace("{{title}}", title)
        gemini_config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema
        )
        chat = self.gemini_client.aio.chats.create(model='gemini-2.5-flash-lite', config=gemini_config)
        response = await chat.send_message(
            prompt
        )
        items = json.loads(response.candidates[0].content.parts[0].text)
        results = []
        for item in items["items"]:
            for k, v in item.items():
                result = subprocess.run(f"rg -i '{v}'", shell=True, capture_output=True, text=True).stdout
                results.append(result)
        path = await self.symbol_file_agent(str(results))
        return path
    
    async def page_generator_agent(self, section, prompt_raw):
        prompt = prompt_raw.replace('{{slug}}', self.config.slug).replace('{{title}}', section["title"]).replace('{{concept}}', section["concept"]).replace('{{api_items}}', str(section["api_items"]))
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
        gemini_config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(
                include_thoughts=False,
                thinking_level=self.config.thinking_level
            ),
            response_mime_type="application/json",
            response_schema=schema
        )
        chat = self.gemini_client.aio.chats.create(model=self.config.model, config=gemini_config)
        response = ''
        response_stream = await chat.send_message_stream(
            prompt
        )
        async for chunk in response_stream:
            if chunk.text:
                response += chunk.text
                escaped = chunk.text.replace('\n', ' ')
                print(f'RESPONSEID_{chunk.response_id}:{escaped}', flush=True)
        page = json.loads(response) 
        return page
    
    async def validate_plan(self, plan):
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
                "additionalProperties": False
            }
        }
    },
    "required": ["plan"],
    "additionalProperties": False
}
        prompt = f"""
        You will be given a repository plan for {self.config.slug}:{plan}
        Your job is to double check it to see if it misses anything and got anything wrong and if so fix it.  Don't use dot notations/dot chaining, if thats the case use the most determinant part.
    """
        stream = await self.claude_client.beta.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
            extra_headers={
                "anthropic-beta": "structured-outputs-2025-11-13"
            },
            output_format={
                "type": "json_schema",
                "schema": schema
            },
            stream=True
        )
        full_text = ""
        async for event in stream:
            if event.type == "content_block_delta":
                if event.delta.type == "text_delta":
                    full_text += event.delta.text
                    escaped = event.delta.text.replace('\n', ' ')
                    print(f'PLAN_CHUNK:{escaped}', flush=True)
        result = json.loads(full_text)
        return result