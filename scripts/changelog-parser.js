/**
 * A wrapper around the keep-a-changelog library to parse CHANGELOG.md files
 */

const fs = require('fs');
const { parser } = require('keep-a-changelog');

const FORMAT_GITHUB = 'github';
const FORMAT_FASTLANE = 'fastlane';

/**
 * Parses a changelog entry and formats it for GitHub
 */
function formatReleaseChangeGithub(change) {
  let title = change.toString('-');
  title = title.replace(/\[#(\d+)\]/g, '#$1'); // replace refs like [#123] with #123
  return title;
}

/**
 * Parses a changelog entry and formats it for Fastlane
 */
function formatReleaseChangeFastlane(change) {
  let title = change.toString('•');
  title = title.replace(/\(\[#\d+\]\)/g, ''); // strip issue references
  return title;
}

/**
 * Parses a changelog file and extracts formatted release notes
 * 
 * @param {string} changelogPath - Path to CHANGELOG.md file
 * @param {string} version - Version tag to extract
 * @param {string} format - Target platform for formatting
 * @param {string|null} maintainer - Maintainer's GitHub username (required if format is FORMAT_GITHUB)
 * @param {string|null} repository - GitHub repository (e.g., "Fossify/Store") (required if format is FORMAT_GITHUB)
 * @returns {string} - Formatted release notes
 */
function extractReleaseNotes(changelogPath, version, format = FORMAT_GITHUB, maintainer = null, repository = null) {
  if (!changelogPath) {
    throw new Error('changelogPath is required.');
  }

  if (!version) {
    throw new Error('App version is required.');
  }

  if (format !== FORMAT_GITHUB && format !== FORMAT_FASTLANE) {
    throw new Error(`Invalid format specified: ${format}. Must be either "${FORMAT_GITHUB}" or "${FORMAT_FASTLANE}".`);
  }

  if (format === FORMAT_GITHUB) {
    if (!repository) {
      throw new Error('GitHub repository (e.g., "Fossify/Store") is required for GitHub format.');
    }
  }

  if (!fs.existsSync(changelogPath)) {
    throw new Error(`Changelog file not found at ${changelogPath}`);
  }

  console.log(`Reading changelog from: ${changelogPath}...`);
  const changelogContent = fs.readFileSync(changelogPath, 'utf8');

  let parsed;
  try {
    parsed = parser(changelogContent);
    console.log(`Parsed ${parsed.releases.length} releases from changelog.`);
  } catch (error) {
    throw new Error(`Failed to parse CHANGELOG.md: ${error.message}`);
  }

  console.log(`Extracting changelog for version: ${version}...`);
  const release = parsed.findRelease(version);

  if (!release) {
    throw new Error(`No changelog entry found for version ${version} in ${changelogPath}. Please update the changelog before creating the release.`);
  }

  let notes = '';
  if (release.changes && release.changes.size > 0) {
    for (const [sectionTitle, changes] of release.changes) {
      if (changes && changes.length > 0) {
        const capitalizedTitle = sectionTitle.charAt(0).toUpperCase() + sectionTitle.slice(1);
        if (format === FORMAT_GITHUB) {
          notes += `### ${capitalizedTitle}\n\n`;
        } else {
          notes += `${capitalizedTitle}:\n\n`;
        }

        const formattedChanges = changes.map(item => {
          if (format === FORMAT_GITHUB) {
            return formatReleaseChangeGithub(item);
          } else {
            return formatReleaseChangeFastlane(item);
          }
        });

        notes += formattedChanges.join('\n') + '\n\n';
      }
    }
  }

  if (!notes) {
    console.log(`Version ${version} found, but no changes listed.`);
    notes = '*No specific changes in this version.*\n\n';
  } else {
    console.log(`Extracted changelog for version ${version}.`);
  }

  if (format === FORMAT_GITHUB) {
    let githubSpecificContent = '';

    const releaseIndex = parsed.releases.findIndex(r => r.version === version);
    const prevRelease = (releaseIndex >= 0 && releaseIndex + 1 < parsed.releases.length) ? parsed.releases[releaseIndex + 1] : null;
    let compareUrl = '';
    if (prevRelease && prevRelease.version) {
      console.log(`Found previous release version: ${prevRelease.version}`);
      compareUrl = `https://github.com/${repository}/compare/${prevRelease.version}...${version}`;
    } else {
      console.log(`No previous release found or this is the first release.`);
      compareUrl = `https://github.com/${repository}/commits/${version}`;
    }

    console.log(`Generated compare URL: ${compareUrl}`);
    githubSpecificContent += `**Full Changelog:** ${compareUrl}`;

    githubSpecificContent += '\n\n';
    if (maintainer) {
      githubSpecificContent += `<sub>_This is an automated release; ping [@${maintainer}](https://github.com/${maintainer}) for urgent issues._</sub>`;
    }

    if (githubSpecificContent.length > 0) {
      notes += githubSpecificContent;
    }
  }

  console.log("Final generated notes:\n", notes);
  return notes;
}

/**
 * Formats release notes for GitHub releases
 * Ensures issue references are properly linked
 * @param {string} changelogPath - Path to CHANGELOG.md file
 * @param {string} version - Version tag to extract
 * @param {string} maintainer - Maintainer's GitHub username
 * @param {string} repository - GitHub repository (e.g., "owner/repo")
 */
function formatForGitHub(changelogPath, version, maintainer, repository) {
  return extractReleaseNotes(changelogPath, version, FORMAT_GITHUB, maintainer, repository);
}

/**
 * Formats release notes for Fastlane (Google Play, F-Droid, etc.)
 * @param {string} changelogPath - Path to CHANGELOG.md file
 * @param {string} version - Version tag to extract
 */
function formatForFastlane(changelogPath, version) {
  return extractReleaseNotes(changelogPath, version, FORMAT_FASTLANE, null, null);
}

module.exports = {
  extractReleaseNotes,
  formatForGitHub,
  formatForFastlane
};