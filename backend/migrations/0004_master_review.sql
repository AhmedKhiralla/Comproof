-- Comproof 1.2: review of the approved (reference) packaging material on its own - Level 1 and the checks that
-- need one file only (barcode validity, text size, Braille, dieline). No test file.

ALTER TABLE comparisons DROP CONSTRAINT comparisons_purpose_check;
ALTER TABLE comparisons ADD CONSTRAINT comparisons_purpose_check
  CHECK (purpose IN ('proof', 'printed_sample', 'supplier_proof', 'master_review'));
ALTER TABLE comparisons ALTER COLUMN test_file_id DROP NOT NULL;
ALTER TABLE comparisons ADD CONSTRAINT comparisons_test_file_rule
  CHECK ((purpose = 'master_review') = (test_file_id IS NULL));
