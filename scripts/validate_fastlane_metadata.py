"""This script validates Fastlane metadata length limits."""

from pathlib import Path

METADATA_DIR = Path("fastlane/metadata/android")
EN_US_LANG_CODE = "en-US"

FILE_LENGTH_LIMITS = {
    "title.txt": 30,
    "short_description.txt": 80,
    "full_description.txt": 4000
}

CHANGELOG_LENGTH_LIMIT = 500


def check_file_length(file_path, limit):
    if not file_path.is_file():
        return True

    if file_path.stat().st_size == 0:
        print(f"::error::File {file_path} is empty!")
        return False

    try:
        content = file_path.read_text(encoding='utf-8').strip()
        if len(content) > limit:
            print(
                f"::error::File {file_path} is too long ({len(content)} chars, max {limit})!")
            return False
        return True

    except UnicodeDecodeError:
        print(f"::error::File {file_path} contains invalid UTF-8 encoding!")
        return False


def check_changelogs(lang_dir):
    changelogs_dir = lang_dir / "changelogs"

    if not changelogs_dir.exists():
        return True

    all_valid = True
    for changelog_file in changelogs_dir.glob("*.txt"):
        if changelog_file.stat().st_size == 0:
            print(f"::warning::Changelog file {changelog_file} is empty")
            continue

        try:
            content = changelog_file.read_text(encoding='utf-8').strip()
            if len(content) > CHANGELOG_LENGTH_LIMIT:
                print(
                    f"::error::Changelog {changelog_file} is too long ({len(content)} chars, max {CHANGELOG_LENGTH_LIMIT})!"
                )
                all_valid = False

        except UnicodeDecodeError:
            print(
                f"::error::Changelog file {changelog_file} contains invalid UTF-8 encoding!"
            )
            all_valid = False

    return all_valid


def check_language_directory(lang_dir):
    all_valid = True

    for file_name, limit in FILE_LENGTH_LIMITS.items():
        file_path = lang_dir / file_name
        if not check_file_length(file_path, limit):
            all_valid = False

    if not check_changelogs(lang_dir):
        all_valid = False

    return all_valid


def main():
    if not METADATA_DIR.is_dir():
        print(f"::error::Metadata directory {METADATA_DIR} not found!")
        exit(1)

    en_us_dir = METADATA_DIR / EN_US_LANG_CODE
    if not en_us_dir.is_dir():
        print(f"::error::Required en-US directory {en_us_dir} not found!")
        exit(1)

    print("Starting Fastlane metadata validation...")

    all_valid = True

    for lang_dir in METADATA_DIR.iterdir():
        if lang_dir.is_dir():
            if not check_language_directory(lang_dir):
                all_valid = False

    if all_valid:
        print("All metadata files are valid!")
    else:
        print("::error::Some metadata files have validation errors!")
        exit(1)


if __name__ == "__main__":
    main()
