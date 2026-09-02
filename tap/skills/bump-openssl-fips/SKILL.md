---
name: bump-openssl-fips
description: Check whether TAP's pinned OpenSSL FIPS provider is still current, and move it if it is not. Use for "is our OpenSSL still good", "check the OpenSSL pins", "OpenSSL CVE", "bump the FIPS provider", a drift-check failure, or any advisory naming the version in docker/build-openssl-fips.sh. Covers the decision gate (when a bump is warranted at all), the transcription, and every file that must move together.
allowed-tools: Read Edit Bash(scripts/verify-openssl-release *) Bash(git status *) Bash(git diff *) Bash(git log *) Bash(git add *) Bash(git commit *) Bash(curl *) Bash(gpg *) Bash(scripts/dc *) Grep Glob
argument-hint: [<target-version> | "check"]
---

# Bump the OpenSSL FIPS provider

**Read this before editing any pin.** The provider is the single most compliance-significant binary
in the image, and a half-applied bump is worse than no bump: it ships a *false* declaration, which
makes the vulnerability detection we built report on a version we no longer run.

## 0. The governing rule

A CMVP-validated module is **frozen at the validated version by construction**. So the pin does not
age out the way a dependency pin does, and *a newer version existing is not a reason to move*.

But frozen is not permanent. The operator ruling (2026-08-31) is explicit:

> **A secure OpenSSL matters more than a FIPS-validated one.** Patching a serious flaw is the
> expected outcome; validated-module status is what yields.

Decision D17 (2026-09-02, `docs/misc/doc-fips-assessment-record.md` §2) reads that literally: the
pin tracks the FIPS code line's patched releases, and when the pinned version carries no
certificate the artifact is declared "FIPS mode on, NOT CMVP-validated as shipped" — a derived,
distinct state (`tap/fips_pins.py`), never a hand-written claim. Re-pin to a version in the
`OSSL_CMVP_VALIDATED` table only for a build an audit needs the certificate for.

So: **do not bump casually. Do bump for a vulnerability.** Both halves are load-bearing.

## 1. Decide whether a bump is warranted — this is the gate

Exactly four triggers justify moving. Anything else is noise:

| Trigger | How you learned it |
| --- | --- |
| Published sha256 no longer matches the pin | `scripts/verify-openssl-release` reports CHANGED |
| The signing key is no longer authorized at the tag | same |
| **A CVE affects code inside the FIPS provider** | an advisory naming our version, then §2 triage |
| CMVP #4282 moved to Historical | a human checked; nothing automates this yet |

⚠️ **"A newer release exists" is NOT a trigger.** If that is all you have, stop here.

## 2. If the trigger is a CVE, triage it BEFORE deciding

Most OpenSSL CVEs do not affect us, and acting on the raw list is how this channel becomes noise.
Measured on 2026-08-31: the CPE for 3.0.9 returned **38 CVEs**, of which **6 were not OpenSSL at
all** (Mutt, OpenLDAP, mod_ssl — other products indexed under OpenSSL's CPE), and **11 of the 12 most
severe were in code the FIPS provider does not contain.**

`fips.so` holds algorithm implementations only — ciphers, digests, MACs, DRBGs, RSA/EC/DH, KDFs and
the self-tests. **TLS, DTLS, X.509, CMS, PKCS#7, PKCS#12, ASN.1 parsing and BIO are NOT in it**; we
run the base image's modern libcrypto (3.6.x) for all of that.

The triage is mechanical — ask the binary, not the description:

```bash
# in a container carrying the provider
strings /usr/lib/ossl-modules/fips.so > /tmp/s.txt
grep -ci "<symbol-or-subsystem-from-the-advisory>" /tmp/s.txt
```

Absent → the vulnerable code is not in the module we ship; record that and stop. Present → it is a
real candidate; confirm against the advisory's fix commits before moving.

**Also ask whether we USE it.** A vulnerable primitive we never call is a different risk from one on
the passkey or TLS path. `tap.crypto_bom` is the inventory for that question.

## 3. Get the target version's facts — transcribe, never type

```bash
scripts/verify-openssl-release <target-version>
```

It prints `OSSL_VERSION`, `OSSL_SHA256`, and the authorized signer fingerprints **at that tag**.
Exit codes: `0` all hold, `1` something CHANGED, `2` something NOT OBSERVABLE — never treat `2` as
success.

⚠️ **The trap that cost an afternoon on tap#221:** the `.asc` names the signing **SUBKEY**, while
`doc/fingerprints.txt` lists **PRIMARIES**. Comparing them directly makes an authorized key look
unlisted. `OSSL_SIGNING_PRIMARY` is the **primary**.

⚠️ **The tag's own `fingerprints.txt` is the authority.** The list published on openssl-library.org
names only currently-active signers and will not vouch for an older release.

## 4. Confirm the target is validated — or record that it is not

- If the target version has **its own CMVP certificate**, add it to `OSSL_CMVP_VALIDATED` in
  `docker/build-openssl-fips.sh` (transcribed from the certificate's CMVP page — number, standard,
  sunset); the derived posture then reports it everywhere. **Or**
- Record this as a **security-driven move under the exit ramp** (D17 is the standing policy; name
  the CVE triage and the decider in the assessment record). The derived posture flips to
  `FIPS_MODE_UNVALIDATED_BUILD` on its own; what the `fips-validation-claims` guard then names is
  every prose claim that still says "CMVP #…" or "FIPS-validated" — fix the prose, never the guard.

## 5. Edit every site, in one commit

A bump that lands in some files and not others is the failure this skill exists to prevent.

| File | What changes |
| --- | --- |
| `docker/build-openssl-fips.sh` | `OSSL_VERSION`, `OSSL_SHA256`, `OSSL_SIGNING_PRIMARY` if the signer changed, and `OSSL_CMVP_VALIDATED` if the target is certified |
| `docker/openssl-release-keys.asc` | replace **only if** the signer changed — and update its provenance header (retrieval command, date, keyserver) |
| `docker/sbom-supplemental.json` | `version`, `source`, `purl` (twice — coordinate **and** the encoded `download_url`), `cpe` |
| `docker/postgres/sbom-supplemental.json` | the same fields — **both images build the same provider** |
| `README.md` | the derived status clause (`tap.fips_pins.Pins.status_clause()`, verbatim — the guard checks it) |
| `specs/spec-fips.md`, `specs/spec-cicd-hardening.md`, `Dockerfile`, `docker/postgres/Dockerfile` | any prose naming the version or a certificate (the guard covers the Dockerfiles, README and supplementals) |
| `docs/misc/doc-fips-assessment-record.md` | the decision entry naming the CVE triage and the decider (D17 pattern) |

`grep -rn "<old-version>" docker/ specs/ README.md` before committing, then `scripts/dc exec web uv run pytest tap/tests/test_fips_pins.py tap/tests/test_guards.py -k fips` — the guard is the list of what is still stale. Prose mentions are commentary; the pins and
the SBOM fields are not.

## 6. Verify by building, and by watching it refuse

```bash
docker build --progress=plain --no-cache --target ossl-builder -t ossl-check .
scripts/verify-openssl-release            # must now report 4 holds against the NEW pin
```

The build must show both gates passing. Then prove they still *bite*: temporarily wrong-digit the
`OSSL_SHA256` and confirm the build fails closed at gate one. A gate nobody has watched fail is
indistinguishable from one that cannot.

Finally, confirm the DB image builds too — it runs the same script and is the half that was
unverified until 2026-08-29 (tap#232).

## Canon

- `specs/spec-fips.md` — `req-fips-pin-currency` (this procedure), the crypto-BOM requirements
- `specs/spec-cicd-hardening.md` — `req-cicd-supply-chain-provenance-3` (the two source gates)
- `docs/misc/doc-fips-assessment-record.md` — the decision/lessons record (D4, D13, D15, L1, L13)
- `docker/build-openssl-fips.sh` — the pins, the exit ramp, and the bump procedure at the point of use
