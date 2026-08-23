"""Out-of-band detection gate — the LIVE authoring-time half (req-cicd-sbom-12).

The reconciliation runs here as a unit test so an undeclared `COPY --from` site
reds the promote lane, not the publish: both real Dockerfiles must account for
every site against their real supplemental manifests, and the parser semantics
(annotation binding, dir-destination computation) are pinned by synthetic cases.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("sbom_oob_detect", _REPO_ROOT / "scripts" / "sbom" / "oob_detect.py")
assert _spec is not None and _spec.loader is not None
oob = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oob)

_SUPPLEMENTAL = {"components": [{"name": "thing", "path": "/usr/lib/thing.so"}]}


def _check(tmp_path: Path, dockerfile_text: str) -> list[str]:
    df = tmp_path / "Dockerfile"
    df.write_text(dockerfile_text, encoding="utf-8")
    problems = oob.check_dockerfile_sites(df, _SUPPLEMENTAL)
    assert isinstance(problems, list)
    return problems


@pytest.mark.spec("req-cicd-sbom-12-1")
def test_real_dockerfiles_reconcile_against_real_manifests() -> None:
    """The live gate: every COPY --from site in BOTH shipped Dockerfiles is
    declared in its supplemental manifest or explicitly sbom-allow annotated."""
    for dockerfile, supplemental in [
        (_REPO_ROOT / "Dockerfile", _REPO_ROOT / "docker" / "sbom-supplemental.json"),
        (
            _REPO_ROOT / "docker" / "postgres" / "Dockerfile",
            _REPO_ROOT / "docker" / "postgres" / "sbom-supplemental.json",
        ),
    ]:
        problems = oob.check_dockerfile_sites(dockerfile, oob._gen.load_supplemental(supplemental))
        assert problems == [], f"{dockerfile}: {problems}"


@pytest.mark.spec("req-cicd-sbom-12-1")
def test_undeclared_copy_from_is_a_red(tmp_path: Path) -> None:
    problems = _check(tmp_path, "FROM x AS a\nCOPY --from=builder /built/mystery.bin /usr/bin/mystery\n")
    assert len(problems) == 1 and "/usr/bin/mystery" in problems[0]


@pytest.mark.spec("req-cicd-sbom-12-1")
def test_declared_copy_from_passes(tmp_path: Path) -> None:
    assert _check(tmp_path, "COPY --from=builder /built/thing.so /usr/lib/thing.so\n") == []


@pytest.mark.spec("req-cicd-sbom-12-2")
def test_annotation_allows_the_next_instruction_only(tmp_path: Path) -> None:
    """One blessed exception must never silently bless the site after it."""
    text = (
        "# sbom-allow(req-cicd-sbom-2): infra bytes, deliberately excluded\n"
        "COPY --from=warm /cache /opt/cache\n"
        "COPY --from=warm /other /opt/other\n"
    )
    problems = _check(tmp_path, text)
    assert len(problems) == 1 and "/opt/other" in problems[0]


@pytest.mark.spec("req-cicd-sbom-12-2")
def test_annotation_does_not_float_past_instructions(tmp_path: Path) -> None:
    text = (
        "# sbom-allow(req-cicd-sbom-2): meant for the RUN below, binds to it, covers nothing\n"
        "RUN echo hi\n"
        "COPY --from=warm /cache /opt/cache\n"
    )
    problems = _check(tmp_path, text)
    assert len(problems) == 1 and "/opt/cache" in problems[0]


@pytest.mark.spec("req-cicd-sbom-12-3")
def test_dir_destination_requires_every_computed_path(tmp_path: Path) -> None:
    """/uv declared alone cannot carry /uvx: dir destinations expand per source file."""
    supplemental = {"components": [{"name": "uv", "path": "/bin/uv"}]}
    df = tmp_path / "Dockerfile"
    df.write_text("COPY --from=img /uv /uvx /bin/\n", encoding="utf-8")
    problems = oob.check_dockerfile_sites(df, supplemental)
    assert len(problems) == 1 and "/bin/uvx" in problems[0] and "/bin/uv'" not in problems[0]
