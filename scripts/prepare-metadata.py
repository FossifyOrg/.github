"""
This script prepares the metadata for Google Play.

1. It checks if the source metadata (en-US) is complete.
2. It deletes translations that are incomplete or unsupported by Google Play.
3. It copies the title.txt file from the en-US folder to all supported language folders.
"""

import shutil
from pathlib import Path

METADATA_DIR = Path("fastlane/metadata/android")
EN_US_LANG_CODE = "en-US"
EN_US_TITLE_PATH = METADATA_DIR / EN_US_LANG_CODE / "title.txt"

# Source: https://support.google.com/googleplay/android-developer/answer/9844778
SUPPORTED_LANGUAGES = [
    "af",
    "sq",
    "am",
    "ar",
    "hy-AM",
    "az-AZ",
    "bn-BD",
    "eu-ES",
    "be",
    "bg",
    "my-MM",
    "ca",
    "zh-HK",
    "zh-CN",
    "zh-TW",
    "hr",
    "cs-CZ",
    "da-DK",
    "nl-NL",
    "en-AU",
    "en-CA",
    "en-US",
    "en-GB",
    "en-IN",
    "en-SG",
    "en-ZA",
    "et",
    "fil",
    "fi-FI",
    "fr-CA",
    "fr-FR",
    "gl-ES",
    "ka-GE",
    "de-DE",
    "el-GR",
    "gu",
    "iw-IL",
    "hi-IN",
    "hu-HU",
    "is-IS",
    "id",
    "it-IT",
    "ja-JP",
    "kn-IN",
    "kk",
    "km-KH",
    "ko-KR",
    "ky-KG",
    "lo-LA",
    "lv",
    "lt",
    "mk-MK",
    "ms-MY",
    "ms",
    "ml-IN",
    "mr-IN",
    "mn-MN",
    "ne-NP",
    "no-NO",
    "fa",
    "fa-AE",
    "fa-AF",
    "fa-IR",
    "pl-PL",
    "pt-BR",
    "pt-PT",
    "pa",
    "ro",
    "rm",
    "ru-RU",
    "sr",
    "si-LK",
    "sk",
    "sl",
    "es-419",
    "es-ES",
    "es-US",
    "sw",
    "sv-SE",
    "ta-IN",
    "te-IN",
    "th",
    "tr-TR",
    "uk",
    "ur",
    "vi",
    "zu"
]


def check_source_completeness():
    if not EN_US_TITLE_PATH.is_file() or EN_US_TITLE_PATH.stat().st_size == 0:
        print(
            f"::error::Source metadata (en-US) title file {EN_US_TITLE_PATH} is missing or empty!"
        )
        exit(1)

    short_desc_path = METADATA_DIR / EN_US_LANG_CODE / "short_description.txt"
    full_desc_path = METADATA_DIR / EN_US_LANG_CODE / "full_description.txt"

    if not (
        short_desc_path.is_file() and short_desc_path.stat().st_size > 0 and
            full_desc_path.is_file() and full_desc_path.stat().st_size > 0
    ):
        print(
            f"::error::Source metadata (en-US) (short or full description) is incomplete. Please ensure {short_desc_path} and {full_desc_path} exist and are not empty."
        )
        exit(1)

    print("Source metadata (en-US) is complete.")


def main():
    check_source_completeness()

    if not METADATA_DIR.is_dir():
        print(
            f"::error::Metadata directory {METADATA_DIR} not found. How could you let that happen?"
        )
        exit(1)

    for lang_dir in METADATA_DIR.iterdir():
        if not lang_dir.is_dir():
            continue

        lang_code = lang_dir.name
        # Not ideal but this is required as there could be translations for languages not supported by Google Play
        if not lang_code in SUPPORTED_LANGUAGES:
            print(
                f"::warning::Language code '{lang_code}' (folder {lang_dir}) is not in the supported list. Deleting folder..."
            )
            shutil.rmtree(lang_dir)
            continue

        print(f"Processing supported language: {lang_code}")
        target_title_path = lang_dir / "title.txt"
        short_desc_path = lang_dir / "short_description.txt"
        full_desc_path = lang_dir / "full_description.txt"

        # This copying is only required because the title.txt is never translated (filtered out on Weblate) but Google Play requires it for all languages
        # See: https://github.com/orgs/FossifyOrg/discussions/23#discussioncomment-7769471
        if lang_code != EN_US_LANG_CODE:
            if not target_title_path.is_file() or target_title_path.stat().st_size == 0:
                print(f"Copying en-US title to {lang_code}")
                shutil.copy2(EN_US_TITLE_PATH, target_title_path)
            else:
                print(f"Title already exists for {lang_code}")

        # Some languages have incomplete translation (e.g. missing short or full description)
        if not (
            short_desc_path.is_file() and short_desc_path.stat().st_size > 0 and
                full_desc_path.is_file() and full_desc_path.stat().st_size > 0
        ):
            print(
                f"::warning::Supported language {lang_code} is incomplete (missing short or full description). Deleting folder {lang_dir}"
            )
            shutil.rmtree(lang_dir)
        else:
            print(f"Language {lang_code} is complete and ready.")

    print("Metadata preparation complete.")


if __name__ == "__main__":
    main()
