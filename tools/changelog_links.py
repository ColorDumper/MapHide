"""Add a commit link to each line of a changelog version, at release time.

    python tools/changelog_links.py v0.3.0          # the Unreleased section
    python tools/changelog_links.py v0.3.0 --since v0.2.6

Finds, for every line under `## Unreleased` that has no link yet, the first
commit since the last tag that added that line to CHANGELOG.md, and prints
the section with the links filled in. Then it lists every line to check by
hand: a line it couldn't find, one that was reworded after it was added, or
one whose commit changed nothing but the changelog. Nothing is written;
paste the section into CHANGELOG.md once it looks right.
"""

import argparse
import difflib
import re
import subprocess

REPO_URL = "https://github.com/ColorDumper/MapHide"
CHANGELOG = "CHANGELOG.md"
LINK = re.compile(r"\s*\((\[[0-9a-f]{7}\]\([^)]*\)(, )?)+\)$")
# How alike a reworded line must be to the one a commit added.
SIMILAR = 0.6


def git(*args):
    # Only ever git, with arguments this script builds.
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout


def bullets(text, heading="## Unreleased"):
    """The bullet lines under `heading`, up to the next version heading."""
    lines, inside = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line.startswith(heading)
        elif inside and line.startswith("- "):
            lines.append(line)
    return lines


def without_link(line):
    return LINK.sub("", line).strip()


def added_lines(diff):
    """The bullet lines a `git show -U0` diff of the changelog adds."""
    return [without_link(line[1:]) for line in diff.splitlines() if line.startswith("+- ")]


def find_commit(line, commits):
    """(sha, sure) for the commit that made the change `line` describes.

    `commits` are oldest first, each (sha, added lines, changed more than the
    changelog). The first commit that added `line` and changed something else
    too is sure. Failing that, the commit whose added line is most like it
    (the line was reworded later), then one that only added it to the
    changelog; neither is sure. (None, False) when nothing comes close."""
    for sha, added, has_change in commits:
        if has_change and line in added:
            return sha, True
    best, best_score = None, SIMILAR
    for sha, added, has_change in commits:
        for candidate in added if has_change else ():
            score = difflib.SequenceMatcher(None, line, candidate).ratio()
            if score > best_score:
                best, best_score = sha, score
    if best is not None:
        return best, False
    return next((sha for sha, added, _ in commits if line in added), None), False


def link(sha):
    return f"[{sha[:7]}]({REPO_URL}/commit/{sha})"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="the version being released, such as v0.3.0")
    parser.add_argument("--since", help="the previous tag (default: the latest tag)")
    args = parser.parse_args()
    since = args.since or git("describe", "--tags", "--abbrev=0").strip()

    shas = git("rev-list", "--reverse", "--no-merges", f"{since}..HEAD", "--", CHANGELOG).split()
    commits = [
        (
            sha,
            added_lines(git("show", "--format=", "-U0", sha, "--", CHANGELOG)),
            git("show", "--format=", "--name-only", sha).split() != [CHANGELOG],
        )
        for sha in shas
    ]

    to_check = []
    with open(CHANGELOG, encoding="utf-8") as file:
        lines = bullets(file.read())
    for line in lines:
        if LINK.search(line):
            print(line)
            continue
        text = without_link(line)
        sha, sure = find_commit(text, commits)
        if sha is None:
            print(text)
            to_check.append(f"no commit found: {text}")
            continue
        print(f"{text} ({link(sha)})")
        if not sure:
            to_check.append(f"check {sha[:7]} is the change: {text}")

    heading = f"## [{args.version}]({REPO_URL}/compare/{since}...{args.version}) - YYYY-MM-DD"
    print(f"\nHeading: {heading}")
    for item in to_check:
        print(f"CHECK  {item}")


if __name__ == "__main__":
    main()
