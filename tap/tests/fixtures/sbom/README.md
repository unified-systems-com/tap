# tap-web-trimmed.cdx.json

14 components cut from the attested tap-web arm64 CycloneDX 1.7 document (Syft 1.51.0, built 2026-10-15T15:02:05Z,
image digest `sha256:a9149a88a6239fc7a5351d9854fbff42448d2ed28cc71951a4c2aa2f4aca7750`, 192 components). SHA-256 of
the source file as downloaded with `gh attestation download`: `734809b9e5439845a25776385f36e50874789d7069e8231fe9ad80990d417aba`.

It is inert test data used by `tap/tests/test_sbom_completeness.py` (`req-cicd-sbom-32-9`). The hashes and base64 in it
are the source document's own. `evidence` was deleted from each component. To regenerate it from the source file `$S`:

```
jq '{bomFormat,specVersion,serialNumber,version,
     metadata:{timestamp:.metadata.timestamp, component:.metadata.component},
     components:( [.components[]|select(.type=="operating-system")]
       + [.components[]|select(.purl!=null and (.purl|startswith("pkg:apk")) and (.purl|test("upstream=")))][0:3]
       + [.components[]|select(.purl!=null and (.purl|startswith("pkg:apk")) and (.purl|test("upstream=")|not))][0:3]
       + [.components[]|select(.purl!=null and (.purl|startswith("pkg:pypi")))][0:2]
       + [.components[]|select(.purl!=null and (.purl|startswith("pkg:npm")))][0:2]
       + [.components[]|select(.purl!=null and (.purl|startswith("pkg:generic")))][0:1]
       + [.components[]|select(.purl!=null and (.purl|startswith("pkg:github")))][0:2]
     )|map(del(.evidence)) }' "$S"
```

# wheel-seed-records.txt and locked-pypi.txt (tests for scripts/sbom/wheel_attributes.py, req-cicd-sbom-33)

- `wheel-seed-records.txt` is the output of `wheel_attributes.SEED_SCRIPT` run inside the local
  `ghcr.io/unified-systems-com/tap-web:latest` image on 2026-10-19:
  `docker run --rm --entrypoint sh <image> -c "$SEED_SCRIPT"`. It is the WHEEL and METADATA headers of all 73 wheels
  in the image's cache seed (`/opt/uv-cache-seed/archive-v0`), unedited.
- `locked-pypi.txt` is the 71 pypi `name-version` keys of the attested tap-web revision 1
  (`sha256:a9149a88a6239fc7a5351d9854fbff42448d2ed28cc71951a4c2aa2f4aca7750`), names as Syft wrote them, one per line.
