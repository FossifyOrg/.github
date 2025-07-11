#!/bin/bash
set -euo pipefail

NEW_VERSION="$1"
VERSION_CODE="$2"
GITHUB_REPOSITORY="$3"

if [[ -z "$NEW_VERSION" || -z "$VERSION_CODE" || -z "$GITHUB_REPOSITORY" ]]; then
    echo "Error: Missing required arguments"
    echo "Usage: $0 <new_version> <version_code> <repository_name>"
    echo "Example: $0 1.2.3 42 FossifyOrg/Gallery"
    exit 1
fi

echo "Updating version to $NEW_VERSION (code: $VERSION_CODE) for $GITHUB_REPOSITORY"

# check if there are actual changes in the Unreleased section
echo "Checking for changes in Unreleased section..."
if [[ ! -f "CHANGELOG.md" ]]; then
    echo "Error: CHANGELOG.md not found"
    exit 1
fi

# extract content between [Unreleased] and the next version section
unreleased_content=$(sed -n '/^## \[Unreleased\]/,/^## \[/p' CHANGELOG.md | head -n -1 | tail -n +2)

# remove empty lines and spaces
filtered_content=$(echo "$unreleased_content" | sed '/^$/d' | sed '/^[[:space:]]*$/d')

if [[ -z "$filtered_content" ]]; then
    echo "No changes found in [Unreleased] section of CHANGELOG.md"
    echo "Cannot create a release without changelog entries."
    echo "Please add your changes to the [Unreleased] section first."
    exit 1
fi

echo "Found changes in [Unreleased] section, proceeding with release..."

echo "Updating gradle.properties..."
previous_version=$(grep '^VERSION_NAME=' gradle.properties | cut -d= -f2)

if [[ -z "$previous_version" ]]; then
    echo "Error: VERSION_NAME not found in gradle.properties"
    exit 1
fi

if [[ "$previous_version" == "$NEW_VERSION" ]]; then
    echo "Error: New version $NEW_VERSION is the same as the current version $previous_version"
    exit 1
fi

sed -i "s/^VERSION_NAME=.*/VERSION_NAME=$NEW_VERSION/" gradle.properties
sed -i "s/^VERSION_CODE=.*/VERSION_CODE=$VERSION_CODE/" gradle.properties

echo "Updating CHANGELOG.md..."
today=$(date +'%Y-%m-%d')

# add new version section after [Unreleased]
sed -i "s/## \\[Unreleased\\]/## [Unreleased]\\n\\n## [$NEW_VERSION] - $today/" CHANGELOG.md

# update [Unreleased] link to compare from new version to HEAD
sed -i "s|\\[Unreleased\\]:.*|[Unreleased]: https://github.com/$GITHUB_REPOSITORY/compare/$NEW_VERSION...HEAD|" CHANGELOG.md

if [[ "$NEW_VERSION" == "1.0.0" ]]; then
    # first major release so we link to the release tag
    sed -i "/\\[Unreleased\\]:/a\\[$NEW_VERSION\\]: https://github.com/$GITHUB_REPOSITORY/releases/tag/$NEW_VERSION" CHANGELOG.md
else
    # add new version as a compare link
    sed -i "/\\[Unreleased\\]:/a\\[$NEW_VERSION\\]: https://github.com/$GITHUB_REPOSITORY/compare/$previous_version...$NEW_VERSION" CHANGELOG.md
fi

# update release-marker file for triggering the release workflow
echo "Creating release marker..."
mkdir -p .fossify
cat >.fossify/release-marker.txt <<EOF
# Auto-generated file. DO NOT EDIT.
$NEW_VERSION
EOF

echo "Version update completed successfully!"
echo "- gradle.properties: VERSION_NAME=$NEW_VERSION, VERSION_CODE=$VERSION_CODE"
echo "- CHANGELOG.md: Added section for $NEW_VERSION ($today)"
echo "- Release marker: .fossify/release-marker.txt"
echo "Release preparation complete!"
