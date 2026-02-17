#!/usr/bin/env python3

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

BATCH_SIZE = 50
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"
SOURCE_LANGUAGE = "en_US"
SKIP_LANGUAGES = {"tok"}
API_TIMEOUT_SEC = 300
BATCH_DELAY_SEC = 0.5
RESPONSE_LOG_MAX_CHARS = 200


def load_json(file_path: Path) -> Dict[str, Any]:
    """Load and parse a JSON file."""
    try:
        with open(file_path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading {file_path}: {e}")
        raise


def save_json(file_path: Path, data: Dict[str, Any]) -> None:
    """Save data to a JSON file with proper formatting."""
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except OSError as e:
        print(f"Error saving {file_path}: {e}")
        raise


def get_git_root(start_path: Path) -> Path:
    """Return repository root containing start_path."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
            cwd=start_path,
            timeout=10,
        )
        return Path(r.stdout.strip())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return start_path


def get_changed_keys(en_file: Path, git_cwd: Path) -> Set[str]:
    """Extract changed keys from git diff of the English localization file."""
    print("Getting git diff...")
    root = get_git_root(git_cwd)
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD~1", "HEAD", "--", str(en_file)],
            capture_output=True,
            text=True,
            check=False,
            cwd=root,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"Git diff error: {result.stderr}")
            sys.exit(1)
        if not (result.stdout or "").strip():
            print("No diff found - file unchanged")
            return set()
        pattern = re.compile(r'^\+\s*"([^"]+)"\s*:', re.MULTILINE)
        return {m.group(1) for m in pattern.finditer(result.stdout)}
    except subprocess.TimeoutExpired:
        print("Git diff timed out")
        sys.exit(1)
    except Exception as e:
        print(f"Exception in get_changed_keys: {e}")
        sys.exit(1)


def strip_markdown_code_block(content: str) -> str:
    """Remove markdown code block formatting from model response."""
    content = content.strip()
    if not content.startswith("```"):
        return content
    lines = content.split("\n")
    # Drop first line (``` or ```json)
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _log_response_preview(body: str) -> None:
    """Print first RESPONSE_LOG_MAX_CHARS of the response body."""
    preview = body[:RESPONSE_LOG_MAX_CHARS]
    suffix = "..." if len(body) > RESPONSE_LOG_MAX_CHARS else ""
    print(f"Response (200 chars): {preview}{suffix}")


def _parse_groq_response(body: str) -> Optional[str]:
    """Parse Groq API JSON response and return message content, or None on error."""
    data = json.loads(body)
    if "error" in data:
        err = data["error"]
        msg = err.get("message", err) if isinstance(err, dict) else err
        print(f"Groq API error payload: {msg}")
        return None
    choices = data.get("choices")
    if not choices or not isinstance(choices, list):
        return None
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not message:
        return None
    content = message.get("content")
    if content is None:
        return None
    return str(content).strip() or None


def call_groq(prompt: str) -> Optional[str]:
    """Call Groq API with the given prompt via curl and return the response content."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("Error: GROQ_API_KEY environment variable is not set")
        return None

    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 8192,
        "stream": False,
    }
    payload_path = None
    response_body: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(payload, f, ensure_ascii=False)
            payload_path = f.name

        result = subprocess.run(
            [
                "curl", "-s", "-X", "POST", GROQ_API_URL,
                "-H", "Authorization: Bearer " + api_key,
                "-H", "Content-Type: application/json",
                "-d", "@" + payload_path,
            ],
            capture_output=True,
            text=True,
            timeout=API_TIMEOUT_SEC,
        )

        if result.returncode != 0:
            print(f"Groq API error: {result.stderr or result.stdout or 'unknown'}")
            return None

        response_body = (result.stdout or "").strip()
        if not response_body:
            print("Groq API returned empty body")
            return None

        _log_response_preview(response_body)
        return _parse_groq_response(response_body)

    except subprocess.TimeoutExpired:
        print("Groq API call timed out")
        return None
    except json.JSONDecodeError as e:
        print(f"Groq API response JSON error: {e}")
        if response_body:
            _log_response_preview(response_body)
        return None
    except Exception as e:
        print(f"Exception calling Groq API: {e}")
        return None
    finally:
        if payload_path and os.path.exists(payload_path):
            try:
                os.unlink(payload_path)
            except OSError:
                pass


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
    prompt = build_translation_prompt(keys_dict, target_language, full_en_data, existing_target_data)
    response = call_groq(prompt)
    if not response:
        return keys_dict
    # Strip markdown formatting
    content = strip_markdown_code_block(response)
    
    # Parse JSON response
    try:
        translated = json.loads(content)
        
        # Validate that all keys are present
        if not isinstance(translated, dict):
            return keys_dict
        missing_keys = set(keys_dict.keys()) - set(translated.keys())
        for key in missing_keys:
            translated[key] = keys_dict[key]
        return translated
    except json.JSONDecodeError:
        return keys_dict


def translate_language(
    lang_code: str,
    lang_name: str,
    keys_to_translate: Dict[str, str],
    en_data: Dict[str, str],
    existing_data: Dict[str, str],
    localizations_dir: Path,
    dry_run: bool = False,
) -> bool:
    """Translate all keys for a specific language."""
    if not keys_to_translate:
        print("Up to date")
        return False
    print(f"Translating {lang_name} ({len(keys_to_translate)} keys)...")
    translated: Dict[str, str] = {}
    keys = list(keys_to_translate.keys())
    for i in range(0, len(keys), BATCH_SIZE):
        batch_keys = keys[i : i + BATCH_SIZE]
        batch_dict = {k: keys_to_translate[k] for k in batch_keys}
        batch_translated = translate_keys(batch_dict, lang_name, en_data, existing_data)
        translated.update(batch_translated)
        if BATCH_DELAY_SEC and i + BATCH_SIZE < len(keys):
            time.sleep(BATCH_DELAY_SEC)
    final_data = {**existing_data, **translated}
    ordered_data = {k: final_data.get(k, en_data[k]) for k in en_data}
    target_file = localizations_dir / f"{lang_code}.json"
    if dry_run:
        return True
    save_json(target_file, ordered_data)
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Translate localization keys via Groq API.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write files; only show what would be translated.",
    )
    parser.add_argument(
        "--language",
        "-l",
        metavar="CODE",
        help="Translate only this language code (e.g. de_DE).",
    )
    return parser.parse_args()


def main() -> None:
    """Main entry point for the translation script."""
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent.parent
    localizations_dir = project_root / "localizations"
    index_file = project_root / "index.json"
    en_file = localizations_dir / f"{SOURCE_LANGUAGE}.json"
    if not en_file.exists():
        print(f"Error: {en_file} not found")
        sys.exit(1)
    try:
        en_data = load_json(en_file)
    except Exception:
        sys.exit(1)
    changed_keys = get_changed_keys(en_file, project_root)
    if not changed_keys:
        sys.exit(0)
    print(f"Found {len(changed_keys)} changed keys")
    if not index_file.exists():
        print(f"Error: {index_file} not found")
        sys.exit(1)
    try:
        languages: List[Dict[str, Any]] = load_json(index_file)
    except Exception:
        sys.exit(1)
    if args.language:
        languages = [x for x in languages if x.get("code") == args.language]
        if not languages:
            print(f"Error: No language with code {args.language!r} in index.json")
            sys.exit(1)
    translated_count = 0
    for lang_info in languages:
        lang_code = lang_info.get("code")
        lang_name = lang_info.get("name")
        if not lang_code or not lang_name:
            continue
        if lang_code == SOURCE_LANGUAGE:
            continue
        if lang_code in SKIP_LANGUAGES:
            continue
        target_file = localizations_dir / f"{lang_code}.json"
        existing_data = load_json(target_file) if target_file.exists() else {}
        keys_to_translate = {k: en_data[k] for k in changed_keys if k in en_data}
        if translate_language(
            lang_code, lang_name, keys_to_translate, en_data, existing_data,
            localizations_dir, dry_run=args.dry_run,
        ):
            translated_count += 1
    print(f"\n✓ Done - translated {translated_count} language(s)")


if __name__ == "__main__":
    main()
