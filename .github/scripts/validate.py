import os
import sys
import json
from typing import List, Dict

if __name__ == "__main__":
    success: bool = True
    current_dir: str = os.getcwd()
    localizations_dir = os.path.join(current_dir, "localizations")
    # Check whether all localizations contain en-US equivalent key/value entries.
    # Get available keys in en-US.
    keys: List[str] = []
    with open(os.path.join(localizations_dir, "en_US.json"), "r", encoding="utf_8") as file:
        keys.extend(json.loads(file.read()).keys())
    # Check if any localization has some key missing.
    for file in os.listdir(localizations_dir):
        if file.endswith(".json"):
            with open(os.path.join(localizations_dir, file), "r", encoding="utf_8") as file:
                contents: Dict[str, str] = json.loads(file.read())
                for key in keys:
                    if key not in contents:
                        print(f"{file.name}: {key} not found.")
                        success = False
    localizations: List[Dict[str, str]] = []
    # Check whether all entries in index.json are valid i.e. equivalent localization file exists.
    with open(os.path.join(current_dir, "index.json"), "r", encoding="utf_8") as file:
        localizations = json.loads(file.read())
        for l in localizations:
            if not os.path.isfile(os.path.join(localizations_dir, f"{l['code']}.json")):
                print(f"{l['code']}.json not found.")
                success = False
    localization_codes = list(map(lambda l: l["code"], localizations))
    # Check whether all localization files i.e. ll-RR.json have an entry in index.json.
    for file in os.listdir(localizations_dir):
        if file.endswith(".json"):
            if file.split(".")[0] not in localization_codes:
                print(f"{file} not found in index.json.")
                success = False
    # Exit code.
    if not success:
        sys.exit(1)
