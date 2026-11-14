-- Comproof 1.4: what an approved version is a reference FOR.
--   layout  the approved artwork as laid out: page layout and reading order are part of what was approved
--   text    the approved text (typically the Word file the authority approved): line wraps, hyphenation at line ends
--           and the order in which the designer places sections on columns, panels and pages are not deviations
-- Set when the version is registered and fixed from then on, so the signed reference always means the same thing.

ALTER TABLE artwork_versions ADD COLUMN reference_type text NOT NULL DEFAULT 'layout'
  CHECK (reference_type IN ('layout', 'text'));

-- Word masters were always compared as continuous text; keep that for the versions still in use.
UPDATE artwork_versions a SET reference_type = 'text'
  FROM files f
 WHERE f.id = a.file_id AND f.doc_kind = 'docx' AND a.status IN ('draft', 'effective');

CREATE OR REPLACE FUNCTION cp_artwork_reference_type_fixed() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.reference_type IS DISTINCT FROM OLD.reference_type THEN
    RAISE EXCEPTION 'The reference type of artwork version % cannot be changed; register a new version', OLD.version
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER artwork_versions_reference_type BEFORE UPDATE ON artwork_versions
  FOR EACH ROW EXECUTE FUNCTION cp_artwork_reference_type_fixed();
