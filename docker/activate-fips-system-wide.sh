#!/bin/sh
# Activates the FIPS provider SYSTEM-WIDE by editing Wolfi's own stock
# /etc/ssl/openssl.cnf in place, instead of generating a separate file and
# displacing it via OPENSSL_CONF (the original per-image mechanism, kept as the
# TAP_FIPS_ACTIVATION=legacy fallback). POSIX sh + awk, no Python dependency --
# the DB image does not otherwise ship Python, and this script runs in both.
#
# Wolfi's stock file bundles an RFC 9325 TLS hardening policy
# ([ssl_module] -> system_default = crypto_policy) and Chainguard's own
# legacy-provider gating ([default]'s CHAINGUARD_LEGACY_* vars, [legacy_sect]).
# The OPENSSL_CONF override mechanism silently DISCARDS all of that (its own
# [openssl_init] never sets ssl_conf), which nobody had noticed until this
# file was written.
#
# Editing the stock file in place keeps what TAP actually needs and drops what
# it does not, rather than inheriting Chainguard's whole policy wholesale OR
# naively leaving FIPS-approval alone to stand in for TLS hardening -- these
# are different concerns (caught in review, verified directly, see below):
#
# - The legacy-provider config ([default], [legacy_sect], [default_sect]) is
#   DELETED outright, not left as inert leftovers -- we never activate
#   `legacy`/`default` under strict FIPS (provider_sect names fips+base only),
#   so it is dead config in a FIPS posture file, which is worse than no config.
# - `Groups` and `SignatureAlgorithms` (post-quantum/hybrid/MLDSA) and the
#   unused `DTLS.*` bounds (TAP is an HTTPS app) are DELETED. Tested directly:
#   pairing the unmodified values with strict fips+base broke EVERY outbound
#   TLS connection outright (`SSL_CTX_new_ex: error in system default config`,
#   `SSL_CONF_cmd: bad value` naming exactly these two directives) -- not a
#   degradation, a hard failure.
# - `Ciphersuites` and `CipherString` are KEPT. They were never implicated in
#   the breakage above, and deleting them anyway (an earlier version of this
#   script did) was a real mistake caught in review: `default_properties =
#   fips=yes` constrains WHICH PROVIDER implements an algorithm, not WHICH
#   SUITES get negotiated -- TLS 1.2 static-RSA key exchange and SHA-1 MACs
#   are individually FIPS-approved primitives that RFC 9325 excludes anyway.
#   Verified directly: with these two deleted, `openssl ciphers -s -tls1_2`
#   offered the full legacy OpenSSL default list (SSLv3-labeled static-RSA
#   suites included); with them kept, it is exactly the stock policy's 6
#   modern AEAD suites, same as before this mechanism existed.
# - `TLS.MinProtocol = TLSv1.2` / `TLS.MaxProtocol = TLSv1.3` is KEPT -- a
#   protocol version floor has nothing to do with which algorithms a provider
#   implements, so it carried none of the Groups/SignatureAlgorithms risk.
#
# Every edit below targets an exact, whole-line anchor (grep -qxF, not a
# substring match an inactive comment could also satisfy) and verifies it was
# found before editing, and verifies the result after editing -- plus a real
# functional check (`openssl list -providers`, not just string presence) at
# the very end. A silent no-op here is the fail-open trap
# (doc-fips-assessment-record.md L1) this whole self-check apparatus exists to
# catch -- so this script fails CLOSED (aborts the build) the moment Wolfi's
# stock file no longer matches what it expects, rather than silently leaving
# FIPS (or the suite/version floor) inactive.
set -eu

CNF=/etc/ssl/openssl.cnf
TMP="${CNF}.new"

require() {
  grep -qxF "$1" "$CNF" || { echo "FATAL: expected line not found (exact) in ${CNF}: $1" >&2; exit 1; }
}
require_absent() {
  grep -qxF "$1" "$CNF" && { echo "FATAL: expected line to be gone (exact) from ${CNF} but it is still there: $1" >&2; exit 1; }
  return 0
}

require 'openssl_conf = openssl_init'
require '[provider_sect]'
require 'default = default_sect'
require 'legacy = legacy_sect'
require 'providers = provider_sect'
require 'Groups = \'
require 'SignatureAlgorithms = \'
require 'Ciphersuites = TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256'
require 'CipherString = \'
require 'DTLS.MaxProtocol = DTLSv1.2'
require 'CHAINGUARD_LEGACY_ALLOWED = 1'

awk '
  # Line-exact insertions and substitutions.
  $0 == "openssl_conf = openssl_init" {
    print; print ".include /etc/ssl/fipsmodule.cnf"; next
  }
  $0 == "default = default_sect" { print "fips = fips_sect"; next }
  $0 == "legacy = legacy_sect"   { print "base = base_sect"; next }
  $0 == "providers = provider_sect" {
    print; print "alg_section = algorithm_sect"; next
  }

  # Dead config once provider_sect no longer names default/legacy: [legacy_sect]
  # and [default_sect] -- each header through the next [section] or EOF. [default]
  # is handled separately, by exact known lines, NOT the same way: unlike those two,
  # the ca.cnf include sits physically within defaults extent in the stock file
  # without being part of it (an include is a preprocessor directive, not a section
  # member) -- a whole-section delete here swallows it too, confirmed the hard way
  # (the post-edit check for it below caught it; this comment exists so the
  # mistake is not repeated; no literal quote marks in this comment block, since
  # it lives inside the outer shells own single-quoted awk program string, which
  # has no concept of an inner #-comment and just scans for the next quote char).
  $0 == "[default]"                        { next }
  $0 == "CHAINGUARD_LEGACY_ALLOWED = 1"    { next }
  $0 == "CHAINGUARD_LEGACY_ENABLE_DES = 0" { next }
  $0 == "[legacy_sect]"  { in_dead_section = 1; next }
  $0 == "[default_sect]" { in_dead_section = 1; next }
  in_dead_section && /^\[/ { in_dead_section = 0 }
  in_dead_section { next }

  # Not-FIPS-module-compatible crypto_policy directives: delete the directive
  # line and every backslash-continued line that follows it (Groups,
  # SignatureAlgorithms span several), or the single line (DTLS.*).
  # Ciphersuites/CipherString are KEPT -- see the module header for why.
  /^Groups = / || /^SignatureAlgorithms = / {
    in_continuation = 1
    if ($0 !~ /\\$/) in_continuation = 0
    next
  }
  in_continuation && /\\$/  { next }
  in_continuation           { in_continuation = 0; next }
  /^DTLS\.MaxProtocol = /   { next }
  /^DTLS\.MinProtocol = /   { next }

  # The comment above [crypto_policy] documented the PQC/hybrid/MLDSA/EdDSA/
  # brainpool support this script just deleted -- leaving it would be false
  # documentation, which is worse than no documentation. Replace it with an
  # accurate note the first time its first line is seen.
  $0 == "# As per RFC 9325, equivalent to:" {
    print "# Keeps the stock AEAD-only cipher suites and the TLS version floor; drops only"
    print "# the post-quantum/hybrid/MLDSA directives, which the FIPS module (3.0.22) does"
    print "# not implement and which broke outbound TLS outright when left in place."
    stale_comment = 1
    next
  }
  stale_comment && /^#/ { next }

  # Collapse runs of blank lines left behind by the deletions above into one --
  # cosmetic only (OpenSSL ini-style parsing ignores blank lines either way),
  # but this file is read by humans too.
  /^$/  { stale_comment = 0; if (prev_blank) next; prev_blank = 1; print; next }
  { stale_comment = 0; prev_blank = 0; print }
' "$CNF" > "$TMP"

# Strict fips + base provider set, fips=yes globally (base supplies encoders/decoders,
# no crypto primitives, required for key-file I/O -- not a hole in the boundary, L15).
printf '[base_sect]\nactivate = 1\n\n[algorithm_sect]\ndefault_properties = fips=yes\n' >> "$TMP"

mv "$TMP" "$CNF"

require 'fips = fips_sect'
require 'base = base_sect'
require 'alg_section = algorithm_sect'
require 'default_properties = fips=yes'
require 'ssl_conf = ssl_module'
require '.include ca.cnf'
require 'TLS.MinProtocol = TLSv1.2'
require 'TLS.MaxProtocol = TLSv1.3'
require 'Ciphersuites = TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256'
require 'CipherString = \'
require_absent 'legacy = legacy_sect'
require_absent 'CHAINGUARD_LEGACY_ALLOWED = 1'
require_absent '[legacy_sect]'
require_absent '[default_sect]'
require_absent '[default]'
require_absent 'Groups = \'
require_absent 'SignatureAlgorithms = \'
require_absent 'DTLS.MaxProtocol = DTLSv1.2'
require_absent '# As per RFC 9325, equivalent to:'

echo "=== ${CNF} after system-wide FIPS activation ==="
cat "$CNF"

# Functional check, not just string presence (a textual require can be satisfied by a
# config OpenSSL itself refuses to load correctly -- this asks OpenSSL to report its own
# state instead of trusting the file). No OPENSSL_CONF is set at this point, so this reads
# the file just edited at its real default path, exactly as every later process will.
echo "=== functional check: openssl list -providers (the edited config, read the same way every later process will) ==="
providers_output="$(openssl list -providers)"
echo "$providers_output"
echo "$providers_output" | grep -qxF '  fips' || { echo "FATAL: openssl itself does not report the fips provider active" >&2; exit 1; }
echo "$providers_output" | grep -qxF '  base' || { echo "FATAL: openssl itself does not report the base provider active" >&2; exit 1; }
if echo "$providers_output" | grep -qxF '  default'; then
  echo "FATAL: openssl itself reports the default (non-FIPS) provider active" >&2
  exit 1
fi
if echo "$providers_output" | grep -qxF '  legacy'; then
  echo "FATAL: openssl itself reports the legacy (non-FIPS) provider active" >&2
  exit 1
fi
