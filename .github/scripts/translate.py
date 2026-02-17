#!/usr/bin/env python3

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Any, Set, Optional, List

BATCH_SIZE = 50
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"
SOURCE_LANGUAGE = 'en_US'
SKIP_LANGUAGES = {'tok'}


def load_json(file_path: Path) -> Dict[str, Any]:
    """Load and parse a JSON file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading {file_path}: {e}")
        raise


def save_json(file_path: Path, data: Dict[str, Any]) -> None:
    """Save data to a JSON file with proper formatting."""
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
    except Exception as e:
        print(f"Error saving {file_path}: {e}")
        raise


def get_changed_keys(en_file: Path) -> Set[str]:
    """Extract changed keys from git diff of the English localization file."""
    print("Getting git diff...")
    
    try:
        result = subprocess.run(
            ['git', 'diff', 'HEAD~1', 'HEAD', '--', str(en_file)],
            capture_output=True,
            text=True,
            check=False,
            cwd=en_file.parent.parent
        )
        
        print(f"Git diff return code: {result.returncode}")
        
        if result.returncode != 0:
            print(f"Git diff error: {result.stderr}")
            sys.exit(1)
        
        if not result.stdout.strip():
            print("No diff found - file unchanged")
            return set()
        
        # Parse diff output to extract changed keys using regex for better accuracy
        changed_keys = set()
        # Match lines like: + "key": "value"
        pattern = re.compile(r'^\+\s*"([^"]+)"\s*:', re.MULTILINE)
        
        for match in pattern.finditer(result.stdout):
            key = match.group(1)
            changed_keys.add(key)
        
        return changed_keys
        
    except subprocess.TimeoutExpired:
        print("Git diff timed out")
        sys.exit(1)
    except Exception as e:
        print(f"Exception in get_changed_keys: {e}")
        sys.exit(1)


def strip_markdown_code_block(content: str) -> str:
    """Remove markdown code block formatting from model response."""
    content = content.strip()
    
    if content.startswith('```'):
        # Remove opening ```json or ```
        lines = content.split('\n')
        if lines[0].strip() in ('```json', '```'):
            lines = lines[1:]
        
        # Remove closing ```
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        
        content = '\n'.join(lines).strip()
    
    return content


def call_groq(prompt: str) -> Optional[str]:
    """Call Groq API with the given prompt via curl and return the response content."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("Error: GROQ_API_KEY environment variable is not set")
        return None
    print(f"[debug] Groq API: model={GROQ_MODEL}, prompt length={len(prompt)} chars")
    try:
        payload = {
            "model": GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 8192,
            "stream": False,
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(payload, f, ensure_ascii=False)
            payload_path = f.name
        try:
            result = subprocess.run(
                [
                    "curl", "-s", "-X", "POST", GROQ_API_URL,
                    "-H", "Authorization: Bearer " + api_key,
                    "-H", "Content-Type: application/json",
                    "-d", "@" + payload_path,
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
            print(f"[debug] curl returncode={result.returncode}, stdout length={len(result.stdout)}, stderr length={len(result.stderr)}")
            if result.returncode != 0:
                print(f"Groq API error: {result.stderr}")
                return None
            out = result.stdout.strip()
            if not out:
                print("[debug] Groq API returned empty body")
                return None
            print(f"[debug] response preview (first 200 chars): {out[:200]!r}")
            data = json.loads(out)
            choice = data.get("choices")
            if not choice:
                print(f"[debug] response has no 'choices'; keys={list(data.keys())}")
                return None
            message = choice[0].get("message", {})
            content = (message.get("content") or "").strip() or None
            print(f"[debug] extracted content length={len(content) if content else 0} chars")
            return content
        finally:
            os.unlink(payload_path)
    except subprocess.TimeoutExpired:
        print("Groq API call timed out")
        return None
    except json.JSONDecodeError as e:
        print(f"Groq API response JSON error: {e}")
        print(f"[debug] response (first 500 chars): {out[:500] if out else '(empty)'}")
        return None
    except Exception as e:
        print(f"Exception calling Groq API: {e}")
        return None


def build_translation_prompt(
    keys_dict: Dict[str, str],
    target_language: str,
    full_en_data: Dict[str, str],
    existing_target_data: Dict[str, str]
) -> str:
    """Build the translation prompt for the model."""
    return f"""You are a professional translator working on localization for Harmonoid, a music player application. Translate the following JSON object from English to {target_language}.

CONTEXT: These strings are UI text for a music player app. They include terms related to music playback, playlists, albums, artists, audio settings, and media library management.

FULL ENGLISH LOCALIZATION (all strings for reference):
{json.dumps(full_en_data, ensure_ascii=False, indent=2)}

EXISTING {target_language.upper()} LOCALIZATION (for consistency reference):
{json.dumps(existing_target_data, ensure_ascii=False, indent=2)}

IMPORTANT RULES:
1. Keep all JSON keys EXACTLY the same (do not translate keys)
2. Only translate the VALUES
3. Preserve any special formatting like quotes (""), placeholders ("M", "N", "X", "ENTRY", "PLAYLIST", etc.)
4. Maintain the same meaning, tone, punctuation, capitalization, structure, pluralization and formatting as the English source
5. Use appropriate music/audio terminology for the target language
6. Maintain CONSISTENCY with the existing translations shown above - use the same style, tone, and terminology choices
7. For technical terms (e.g., "playlist", "equalizer"), check if they were translated or kept in English in existing translations and follow the same pattern
8. Return ONLY the translated JSON object, no additional text or explanations
9. Ensure the output is valid JSON
10. Try to keep similar string length as the original English string (if possible and natural in the target language)

STRINGS TO TRANSLATE:
{json.dumps(keys_dict, ensure_ascii=False, indent=2)}"""


def translate_keys(
    keys_dict: Dict[str, str],
    target_language: str,
    full_en_data: Dict[str, str],
    existing_target_data: Dict[str, str]
) -> Dict[str, str]:
    """Translate a dictionary of keys using Groq API."""
    if not keys_dict:
        return {}
    
    print("Calling Groq API...")
    
    prompt = build_translation_prompt(keys_dict, target_language, full_en_data, existing_target_data)
    response = call_groq(prompt)
    
    if not response:
        print("Empty or failed Groq API response, returning original keys")
        return keys_dict
    
    print("Groq API returned successfully")
    
    # Strip markdown formatting
    content = strip_markdown_code_block(response)
    print(f"[debug] after strip_markdown: content length={len(content)} chars, preview: {content[:150]!r}...")
    
    # Parse JSON response
    try:
        translated = json.loads(content)
        
        # Validate that all keys are present
        if not isinstance(translated, dict):
            print("LLM response is not a dictionary")
            return keys_dict
        
        missing_keys = set(keys_dict.keys()) - set(translated.keys())
        if missing_keys:
            print(f"Warning: Missing keys in translation: {missing_keys}")
            # Fill in missing keys with original values
            for key in missing_keys:
                translated[key] = keys_dict[key]
        
        return translated
        
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        print(f"Content preview: {content[:500] if content else '(empty)'}...")
        return keys_dict


def translate_language(
    lang_code: str,
    lang_name: str,
    keys_to_translate: Dict[str, str],
    en_data: Dict[str, str],
    existing_data: Dict[str, str],
    localizations_dir: Path
) -> bool:
    """Translate all keys for a specific language."""
    if not keys_to_translate:
        print("Up to date")
        return False
    
    print(f"Translating {len(keys_to_translate)} keys...")
    
    # Translate in batches
    translated = {}
    keys = list(keys_to_translate.keys())
    total_batches = (len(keys) + BATCH_SIZE - 1) // BATCH_SIZE
    
    for i in range(0, len(keys), BATCH_SIZE):
        batch_keys = keys[i:i + BATCH_SIZE]
        batch_dict = {k: keys_to_translate[k] for k in batch_keys}
        
        batch_num = i // BATCH_SIZE + 1
        print(f"Batch {batch_num}/{total_batches} ({len(batch_keys)} keys)")
        
        batch_translated = translate_keys(batch_dict, lang_name, en_data, existing_data)
        translated.update(batch_translated)
    
    # Merge translations with existing data and maintain key order from en_US.json
    final_data = {**existing_data, **translated}
    ordered_data = {k: final_data.get(k, en_data[k]) for k in en_data.keys()}
    
    # Save the updated translations
    target_file = localizations_dir / f"{lang_code}.json"
    save_json(target_file, ordered_data)
    print(f"✓ Saved to {target_file.name}")
    
    return True


def main() -> None:
    """Main entry point for the translation script."""
    print("Starting translation script...")
    
    # Setup paths
    script_dir = Path(__file__).parent
    project_root = script_dir.parent.parent
    localizations_dir = project_root / "localizations"
    index_file = project_root / "index.json"
    en_file = localizations_dir / f"{SOURCE_LANGUAGE}.json"
    
    print(f"Paths:")
    print(f"  project_root: {project_root}")
    print(f"  en_file: {en_file}")
    
    # Validate English localization file exists
    if not en_file.exists():
        print(f"Error: {en_file} not found")
        sys.exit(1)
    
    # Load English localization file
    try:
        en_data = load_json(en_file)
        print(f"Loaded {len(en_data)} keys from {SOURCE_LANGUAGE}.json")
    except Exception:
        sys.exit(1)
    
    # Get keys that were changed in the latest commit
    changed_keys = get_changed_keys(en_file)
    
    if not changed_keys:
        print("No changed keys found - nothing to translate")
        sys.exit(0)
    
    print(f"Found {len(changed_keys)} changed keys: {', '.join(sorted(changed_keys))}")
    
    # Load list of available languages from index.json
    if not index_file.exists():
        print(f"Error: {index_file} not found")
        sys.exit(1)
    
    try:
        languages = load_json(index_file)
        print(f"Loaded {len(languages)} languages")
    except Exception:
        sys.exit(1)
    
    # Translate changed keys for each language
    translated_count = 0
    
    for lang_info in languages:
        lang_code = lang_info.get('code')
        lang_name = lang_info.get('name')
        
        if not lang_code or not lang_name:
            print(f"Warning: Invalid language entry: {lang_info}")
            continue
        
        # Skip English since it's the source language
        if lang_code == SOURCE_LANGUAGE:
            continue
        
        # Skip languages that should not be auto-translated
        if lang_code in SKIP_LANGUAGES:
            print(f"\n[{lang_code}] {lang_name} - Skipped (manual translation only)")
            continue
        
        print(f"\n[{lang_code}] {lang_name}")
        
        # Load existing translations for this language
        target_file = localizations_dir / f"{lang_code}.json"
        existing_data = load_json(target_file) if target_file.exists() else {}
        
        # Filter to only keys that need translation
        keys_to_translate = {k: en_data[k] for k in changed_keys if k in en_data}
        
        # Translate the language
        if translate_language(lang_code, lang_name, keys_to_translate, en_data, existing_data, localizations_dir):
            translated_count += 1
    
    print(f"\n✓ Done - translated {translated_count} language(s)")


if __name__ == "__main__":
    main()
