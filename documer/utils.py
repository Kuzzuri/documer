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