import os, subprocess

async def list_directory(path):
    try:
        items = os.listdir(path)
        return items
    except FileNotFoundError:
        return {"error": f"Path does not exist: {path}. Verify the path and try again."}
    except NotADirectoryError:
        return {"error": "This is a file, not a directory. Verify the path and try again."}
    
async def find(pattern):
    results = subprocess.run(f"fd -i '{pattern}'", shell=True, capture_output=True, text=True).stdout
    return results

async def grep(pattern):
    results = subprocess.run(f"rg -i '{pattern}'", shell=True, capture_output=True, text=True).stdout
    return results