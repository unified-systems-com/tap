# Changelog

## [0.1.3](https://github.com/unified-systems-com/tap/compare/v0.1.2...v0.1.3) (2026-08-20)


### Features

* **cicd:** consumers pin a version instead of tracking :latest ([60f2093](https://github.com/unified-systems-com/tap/commit/60f2093ec7e2aab38bcaf435bb32f66e86165eff))
* **cicd:** digest-threaded publish pipeline (req-cicd-supply-chain-provenance-1) ([0c4c953](https://github.com/unified-systems-com/tap/commit/0c4c953f3c09b97a81d38bb7c66c9582cea8cc17))
* **dco:** remediation commits — certify retroactively without rewriting history ([026b1f9](https://github.com/unified-systems-com/tap/commit/026b1f9e3c6a6b957655a0e25bfc475271b7e36d))
* **grid:** EntityType.kind — discriminate node vs edge in the type catalog ([0ab001a](https://github.com/unified-systems-com/tap/commit/0ab001aeeb75073ecebe186849425ae3c2163eed))
* **health:** probe selection sets — liveness/readiness, declared and mandatory ([fdfe4c3](https://github.com/unified-systems-com/tap/commit/fdfe4c3eb21dba17824d71b9c455e7a5f8ed7169))
* **health:** serving, grid-table and plugins-loaded probes ([3394ad0](https://github.com/unified-systems-com/tap/commit/3394ad0e9eb2155b4a8e0c56556fa2296db0731b))
* **policy:** CONTRIBUTING + DCO land as approved policy; sign-off enforcement ON ([90d5a14](https://github.com/unified-systems-com/tap/commit/90d5a14ad295efd345836812a9e235b0ea9e6214))


### Bug Fixes

* **auth:** enrollment link origin IS the ceremony origin (sweep S2) ([3cca3ac](https://github.com/unified-systems-com/tap/commit/3cca3acf313cc8ca5a08d86466c1a79632c24973))
* **cicd:** base compose is pull-only — building is an explicit opt-in overlay ([fdd6139](https://github.com/unified-systems-com/tap/commit/fdd61399fe3598b246226c895b1cef6631cb09f0))
* **cicd:** CI rides tap-db:latest — the version pin is a consumer contract ([f734c2f](https://github.com/unified-systems-com/tap/commit/f734c2f2f7ed2b50ee24f6ba44433dfe9cc589f5))
* **cicd:** release-commit publishes survive newest-main-wins cancellation ([2dc00c1](https://github.com/unified-systems-com/tap/commit/2dc00c1efd89585a3d7511f500437d6c130548c1))
* nine duplicate-fact collapses + four boot/auth precision fixes ([0becf1a](https://github.com/unified-systems-com/tap/commit/0becf1a34c25d750f44c9c3f7289953da724da06))


### Documentation

* **grid:** backlog req for first-party types in the type catalog ([3a3704a](https://github.com/unified-systems-com/tap/commit/3a3704a563b9c63b4a2da3ca56fb68a014e09ab1))
* **grid:** sharpen the stale-catalog-rows gap — accumulated state, not fresh-instance behaviour ([7f75fe6](https://github.com/unified-systems-com/tap/commit/7f75fe6ea719175a302da96b01d4979b9f12013d))
* **health:** correct the entity-type catalog non-goal — measured causes, not a classification issue ([2ea3117](https://github.com/unified-systems-com/tap/commit/2ea31176ccd6f10812e17bf5c4ebbca262171830))
* **misc:** duplicate-derivation backlog — the open ~30, with the detectors ([0baae29](https://github.com/unified-systems-com/tap/commit/0baae2949357de413af44bf53cefe2309a14efac))
* **plugins:** lifecycle v1 — define the departure contract (req-plugin-lifecycle-v1-departure) ([2852990](https://github.com/unified-systems-com/tap/commit/2852990953e989e8b81d5e69e4f001b18f2bf02b))
* **policy:** correct the approval provenance recorded in 90d5a14a ([a28419b](https://github.com/unified-systems-com/tap/commit/a28419bf89fa5c951aacd86e5822157510e9022f))

## [0.1.2](https://github.com/unified-systems-com/tap/compare/v0.1.1...v0.1.2) (2026-08-12)


### Features

* **grid:** grid-table classification single source (req-grid-table-classification.sec) ([e805865](https://github.com/unified-systems-com/tap/commit/e80586571a34061c631c24312f642a18f6e7b7a7))
* **specs:** TAP-KNOWN-DUPE convention for intentional duplicates (req-tap-known-dupes) ([24767b3](https://github.com/unified-systems-com/tap/commit/24767b317fde60f7390c1d75e20d6fe6c60e46b0))


### Bug Fixes

* **auth:** built-in actor keys collapse to one code home (audit [#2](https://github.com/unified-systems-com/tap/issues/2)) ([264e899](https://github.com/unified-systems-com/tap/commit/264e899ea14801dc430a82b2d4dd0302502ec1b6))
* **auth:** request identity derived once, at the middleware (audit [#4](https://github.com/unified-systems-com/tap/issues/4)) ([a0c977a](https://github.com/unified-systems-com/tap/commit/a0c977ae0e2570c1c640a4348522d928ddfa9767))
* **secrets:** secrets-root resolution collapses to two canonical lookups (audit [#3](https://github.com/unified-systems-com/tap/issues/3)) ([b92a168](https://github.com/unified-systems-com/tap/commit/b92a168464aba25ed9930b7cb130160dd4eb9fc2))


### Documentation

* **plugins:** spec-tap-plugin-lifecycle-v1 DRAFT — transactional plugin load/update wrapper ([af77348](https://github.com/unified-systems-com/tap/commit/af77348326acd3b9991b7d78ed91df9ab96c4a01))

## [0.1.1](https://github.com/unified-systems-com/tap/compare/v0.1.0...v0.1.1) (2026-08-12)


### Features

* **grid:** edge property lanes — central hotlink check + schema-required warn mode ([871f7f7](https://github.com/unified-systems-com/tap/commit/871f7f77bdc197a4868f3572e5a775e620f404b3))


### Bug Fixes

* **boot:** TAP_PLUGINS is authoritative — collapse the two-source plugin-set race ([e4183c3](https://github.com/unified-systems-com/tap/commit/e4183c3664295f42fa9ce08d7f6cf61a52da2604))
* **cicd:** wire the release lane to the real app — tap-release-please ([d345c62](https://github.com/unified-systems-com/tap/commit/d345c627e9beaecea2d80206075f321b24989ecf))
* **ci:** gate api-fuzz boot on migrations APPLIED, not just health — the real flake root ([625ae08](https://github.com/unified-systems-com/tap/commit/625ae086017cda375c963afe02ce98a64c3847c0))
* **grid:** annotate migration functions + registry fixture — mypy ratchet clean ([8d942f9](https://github.com/unified-systems-com/tap/commit/8d942f94b1756e425453d3e47114d3d80ba308de))
* **health:** diversify readiness with a critical 'migrations' probe — the real flake fix ([b70d7f9](https://github.com/unified-systems-com/tap/commit/b70d7f93507ca0cb9e213fb82777baa9c6362f99))


### Documentation

* **dev-validation:** close the api-fuzz known-flake ledger row — two-source INSTALLED_APPS divergence, root-caused + fixed ([f242cf9](https://github.com/unified-systems-com/tap/commit/f242cf9444073833cfbb6755dacea40f6eb96307))
* **dev-validation:** correct the known-flake ledger — the real root was migrate-vs-boot, fixed by the migrations readiness probe ([d02b444](https://github.com/unified-systems-com/tap/commit/d02b444d7aceca68e701365c34bf6a3d0e010d51))
* **health:** probes-4 ACID — add migrations to the enumerated critical set ([2cbd947](https://github.com/unified-systems-com/tap/commit/2cbd94788976a7829cb8051cfa4de8338d6059e5))
* **health:** record the migrations probe in spec-tap-health-v0 — the first readiness-class probe ([3bbfa8f](https://github.com/unified-systems-com/tap/commit/3bbfa8f2d4c3e354e9e8b4161dcef051e2cd0310))
* **spec:** api-fuzz flake ESCALATED — recurred same day; investigation owned by session/unified ([cd70a1b](https://github.com/unified-systems-com/tap/commit/cd70a1beac5d59d31101109248619ec058e0f5de))
* **spec:** api-fuzz known-flake ledger — track setup-phase reds across sessions ([4b6104f](https://github.com/unified-systems-com/tap/commit/4b6104fc0ea546a89a0139454f62365337922d4c))
