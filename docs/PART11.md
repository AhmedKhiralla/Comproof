# Comproof — 21 CFR Part 11 traceability

This maps each Part 11 requirement to how Comproof meets it, and to the automated test that proves it where one
exists. It supports, but does not replace, the customer's own validation (URS, risk assessment, IQ/OQ/PQ),
procedures and training. Comproof is configurable, off-the-shelf software (GAMP 5 category 4).

## Subpart B — Electronic records

| Clause | Requirement | How Comproof meets it | Evidence |
|---|---|---|---|
| 11.10(a) | Validation; ability to discern invalid or altered records | Every file is stored content-addressed by SHA-256 and re-hashed on every read; a mismatch refuses the file. Each comparison result is hashed (`result_sha256`) and every screenshot's SHA-256 is kept in a manifest checked before it is served. The audit trail is hash-chained per company and can be verified on demand (Audit → Verify). The engine version is stamped on every result. | `test_comparison_run_and_findings`, `test_audit_trail_hash_chain`, `test_records_cannot_be_altered_in_database` |
| 11.10(b) | Accurate and complete copies, human-readable and electronic | Interactive report, PDF report, Excel findings log and standalone HTML report; the original uploaded files can be downloaded unchanged. Exports are audited. | `test_exports` |
| 11.10(a) | (colour) | Each shade set's measurement (inks, sample points, L*a*b*) is hashed; the preview images' hashes are inside it. A comparison records the measurement hash it was run against and the worker refuses a measurement whose hash no longer matches. | `test_shade_set_verification_and_signature`, `test_colour_check_of_samples` |
| 11.10(c) | Protection of records for their retention period | Files, decisions and signatures are append-only (database triggers reject UPDATE and DELETE; the application role has SELECT and INSERT only). Comparisons and artwork versions cannot be deleted; closed comparisons are immutable. Files are written read-only (0440) to a persistent volume. Retention and backup of the database and volume follow the customer's procedure (Railway backups or equivalent). | `test_records_cannot_be_altered_in_database` |
| 11.10(d) | Limiting system access to authorised individuals | Named accounts created by the company administrator; roles per site (artwork editor, reviewer, approver, viewer); PostgreSQL row-level security isolates companies even if application code is wrong; sessions time out on inactivity. | `test_other_company_cannot_see_comparison`, foundation tests |
| 11.10(e) | Secure, computer-generated, time-stamped audit trail | Database triggers write the audit trail — the application cannot skip it. Each entry records who, what, when (server UTC), the old and new values and the reason, and links to the previous entry's hash. Users cannot change or delete it. Engine runs record RUN_STARTED / RUN_FINISHED / RUN_FAILED; file uploads, downloads, exports and failed signatures are recorded too. | `test_audit_trail_hash_chain`, foundation tests |
| 11.10(f) | Operational system checks (enforced sequencing) | A shade set can become the colour reference only through an approval signature on its measurement hash, and never when the Light / Standard / Dark verification failed; its measurement can never change (database guard). Database guards enforce the workflow: queued → running → review → approved / rejected; findings can be decided only during review; approval or rejection requires a matching signature whose record hash equals the result hash; four-eyes and all-decided rules; an artwork version becomes the effective master only through an approval signature. | `test_review_and_signature_rules`, `test_library_and_master_signature` |
| 11.10(g) | Authority checks | Every endpoint checks the user's role at the site; signing re-checks the role for the meaning being signed (only approvers approve masters and comparisons). | `test_library_and_master_signature`, `test_review_and_signature_rules` |
| 11.10(h) | Device checks (validity of the source of data input) | Uploads are identified by their content (magic bytes), not their name; unsupported types are refused. The input type (vector PDF, scanned PDF, image, Word) and page count are recorded with the file. | `test_library_and_master_signature` |
| 11.10(i) | Training of people who develop, maintain or use the system | Customer procedure. Comp11 Labs provides the user guide, the administrator guide and this document. | — |
| 11.10(j) | Written policies holding individuals accountable for e-signatures | Customer procedure. The signing dialog shows the legal statement that the electronic signature is the binding equivalent of a handwritten one. | — |
| 11.10(k) | Controls over system documentation | Documentation is versioned with the source in Git; each release has a version number shown in the app. | — |
| 11.30 | Open systems | Hosted over HTTPS only (secure cookies, HSTS, strict content security policy). AI providers receive only page images and text of the documents being compared, over HTTPS, and only when the company switches AI on. | — |

## Subpart C — Electronic signatures

| Clause | Requirement | How Comproof meets it | Evidence |
|---|---|---|---|
| 11.50(a) | Signed records show name, date and time, and meaning | Each signature stores the signer's full name, server UTC time, the meaning (reviewed, approved, rejected, approved as master, withdrawn), the exact statement shown, the reason, and the hash of the record signed. The report and exports show all of these. | `test_review_and_signature_rules` |
| 11.50(b) | Same controls as records; shown in human-readable form | Signatures are append-only rows covered by the audit trail and appear in every report and export. | `test_records_cannot_be_altered_in_database` |
| 11.70 | Signature/record linking | Shade set signatures carry the SHA-256 of the measurement. The signature carries the SHA-256 of the result it was given against; the database refuses an approval whose signature hash differs from the record. A signature cannot be copied to another record. | `test_review_and_signature_rules` |
| 11.100(a) | Unique to one individual, not reused or reassigned | Email is unique; accounts are deactivated, never deleted or renamed to someone else. | foundation tests |
| 11.100(b) | Identity verified before assigning | Customer procedure; the company administrator creates the account. | — |
| 11.100(c) | Certification to the agency | Customer letter to FDA (and local equivalents). | — |
| 11.200(a)(1) | Two distinct components (ID and password); re-entered for each signing | Each signature asks for email and password again, even within a session. | `test_library_and_master_signature` |
| 11.200(a)(2) | Used only by the genuine owner | The signer must be the signed-in user; failed attempts are audited (SIGNATURE_FAILED) and count toward account lockout, which also ends the sessions. | `test_library_and_master_signature` |
| 11.200(b) | Biometrics | Not used. | — |
| 11.300(a) | Uniqueness of ID/password combinations | Unique email; passwords hashed (scrypt); password history prevents reuse. | foundation tests |
| 11.300(b) | Periodic checking, recall or revision | Password expiry (default 90 days, configurable 0–365), forced change at first sign-in and after an administrator reset. | foundation tests |
| 11.300(c) | Loss management | The administrator deactivates the account or resets the password; sessions are revoked. | foundation tests |
| 11.300(d) | Safeguards against unauthorised use; reporting attempts | Lockout after failed sign-ins or signatures (default 5 attempts, 30 minutes); every failure is in the audit trail with the IP address. | foundation tests |
| 11.300(e) | Testing of devices that generate ID/passwords | Not applicable (no tokens or cards). | — |

## Password and session policy (per company, Settings → Security)

| Setting | Default | Allowed |
|---|---|---|
| Minimum length | 10 | 8–64 |
| Upper, lower, digit, symbol | required | on / off |
| Expiry | 90 days | 0 (never) – 365 |
| History | 5 | 0–24 |
| Failed attempts before lockout | 5 | 3–10 |
| Lockout | 30 minutes | 5–1440 |
| Inactivity timeout | 30 minutes | 5–240 |

## What the customer validates

- **IQ** — the deployed version, environment variables, database and volume, backups.
- **OQ** — run the automated test suite against the deployed version and execute the scripted test cases in the
  validation pack (sign-in, roles, signatures, workflow guards, audit trail verification, exports).
- **PQ** — compare a set of the customer's own approved and test files with known, seeded differences (numbers,
  dosage form, missing sentences, punctuation, Arabic) and record that each is found at the expected level.
- **Engine changes** — every result carries the engine version; a new engine version is a change control.
