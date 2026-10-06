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
# it does not, rather than inheriting Chainguard's whole policy wholesale:
#
# - The legacy-provider config ([default]'s two vars, [legacy_sect]) is
#   DELETED outright, not left as inert leftovers -- we never activate
#   `legacy` under strict FIPS (provider_sect names fips+base only), so it is
#   dead config in a FIPS posture file, which is worse than no config.
#   [default_sect] is equally dead once provider_sect no longer names
#   `default`, and goes too.
# - crypto_policy's `Groups`, `SignatureAlgorithms`, `Ciphersuites`,
#   `CipherString` and `DTLS.*` bounds are DELETED. They are Chainguard's bet
#   on being ready for every customer's post-quantum migration (hybrid
#   X25519MLKEM768 key exchange, MLDSA signatures, brainpool curves, a DTLS
#   policy TAP -- an HTTPS app -- never uses). Tested directly: pairing the
#   unmodified policy with strict fips+base broke EVERY outbound TLS
#   connection outright (`SSL_CTX_new_ex: error in system default config`,
#   `SSL_CONF_cmd: bad value` naming Groups/SignatureAlgorithms by name) --
#   not a degradation, a hard failure. Rather than hand-maintain a second,
#   parallel allowlist of "FIPS-safe" cipher suites (which duplicates work the
#   provider boundary already does and is its own maintenance burden), this
#   leaves TLS group/cipher/signature negotiation to openssl-3.6's own
#   built-in defaults -- which `[algorithm_sect] default_properties = fips=yes`
#   (added below) already forces through the FIPS-only provider set for every
#   algorithm fetch in the process, TLS included. Confirmed working this way:
#   the FIPS module (3.0.22) turns out to implement X25519/X448 itself (NIST
#   SP 800-186 added them as approved curves), so the provider boundary alone
#   negotiated a FIPS-approved connection with no hand-curated list needed.
# - `TLS.MinProtocol = TLSv1.2` / `TLS.MaxProtocol = TLSv1.3` is KEPT -- a
#   protocol version floor is genuinely bog-standard and has nothing to do
#   with which algorithms a provider implements, so it carries none of the
#   breakage risk the algorithm-naming directives did.
#
# Every edit below targets an exact anchor and verifies it was found before
# editing, and verifies the result after editing. A silent no-op here is the
# fail-open trap (doc-fips-assessment-record.md L1) this whole self-check
# apparatus exists to catch -- so this script fails CLOSED (aborts the build)
# the moment Wolfi's stock file no longer matches what it expects, rather
# than silently leaving FIPS (or the version floor) inactive.
set -eu

CNF=/etc/ssl/openssl.cnf
TMP="${CNF}.new"

require() {
  grep -qF "$1" "$CNF" || { echo "FATAL: expected line not found in ${CNF}: $1" >&2; exit 1; }
}
require_absent() {
  grep -qF "$1" "$CNF" && { echo "FATAL: expected line to be gone from ${CNF} but it is still there: $1" >&2; exit 1; }
  return 0
}

require 'openssl_conf = openssl_init'
require '[provider_sect]'
require 'default = default_sect'
require 'legacy = legacy_sect'
require 'providers = provider_sect'
require 'Groups = '
require 'SignatureAlgorithms = '
require 'Ciphersuites = '
require 'CipherString = '
require 'DTLS.MaxProtocol'
require 'CHAINGUARD_LEGACY_ALLOWED'

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

  # Dead config once provider_sect no longer names default/legacy: the
  # [default] header and its two CHAINGUARD_LEGACY_* vars, and the
  # [legacy_sect]/[default_sect] sections entirely (header through the next
  # [section] or EOF).
  $0 == "[default]"                        { next }
  $0 == "CHAINGUARD_LEGACY_ALLOWED = 1"    { next }
  $0 == "CHAINGUARD_LEGACY_ENABLE_DES = 0" { next }
  $0 == "[legacy_sect]"  { in_dead_section = 1; next }
  $0 == "[default_sect]" { in_dead_section = 1; next }
  in_dead_section && /^\[/ { in_dead_section = 0 }
  in_dead_section { next }

  # Not-FIPS-module-compatible crypto_policy directives: delete the directive
  # line and every backslash-continued line that follows it (Groups,
  # SignatureAlgorithms, CipherString each span several), or the single line
  # (Ciphersuites, DTLS.*).
  /^Groups = / || /^SignatureAlgorithms = / || /^CipherString = / {
    in_continuation = 1
    if ($0 !~ /\\$/) in_continuation = 0
    next
  }
  in_continuation && /\\$/  { next }
  in_continuation           { in_continuation = 0; next }
  /^Ciphersuites = /        { next }
  /^DTLS\.MaxProtocol = /   { next }
  /^DTLS\.MinProtocol = /   { next }

  # The comment above [crypto_policy] documented the PQC/hybrid/MLDSA/EdDSA/
  # brainpool support this script just deleted -- leaving it would be false
  # documentation, which is worse than no documentation. Replace it with an
  # accurate note the first time its first line is seen.
  $0 == "# As per RFC 9325, equivalent to:" {
    print "# TLS version floor only -- group/cipher/signature-algorithm negotiation is left"
    print "# to openssl-3.6'\''s own built-in defaults, which default_properties=fips=yes below"
    print "# already forces through the FIPS-only provider set (tested: the stock policy is"
    print "# not FIPS-module-compatible and broke outbound TLS outright when left in place)."
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
require_absent 'legacy = legacy_sect'
require_absent 'CHAINGUARD_LEGACY_ALLOWED'
require_absent '[legacy_sect]'
require_absent '[default_sect]'
require_absent '[default]'
require_absent 'Groups = '
require_absent 'SignatureAlgorithms = '
require_absent 'Ciphersuites = '
require_absent 'CipherString = '
require_absent 'DTLS.MaxProtocol'
require_absent 'pure-PQC'

echo "=== ${CNF} after system-wide FIPS activation ==="
cat "$CNF"
