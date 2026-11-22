"""The product image: built from a pinned base, described by its manifest, installing nothing at start.

Spec: `specs/spec-tap-baked-instance.md` (`req-tap-bake-product-image`, `req-tap-bake-immutable-env`,
`req-tap-bake-lifecycle-2`). The build itself needs a network and a tap-web image, so it is
proven by the product-image workflow's run; these tests pin the decisions it rests on.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.metadata
import json
import re
from pathlib import Path
from typing import Any

import pytest

from tap import preboot, product_image

ROOT = Path(__file__).resolve().parents[2]
DIGEST = "sha256:" + "a" * 64
URL = "https://forge.example/org/widget-tap"
COMMIT = "3356301e676094523943f2bbb055be501a6b42d6"
OTHER = "7f08d0780d7468590507df2a5562fe730d76e8c8"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def _fake_dist(site: Path, name: str = "widget_tap", version: str = "1.0.0") -> importlib.metadata.Distribution:
    """A minimal installed distribution: one module and a RECORD that hashes it."""
    pkg = site / "widget"
    pkg.mkdir(parents=True)
    module = b"VALUE = 1\n"
    (pkg / "__init__.py").write_bytes(module)
    info = site / f"{name}-{version}.dist-info"
    info.mkdir()
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n".encode()
    (info / "METADATA").write_bytes(metadata)
    (info / "RECORD").write_text(
        f"widget/__init__.py,sha256={_b64(module)},{len(module)}\n"
        f"{info.name}/METADATA,sha256={_b64(metadata)},{len(metadata)}\n"
        f"{info.name}/RECORD,,\n"
    )
    return importlib.metadata.PathDistribution(info)


def _manifest(dist: importlib.metadata.Distribution, commit: str = COMMIT) -> dict[str, Any]:
    entry = product_image.distribution_entry(dist) | {"origin": "plugin", "slug": "widget", "commit": commit}
    return {"schema": product_image.MANIFEST_SCHEMA, "record": {}, "distributions": [entry]}


def _record_entry(commit: str = COMMIT) -> dict[str, Any]:
    return {"slug": "widget", "enabled": True, "source": {"type": "git", "url": URL, "rev": "v1.0.0", "commit": commit}}


@pytest.mark.spec("req-tap-bake-product-image-1")
def test_the_base_must_be_named_by_digest() -> None:
    assert product_image.require_digest_ref(f"ghcr.io/org/tap-web@{DIGEST}")
    assert product_image.require_digest_ref(f"ghcr.io/org/tap-web:0.4.5@{DIGEST}")
    for ref in ("ghcr.io/org/tap-web:0.4.5", "ghcr.io/org/tap-web", f"ghcr.io/org/tap-web@{DIGEST[:-1]}"):
        with pytest.raises(product_image.ProductImageError, match="by digest"):
            product_image.require_digest_ref(ref)


@pytest.mark.spec("req-tap-bake-product-image-3")
def test_a_plugin_matching_its_manifest_entry_is_satisfied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dist = _fake_dist(tmp_path)
    monkeypatch.setattr(product_image, "installed_distributions", lambda: {"widget-tap": dist})
    assert product_image.plugin_problems(_record_entry(), _manifest(dist)) == []


@pytest.mark.spec("req-tap-bake-product-image-3")
def test_changing_one_installed_file_makes_the_plugin_unsatisfied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = _fake_dist(tmp_path)
    manifest = _manifest(dist)
    monkeypatch.setattr(product_image, "installed_distributions", lambda: {"widget-tap": dist})
    (tmp_path / "widget" / "__init__.py").write_bytes(b"VALUE = 2\n")
    assert product_image.plugin_problems(_record_entry(), manifest) == [
        "widget-tap: widget/__init__.py differs from its RECORD hash"
    ]


@pytest.mark.spec("req-tap-bake-product-image-3")
def test_an_edited_record_or_another_pin_is_unsatisfied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dist = _fake_dist(tmp_path)
    manifest = _manifest(dist)
    monkeypatch.setattr(product_image, "installed_distributions", lambda: {"widget-tap": dist})
    assert "the image was built from" in product_image.plugin_problems(_record_entry(OTHER), manifest)[0]
    record = Path(str(dist.locate_file(f"{Path(str(dist._path)).name}/RECORD")))  # type: ignore[attr-defined]
    record.write_text(record.read_text() + "widget/extra.py,,\n")
    assert product_image.plugin_problems(_record_entry(), manifest) == ["widget-tap: RECORD differs from the manifest"]


@pytest.mark.spec("req-tap-bake-product-image-3")
def test_a_plugin_absent_from_the_manifest_is_unsatisfied(tmp_path: Path) -> None:
    manifest = {"schema": product_image.MANIFEST_SCHEMA, "record": {}, "distributions": []}
    assert product_image.plugin_problems(_record_entry(), manifest) == [
        "plugin 'widget' is not in this image's install manifest"
    ]


@pytest.mark.spec("req-tap-bake-product-image")
def test_the_record_booted_is_the_record_baked(tmp_path: Path) -> None:
    record = tmp_path / "demo.boot.json"
    record.write_text('{"install": {}}\n')
    manifest = {"record": {"profile_id": "demo", "sha256": hashlib.sha256(record.read_bytes()).hexdigest()}}
    product_image.check_record(manifest, "demo", record)
    with pytest.raises(product_image.ProductImageError, match="built for boot record 'demo'"):
        product_image.check_record(manifest, "other", record)
    record.write_text('{"install": {"plugins": []}}\n')
    with pytest.raises(product_image.ProductImageError, match="not the one this image was built from"):
        product_image.check_record(manifest, "demo", record)


@pytest.mark.spec("req-tap-bake-product-image-2")
def test_the_build_refuses_sources_it_cannot_account_for() -> None:
    def record(source: dict[str, Any]) -> dict[str, Any]:
        return {"install": {"plugins": [{"slug": "widget", "source": source}]}}

    with pytest.raises(product_image.ProductImageError, match="git sources only"):
        product_image._record_plugins(record({"type": "editable", "path": "plugins/widget"}))
    with pytest.raises(product_image.ProductImageError, match="pinned 40-hex commit"):
        product_image._record_plugins(record({"type": "git", "url": URL, "rev": "v1.0.0"}))
    assert product_image._record_plugins(record({"type": "git", "url": URL, "rev": "v1", "commit": COMMIT}))


@pytest.mark.spec("req-tap-bake-product-image-2")
@pytest.mark.parametrize(
    ("slug", "url", "rev", "refused"),
    [
        ("../escape", URL, "v1", "lowercase identifier"),
        ("widget", "--upload-pack=touch /tmp/x", "v1", "plain https URL"),
        ("widget", "file:///etc", "v1", "plain https URL"),
        ("widget", "https://x-access-token:ghp_secret@forge.example/org/widget-tap", "v1", "plain https URL"),
        ("widget", "https://user@forge.example/org/widget-tap", "v1", "plain https URL"),
        ("widget", URL, "--output=x", "plain tag name"),
    ],
)
def test_the_record_cannot_steer_a_path_or_an_argv(slug: str, url: str, rev: str, refused: str) -> None:
    record = {
        "install": {"plugins": [{"slug": slug, "source": {"type": "git", "url": url, "rev": rev, "commit": COMMIT}}]}
    }
    with pytest.raises(product_image.ProductImageError, match=refused):
        product_image._record_plugins(record)


@pytest.mark.spec("req-tap-bake-product-image-2")
def test_compiled_closure_digests_are_read_per_distribution() -> None:
    compiled = (
        "boto3==1.40.1 \\\n"
        "    --hash=sha256:" + "1" * 64 + " \\\n"
        "    --hash=sha256:" + "2" * 64 + "\n"
        "    # via widget-tap\n"
        "widget-tap @ file:///tmp/w/widget_tap-1.0.0-py3-none-any.whl \\\n"
        "    --hash=sha256:" + "3" * 64 + "\n"
    )
    assert product_image._parse_compiled(compiled) == {
        "boto3": ["sha256:" + "1" * 64, "sha256:" + "2" * 64],
        "widget-tap": ["sha256:" + "3" * 64],
    }


@pytest.mark.spec("req-tap-bake-product-image-3")
def test_preboot_in_a_product_image_installs_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dist = _fake_dist(tmp_path)
    manifest = _manifest(dist, commit=OTHER)
    monkeypatch.setattr(product_image, "installed_distributions", lambda: {"widget-tap": dist})
    monkeypatch.setattr(preboot, "_install_plugins", lambda *a: pytest.fail("a product image must not install"))
    with pytest.raises(preboot.PrebootError, match="installs nothing at start"):
        preboot._check_product_plugins([_record_entry()], manifest)
    preboot._check_product_plugins([_record_entry()], _manifest(dist))


@pytest.mark.spec("req-tap-bake-product-image-3")
def test_preboot_reads_no_manifest_outside_a_product_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(product_image, "MANIFEST_PATH", tmp_path / "absent.json")
    assert preboot._product_manifest("core_dev") is None
    bad = tmp_path / "install-manifest.json"
    bad.write_text(json.dumps({"schema": "something/else"}))
    monkeypatch.setattr(product_image, "MANIFEST_PATH", bad)
    with pytest.raises(preboot.PrebootError, match="product image: .*schema"):
        preboot._product_manifest("core_dev")


def _product_block() -> str:
    text = (ROOT / "docker" / "entrypoint.sh").read_text()
    return text[text.index("# Product image (req-tap-bake-immutable-env)") : text.index("fi  # not a product image")]


@pytest.mark.spec("req-tap-bake-immutable-env-2")
def test_the_entrypoint_syncs_and_seeds_only_outside_a_product_image() -> None:
    text = (ROOT / "docker" / "entrypoint.sh").read_text()
    sync = text.index("    uv sync --all-packages\n")
    assert text.rfind('if [[ -z "${TAP_PRODUCT_IMAGE}" ]]; then', 0, sync) > text.rfind("\nfi\n", 0, sync)
    block = _product_block()
    assert "export UV_NO_SYNC=1 UV_OFFLINE=1" in block
    mount_re = re.search(r"grep -qE '([^']+)' /proc/self/mountinfo", block)
    assert mount_re, "a mount over the baked environment must be refused"
    pattern = re.compile(mount_re.group(1))
    for covered in ("/app", "/app/.venv", "/app/.venv/lib", "/app/tap-product"):
        assert pattern.search(f"36 25 0:41 / {covered} rw,relatime - overlay overlay rw"), covered
    for elsewhere in ("/app/logs", "/run/tap-gunicorn", "/app/.venvx"):
        assert not pattern.search(f"36 25 0:41 / {elsewhere} rw,relatime - tmpfs tmpfs rw"), elsewhere


@pytest.mark.spec("req-tap-bake-immutable-env-4")
def test_a_development_stack_has_no_manifest_and_keeps_its_venv_machinery() -> None:
    compose = (ROOT / "docker-compose.yml").read_text()
    assert re.search(r"^\s*-\s*\S*venv\S*:/app/\.venv", compose, re.M), "the dev stack keeps its venv volume"
    assert not (ROOT / "tap-product").exists()
    block = _product_block()
    assert block.index("if [[ -f /app/tap-product/install-manifest.json ]]; then") < block.index("TAP_PRODUCT_IMAGE=1")


@pytest.mark.spec("req-tap-bake-lifecycle-2")
def test_the_product_image_build_names_no_product() -> None:
    sources = [
        ROOT / "tap" / "product_image.py",
        ROOT / "docker" / "bake-product-image.sh",
        ROOT / "docker" / "product-image.Dockerfile",
        ROOT / ".github" / "workflows" / "bake-product-image.yml",
    ]
    names = sorted(
        {p.stem.split(".")[0] for p in (ROOT / "product-lines").glob("*")} | {"rampart", "playground", "samsite"}
    )
    for source in sources:
        text = source.read_text().lower()
        named = [n for n in names if n and re.search(rf"\b{re.escape(n.lower())}\b", text)]
        assert not named, f"{source.relative_to(ROOT)} names {named}"
    assert not [n for n in names if re.search(rf"\b{re.escape(n)}\b", _product_block().lower())]


@pytest.mark.spec("req-tap-bake-attest")
def test_the_workflow_publishes_only_a_verified_base_from_the_default_branch() -> None:
    workflow = (ROOT / ".github" / "workflows" / "bake-product-image.yml").read_text()
    on = workflow[workflow.index("\non:") : workflow.index("\npermissions:")]
    assert "workflow_call" in on and "pull_request" not in on
    guard = workflow.index("Refuse anything but a push or dispatch")
    assert guard < workflow.index("actions/checkout@"), "the branch guard runs before anything else"
    assert 'case "$EVENT" in push|workflow_dispatch)' in workflow
    assert '"refs/heads/${DEFAULT_BRANCH}"' in workflow
    verify = workflow.index("gh attestation verify")
    assert verify < workflow.index("docker cp "), "the base is verified before its Dockerfile is read"
    assert "--signer-workflow unified-systems-com/tap/.github/workflows/publish-images.yml" in workflow
