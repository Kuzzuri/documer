import subprocess
from pathlib import Path

def check_api_percentage(api_items):
    percentages = []
    for item in api_items:
        result = subprocess.run(f"rg -i '{item}'", shell=True, text=True, capture_output=True).stdout
        if len(result) > 0:
            percentages.append(1)
        else:
            percentages.append(0)
    found = percentages.count(1)
    percentage = 100 * float(found)/float(len(percentages))
    if percentage > 70:
        return True
    else:
        return False
    
def check_api_path(api_items):
    unfound = []
    for k,v in api_items.values():
        if not Path(v).exists():
            unfound.append(k)
    return unfound

def log_retry(retry_state):
    print(f"Retrying due to: {retry_state.outcome.exception()}")

def analyze_repo_language(lang):
    languages = {
    "py": "python",
    "pyc": "python",
    "js": "javascript",
    "jsx": "javascript",
    "ts": "typescript",
    "tsx": "typescript",
    "java": "java",
    "c": "c",
    "cpp": "c++",
    "cc": "c++",
    "cxx": "c++",
    "h": "c",
    "hpp": "c++",
    "cs": "csharp",
    "go": "go",
    "rs": "rust",
    "rb": "ruby",
    "php": "php",
    "swift": "swift",
    "kt": "kotlin",
    "kts": "kotlin",
    "scala": "scala",
    "r": "r",
    "m": "objective-c",
    "mm": "objective-c",
    "sh": "shell",
    "bash": "shell",
    "pl": "perl",
    "lua": "lua",
    "dart": "dart",
    "ex": "elixir",
    "exs": "elixir",
    "erl": "erlang",
    "hs": "haskell",
    "sql": "sql",
    "xml": "xml",
    "html": "html",
    "css": "css",
    "scss": "css",
    "sass": "css",
    "json": "json",
    "yaml": "yaml",
    "yml": "yaml",
    "md": "markdown",
    "toml": "toml"
}
    return languages.get(lang, None)