#!/usr/bin/env python3

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, Set


def load_json(file_path: Path) -> Dict[str, Any]:
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(file_path: Path, data: Dict[str, Any]) -> None:
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')


def get_changed_keys(en_file: Path) -> Set[str]:
    print("Getting git diff...", flush=True)
    
    try:
        result = subprocess.run(
            ['git', 'diff', 'HEAD~1', 'HEAD', '--', str(en_file)],
            capture_output=True,
            text=True,
            check=False,
            cwd=en_file.parent.parent
        )
        
        print(f"Git diff return code: {result.returncode}", flush=True)
        
        if result.returncode != 0:
            print(f"Git diff error: {result.stderr}", flush=True)
            sys.exit(1)
        
        if not result.stdout.strip():
            print("No diff found - file unchanged", flush=True)
            return set()
        
        changed_keys = set()
        for line in result.stdout.split('\n'):
            if line.startswith('+') and not line.startswith('+++'):
                content = line[1:].strip()
                if content.startswith('"') and '":' in content:
                    try:
                        key = content.split('"')[1]
                        changed_keys.add(key)
                    except IndexError:
                        continue
        
        return changed_keys
        
    except Exception as e:
        print(f"Exception in get_changed_keys: {e}", flush=True)
        sys.exit(1)


def translate_keys(keys_dict: Dict[str, str], target_language: str) -> Dict[str, str]:
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
{json.dumps(keys_dict, ensure_ascii=False, indent=2)}"""

    print(f"Calling LLM...", flush=True)
    
    try:
        result = subprocess.run(
            ['llm', '-m', 'github/gpt-4o'],
            input=prompt,
            capture_output=True,
            text=True,
            check=False,
            timeout=120
        )
        
        print(f"LLM returned with code {result.returncode}", flush=True)
        
        if result.returncode != 0:
            print(f"Error: {result.stderr}", flush=True)
            return keys_dict
        
        content = result.stdout.strip()
        
        if not content:
            print(f"Empty response from LLM", flush=True)
            return keys_dict
        
        if content.startswith('```'):
            content = content.split('```')[1]
            if content.startswith('json'):
                content = content[4:]
            content = content.split('```')[0].strip()
        
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            print(f"JSON error: {e}", flush=True)
            print(f"Content: {content[:200]}...", flush=True)
            return keys_dict
            
    except subprocess.TimeoutExpired:
        print(f"LLM call timed out after 120 seconds", flush=True)
        return keys_dict
    except Exception as e:
        print(f"Exception calling LLM: {e}", flush=True)
        return keys_dict


def main():
    print("Starting translation script...", flush=True)
    
    script_dir = Path(__file__).parent
    project_root = script_dir.parent.parent
    localizations_dir = project_root / "localizations"
    index_file = project_root / "index.json"
    en_file = localizations_dir / "en_US.json"
    
    print(f"Paths:", flush=True)
    print(f"  project_root: {project_root}", flush=True)
    print(f"  en_file: {en_file}", flush=True)
    
    if not en_file.exists():
        print(f"Error: {en_file} not found", flush=True)
        sys.exit(1)
    
    en_data = load_json(en_file)
    print(f"Loaded {len(en_data)} keys from en_US.json", flush=True)
    
    changed_keys = get_changed_keys(en_file)
    
    if not changed_keys:
        print("No changed keys found - nothing to translate", flush=True)
        sys.exit(0)
    
    print(f"Found {len(changed_keys)} changed keys: {', '.join(sorted(changed_keys))}", flush=True)
    
    if not index_file.exists():
        print(f"Error: {index_file} not found", flush=True)
        sys.exit(1)
    
    languages = load_json(index_file)
    print(f"Loaded {len(languages)} languages", flush=True)
    
    for lang_info in languages:
        lang_code = lang_info['code']
        lang_name = lang_info['name']
        
        if lang_code == 'en_US':
            continue
        
        print(f"\n[{lang_code}] {lang_name}", flush=True)
        
        target_file = localizations_dir / f"{lang_code}.json"
        existing_data = load_json(target_file) if target_file.exists() else {}
        
        keys_to_translate = {k: en_data[k] for k in changed_keys if k in en_data}
        
        if not keys_to_translate:
            print("Up to date", flush=True)
            continue
        
        print(f"Translating {len(keys_to_translate)} keys...", flush=True)
        
        batch_size = 50
        translated = {}
        keys = list(keys_to_translate.keys())
        
        for i in range(0, len(keys), batch_size):
            batch_keys = keys[i:i + batch_size]
            batch_dict = {k: keys_to_translate[k] for k in batch_keys}
            
            batch_num = i // batch_size + 1
            total_batches = (len(keys) + batch_size - 1) // batch_size
            print(f"Batch {batch_num}/{total_batches}", flush=True)
            
            batch_translated = translate_keys(batch_dict, lang_name)
            translated.update(batch_translated)
        
        final_data = {**existing_data, **translated}
        ordered_data = {k: final_data.get(k, en_data[k]) for k in en_data.keys()}
        
        save_json(target_file, ordered_data)
        print(f"✓ Saved", flush=True)
    
    print("\n✓ Done", flush=True)


if __name__ == "__main__":
    main()
