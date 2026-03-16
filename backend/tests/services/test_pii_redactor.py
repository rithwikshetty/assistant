from app.services.pii_redactor import UserRedactionPatterns


def test_redacts_term_inside_underscore_delimited_token() -> None:
    text = "ProjC_Education_2023.xlsx"

    redacted, hits = UserRedactionPatterns.redact(text, ["Education"])

    assert redacted == "ProjC_[REDACTED NAME]_2023.xlsx"
    assert hits == ["Education"]


def test_redacts_multi_part_name_across_common_separators() -> None:
    text = "john_smith john-smith john.smith smith_john"

    redacted, hits = UserRedactionPatterns.redact(text, ["John Smith"])

    assert redacted == "[REDACTED NAME] [REDACTED NAME] [REDACTED NAME] [REDACTED NAME]"
    assert hits == ["John Smith"]


def test_does_not_redact_embedded_substring_in_larger_word() -> None:
    text = "coeducation reeducation educational"

    redacted, hits = UserRedactionPatterns.redact(text, ["Education"])

    assert redacted == text
    assert hits == []
