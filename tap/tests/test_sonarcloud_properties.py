"""`.sonarcloud.properties` may only contain properties Automatic Analysis reads.

SonarCloud has two analysis modes reading two different files, and TAP uses
Automatic Analysis, which honours a FIXED and fairly short property list. Anything
else in the file is accepted silently and does nothing.

That is a nasty failure because it is indistinguishable from success: an earlier
revision of this file carried five `sonar.issue.ignore.multicriteria` entries,
complete with reasoning, that never suppressed anything. The dashboard looked
untouched, which is exactly what it looks like when a suppression has not been
written yet.

Suppressions therefore live in the SonarCloud UI (Analysis Scope -> Ignore Issues
on Multiple Criteria) and their REASONING lives in the file as comments. This test
keeps the two from being confused again.
"""

from pathlib import Path

import pytest

PROPERTIES = Path(__file__).resolve().parents[2] / ".sonarcloud.properties"

# Verified against Sonar's Automatic Analysis documentation, 2026-08-31.
AUTOMATIC_ANALYSIS_PROPERTIES = frozenset(
    {
        "sonar.sources",
        "sonar.exclusions",
        "sonar.inclusions",
        "sonar.tests",
        "sonar.test.exclusions",
        "sonar.test.inclusions",
        "sonar.sourceEncoding",
        "sonar.cpd.exclusions",
        "sonar.python.version",
        "sonar.cfamily.reportingCppStandardOverride",
    }
)


def _declared_keys() -> list[str]:
    """Every property actually set in the file (comments are not settings)."""
    keys = []
    for raw in PROPERTIES.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.append(line.split("=", 1)[0].strip())
    return keys


def test_the_file_exists_and_is_named_correctly():
    """Automatic Analysis reads `.sonarcloud.properties`; `sonar-project.properties`
    is the CI-mode name and would be inert here."""
    assert PROPERTIES.is_file()
    assert not (PROPERTIES.parent / "sonar-project.properties").exists()


def test_every_declared_property_is_one_automatic_analysis_reads():
    declared = _declared_keys()
    assert declared, "no properties parsed — this test would pass vacuously"
    unsupported = sorted(set(declared) - AUTOMATIC_ANALYSIS_PROPERTIES)
    assert unsupported == [], (
        f"{unsupported} is not read by Automatic Analysis and will do nothing. "
        "Per-rule suppressions belong in the SonarCloud UI (Analysis Scope -> Ignore "
        "Issues on Multiple Criteria); record the reasoning in the file as a comment."
    )


@pytest.mark.parametrize("key", ["sonar.cpd.exclusions", "sonar.exclusions"])
def test_the_dispositions_we_rely_on_are_actually_set(key):
    """Positive control: the two live settings must be present, not merely explained.

    Without this, deleting them would leave a file full of correct-looking prose and
    no configuration, and every assertion above would still pass."""
    assert key in _declared_keys()


def test_issue_ignore_entries_are_not_reintroduced_as_live_settings():
    """The specific mistake this file already made once."""
    assert not any(k.startswith("sonar.issue.ignore") for k in _declared_keys())
