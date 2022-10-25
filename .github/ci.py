import os
import sys
import json
from typing import List, Dict

if __name__ == "__main__":
    success: bool = True
    current_dir: str = os.getcwd()
    # Check whether all languages contain en-US equivalent key/value entries.
    # Get available keys in en-US.
    keys: List[str] = []
    with open(os.path.join(current_dir, "en_US.json"), "r", encoding="utf_8") as file:
        keys.extend(json.loads(file.read()).keys())
    # Check if any language has some key missing.
    for file in os.listdir(current_dir):
        if file.endswith(".json") and "index.json" not in file:
            with open(os.path.join(current_dir, file), "r", encoding="utf_8") as file:
                contents: Dict[str, str] = json.loads(file.read())
                for key in keys:
                    if key not in contents:
                        print(f"{file.name}: {key} not found.")
                        success = False
    # Check whether all entries in index.json are valid i.e. equivalent translation file exists.
    with open(os.path.join(current_dir, "index.json"), "r", encoding="utf_8") as file:
        languages: List[Dict[str, str]] = json.loads(file.read())
        for l in languages:
            if not os.path.isfile(os.path.join(current_dir, f"{l['code']}.json")):
                print(f"{l['code']}.json not found.")
                success = False
    # Exit code.
    if not success:
        sys.exit(1)
