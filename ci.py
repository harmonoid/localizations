import os
import sys
import json
from typing import List, Dict

if __name__ == "__main__":
    success: bool = True
    current_dir: str = os.getcwd()
    translations_dir = os.path.join(current_dir, "translations")
    # Check whether all languages contain en-US equivalent key/value entries.
    # Get available keys in en-US.
    keys: List[str] = []
    with open(
        os.path.join(translations_dir, "en_US.json"), "r", encoding="utf_8"
    ) as file:
        keys.extend(json.loads(file.read()).keys())
    # Check if any language has some key missing.
    for file in os.listdir(translations_dir):
        if file.endswith(".json"):
            with open(
                os.path.join(translations_dir, file), "r", encoding="utf_8"
            ) as file:
                contents: Dict[str, str] = json.loads(file.read())
                for key in keys:
                    if key not in contents:
                        print(f"{file.name}: {key} not found.")
                        success = False
    language_codes: List[str] = []
    # Check whether all entries in index.json are valid i.e. equivalent translation file exists.
    with open(os.path.join(current_dir, "index.json"), "r", encoding="utf_8") as file:
        languages = json.loads(file.read())
        for k, _ in languages.items():
            if not os.path.isfile(os.path.join(translations_dir, f"{k}.json")):
                print(f"{k}.json not found.")
                success = False
        language_codes = list(languages.keys())
    # Check whether all translation files i.e. ll-RR.json have an entry in index.json.
    for file in os.listdir(translations_dir):
        if file.endswith(".json"):
            if file.split(".")[0] not in language_codes:
                print(f"{file} not found in index.json.")
                success = False
    # Exit code.
    if not success:
        sys.exit(1)
