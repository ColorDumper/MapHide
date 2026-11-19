from tools.changelog_links import added_lines, bullets, find_commit, without_link

CHANGELOG = """# Changelog

## Unreleased

### Added

- Added a thing. ([a1b2c3d](https://github.com/ColorDumper/MapHide/commit/a1b2c3d4))
- Added another thing.

## [v0.3.0](https://github.com/ColorDumper/MapHide/compare/v0.2.6...v0.3.0) - 2026-11-13

- Fixed an old thing.
"""


def test_only_the_unreleased_lines_are_read():
    assert [without_link(line) for line in bullets(CHANGELOG)] == [
        "- Added a thing.",
        "- Added another thing.",
    ]


def test_a_link_already_there_is_recognised_and_left_out():
    assert without_link(bullets(CHANGELOG)[0]) == "- Added a thing."


def test_only_added_bullet_lines_come_from_a_diff():
    diff = "@@ -1 +1 @@\n-- Fixed an old thing.\n+- Fixed a new thing.\n+### Fixed\n"
    assert added_lines(diff) == ["- Fixed a new thing."]


def test_the_first_commit_that_added_the_line_with_its_change_wins():
    commits = [("old", ["- Added X."], True), ("new", ["- Added X."], True)]
    assert find_commit("- Added X.", commits) == ("old", True)


def test_a_line_reworded_later_still_points_at_its_change():
    commits = [
        ("fix", ["- Fixed the overlay staying on after a crash."], True),
        ("reword", ["- Fixed the overlay staying on after MapHide crashed."], False),
    ]
    line = "- Fixed the overlay staying on after MapHide crashed."
    assert find_commit(line, commits) == ("fix", False)


def test_a_line_only_ever_added_to_the_changelog_is_not_sure():
    commits = [("notes", ["- Added a note."], False)]
    assert find_commit("- Added a note.", commits) == ("notes", False)


def test_a_line_no_commit_added_finds_nothing():
    commits = [("abc", ["- Added something unrelated."], True)]
    assert find_commit("- Fixed the tray icon.", commits) == (None, False)
