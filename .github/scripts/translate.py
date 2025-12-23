#!/usr/bin/env python3

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any


def load_json(file_path: Path) -> Dict[str, Any]:
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(file_path: Path, data: Dict[str, Any]) -> None:
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')


def translate_batch(batch_dict: Dict[str, str], target_language: str) -> Dict[str, str]:
    prompt = f"""You are a professional translator. Translate the following JSON object from English to {target_language}.

IMPORTANT RULES:
1. Keep all JSON keys EXACTLY the same (do not translate keys)
2. Only translate the VALUES
3. Preserve any special formatting like quotes (\"\"), placeholders (\"M\", \"N\", \"X\", \"ENTRY\", \"PLAYLIST\", etc.)
4. Maintain the same meaning, punctuation, capitalization, structure and formatting
5. Return ONLY the translated JSON object, no additional text
6. Ensure the output is valid JSON
7. Try to keep the same string length as the original string (if possible)

Input JSON:
{json.dumps(batch_dict, ensure_ascii=False, indent=2)}
"""

    result = subprocess.run(
        ['llm', 'prompt', '-m', 'github/gpt-5', prompt],
        capture_output=True,
        text=True,
        check=False
    )
    
    if result.returncode != 0:
        print(f"  Error: {result.stderr}")
        return batch_dict
    
    content = result.stdout.strip()
    
    if content.startswith('```json'):
        content = content.split('```json')[1].split('```')[0].strip()
    elif content.startswith('```'):
        content = content.split('```')[1].split('```')[0].strip()
    
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        print(f"  JSON decode error: {e}")
        return batch_dict


def main():
    script_dir = Path(__file__).parent
    project_root = script_dir.parent.parent
    localizations_dir = project_root / "localizations"
    index_file = project_root / "index.json"
    
    en_file = localizations_dir / "en_US.json"
    if not en_file.exists():
        print(f"Error: {en_file} not found")
        sys.exit(1)
    
    en_data = load_json(en_file)
    print(f"Loaded {len(en_data)} keys from en_US.json")
    
    if not index_file.exists():
        print(f"Error: {index_file} not found")
        sys.exit(1)
    
    languages = load_json(index_file)
    
    for lang_info in languages:
        lang_code = lang_info['code']
        lang_name = lang_info['name']
        
        if lang_code == 'en_US':
            continue
        
        print(f"\n[{lang_code}] {lang_name}")
        
        target_file = localizations_dir / f"{lang_code}.json"
        existing_data = {}
        
        if target_file.exists():
            existing_data = load_json(target_file)
        
        keys_to_translate = {k: v for k, v in en_data.items() 
                           if k not in existing_data or existing_data[k] == v}
        
        if not keys_to_translate:
            print("  Up to date")
            continue
        
        print(f"  Translating {len(keys_to_translate)} keys")
        
        batch_size = 50
        translated = {}
        keys = list(keys_to_translate.keys())
        
        for i in range(0, len(keys), batch_size):
            batch_keys = keys[i:i + batch_size]
            batch_dict = {k: keys_to_translate[k] for k in batch_keys}
            
            print(f"  Batch {i // batch_size + 1}/{(len(keys) + batch_size - 1) // batch_size}")
            
            batch_translated = translate_batch(batch_dict, lang_name)
            translated.update(batch_translated)
        
        final_data = {**existing_data, **translated}
        ordered_data = {k: final_data.get(k, en_data[k]) for k in en_data.keys()}
        
        save_json(target_file, ordered_data)
        print(f"  ✓ Saved")
    
    print("\n✓ Done")


if __name__ == "__main__":
    main()
