#!/usr/bin/env python3
"""Check that ArchToolkit's release identity is internally consistent.

The checker intentionally uses only the Python standard library so it can run
before CI installs development dependencies.
"""

from __future__ import annotations

import argparse
import configparser
import re
import sys
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse


SEMVER_RE = re.compile(r"\d+\.\d+\.\d+\Z")
ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
ALLOWED_QGIS_CATEGORIES = {"Raster", "Vector", "Database", "Mesh", "Web"}


class _BadgeParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.badges: Dict[str, List[Tuple[str, str]]] = {
            "Version": [],
            "Status": [],
            "License": [],
        }

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "img":
            return
        values = dict(attrs)
        alt = str(values.get("alt") or "")
        src = str(values.get("src") or "")
        for label in self.badges:
            if alt.startswith(label + " "):
                self.badges[label].append((alt[len(label) + 1:].strip(), src))


def _strict_bool(value: str, label: str, errors: List[str]) -> Optional[bool]:
    normalized = str(value or "").strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    errors.append(f"metadata.txt {label} must be exactly true or false")
    return None


def _strip_yaml_comment(value: str) -> str:
    quote = ""
    escaped = False
    for index, character in enumerate(value):
        if quote:
            if quote == '"' and character == "\\" and not escaped:
                escaped = True
                continue
            if character == quote and not escaped:
                quote = ""
            escaped = False
            continue
        if character in "\"'":
            quote = character
        elif character == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    return value.strip()


def _top_level_cff_scalars(text: str, errors: List[str]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for line in text.splitlines():
        if not line or line[0].isspace() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = _strip_yaml_comment(raw_value.strip())
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key in values:
            errors.append(f"CITATION.cff contains duplicate top-level key {key!r}")
            continue
        values[key] = value
    return values


def _one_badge(parser: _BadgeParser, label: str, errors: List[str]) -> Tuple[str, str]:
    found = parser.badges[label]
    if len(found) != 1:
        errors.append(f"README.md must contain exactly one {label} badge; found {len(found)}")
        return "", ""
    return found[0]


def _shield_value(value: str) -> str:
    return str(value).replace("-", "--").replace("_", "__")


def _read_text(path: Path, label: str, errors: List[str]) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        errors.append(f"{label} could not be read as UTF-8: {exc}")
        return None


def _is_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and not any(
        character.isspace() for character in value
    )


def _parse_iso_date(value: str, label: str, errors: List[str]) -> Optional[date]:
    if ISO_DATE_RE.fullmatch(value) is None:
        errors.append(f"{label} must use YYYY-MM-DD syntax; found {value!r}")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append(f"{label} is not a valid calendar date: {value!r}")
        return None


def _bibtex_entry(text: str, start: int) -> Tuple[str, bool]:
    """Return one brace-balanced BibTeX entry starting at ``@software``."""
    opening = text.find("{", start)
    if opening < 0:
        return text[start:], False
    depth = 0
    for index in range(opening, len(text)):
        character = text[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1], True
    return text[start:], False


def _archtoolkit_bibtex_entries(blocks: List[str]) -> List[Tuple[str, bool]]:
    start_re = re.compile(
        r"@software\s*\{\s*ArchToolkit[A-Za-z0-9_.:-]*\s*,",
        re.IGNORECASE,
    )
    entries: List[Tuple[str, bool]] = []
    for block in blocks:
        for match in start_re.finditer(block):
            entries.append(_bibtex_entry(block, match.start()))
    return entries


def _metadata(root: Path, errors: List[str]):
    path = root / "metadata.txt"
    if not path.is_file():
        errors.append("metadata.txt is missing")
        return None
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(path.read_text(encoding="utf-8-sig"))
        return parser["general"]
    except Exception as exc:
        errors.append(f"metadata.txt could not be parsed: {exc}")
        return None


def validate(
    repo_root: Path,
    release_tag: Optional[str] = None,
    release_date: Optional[str] = None,
) -> List[str]:
    """Return deterministic, human-readable release consistency errors."""
    root = Path(repo_root)
    errors: List[str] = []
    general = _metadata(root, errors)
    readme = _read_text(root / "README.md", "README.md", errors)
    citation_text = _read_text(root / "CITATION.cff", "CITATION.cff", errors)
    if general is None or readme is None or citation_text is None:
        return errors

    required_keys = (
        "version", "experimental", "deprecated", "repository",
        "tracker", "homepage", "license", "changelog",
    )
    for key in required_keys:
        if not str(general.get(key, "")).strip():
            errors.append(f"metadata.txt [general] {key} is missing")

    version = str(general.get("version", "")).strip()
    if version and SEMVER_RE.fullmatch(version) is None:
        errors.append(f"metadata.txt version must use X.Y.Z syntax; found {version!r}")
    repository = str(general.get("repository", "")).strip().rstrip("/")
    tracker = str(general.get("tracker", "")).strip().rstrip("/")
    homepage = str(general.get("homepage", "")).strip().rstrip("/")
    category = str(general.get("category", "")).strip()
    license_id = str(general.get("license", "")).strip()
    experimental = _strict_bool(general.get("experimental", ""), "experimental", errors)
    deprecated = _strict_bool(general.get("deprecated", ""), "deprecated", errors)

    expected_status = ""
    if deprecated is True:
        expected_status = "deprecated"
    elif experimental is True:
        expected_status = "experimental"
    elif deprecated is False and experimental is False:
        expected_status = "stable"

    for label, value in (
        ("repository", repository),
        ("tracker", tracker),
        ("homepage", homepage),
    ):
        if value and not _is_http_url(value):
            errors.append(f"metadata.txt {label} must be an absolute HTTP(S) URL")
    if category and category not in ALLOWED_QGIS_CATEGORIES:
        allowed = ", ".join(sorted(ALLOWED_QGIS_CATEGORIES))
        errors.append(f"metadata.txt category is {category!r}; allowed values are {allowed}")

    badge_parser = _BadgeParser()
    badge_parser.feed(readme)
    badge_version, badge_version_src = _one_badge(badge_parser, "Version", errors)
    badge_status, badge_status_src = _one_badge(badge_parser, "Status", errors)
    badge_license, badge_license_src = _one_badge(badge_parser, "License", errors)

    if version and badge_version and badge_version != version:
        errors.append(f"README.md Version badge is {badge_version!r}; expected {version!r}")
    if version and badge_version_src and f"/badge/version-{_shield_value(version)}-" not in badge_version_src:
        errors.append("README.md Version badge URL does not match metadata.txt version")
    if expected_status and badge_status.lower() != expected_status:
        errors.append(f"README.md Status badge is {badge_status!r}; expected {expected_status!r}")
    if expected_status and badge_status_src and f"/badge/status-{_shield_value(expected_status)}-" not in badge_status_src:
        errors.append("README.md Status badge URL does not match metadata.txt status flags")
    if license_id and badge_license != license_id:
        errors.append(f"README.md License badge is {badge_license!r}; expected {license_id!r}")
    if license_id and badge_license_src and f"/badge/license-{_shield_value(license_id)}-" not in badge_license_src:
        errors.append("README.md License badge URL does not match metadata.txt license")

    bib_blocks = re.findall(r"```bibtex\s*(.*?)```", readme, re.DOTALL | re.IGNORECASE)
    archtoolkit_bib_entries = _archtoolkit_bibtex_entries(bib_blocks)
    if len(archtoolkit_bib_entries) != 1:
        errors.append(
            "README.md must contain exactly one ArchToolkit @software BibTeX entry; "
            f"found {len(archtoolkit_bib_entries)}"
        )
        bib_text = ""
    else:
        bib_text, complete_bib_entry = archtoolkit_bib_entries[0]
        if not complete_bib_entry:
            errors.append("README.md ArchToolkit BibTeX entry has unbalanced braces")
    bib_version_match = re.search(r"(?m)^\s*version\s*=\s*\{([^}]+)\}", bib_text)
    bib_url_match = re.search(r"(?m)^\s*url\s*=\s*\{([^}]+)\}", bib_text)
    bib_version = bib_version_match.group(1).strip() if bib_version_match else ""
    bib_url = bib_url_match.group(1).strip().rstrip("/") if bib_url_match else ""
    if not bib_version:
        errors.append("README.md BibTeX version is missing")
    elif version and bib_version != version:
        errors.append(f"README.md BibTeX version is {bib_version!r}; expected {version!r}")
    if not bib_url:
        errors.append("README.md BibTeX URL is missing")
    elif repository and bib_url != repository:
        errors.append(f"README.md BibTeX URL is {bib_url!r}; expected {repository!r}")

    cff = _top_level_cff_scalars(citation_text, errors)
    cff_version = cff.get("version", "")
    cff_repository = cff.get("repository-code", "").rstrip("/")
    cff_url = cff.get("url", "").rstrip("/")
    cff_license = cff.get("license", "")
    if not cff_version:
        errors.append("CITATION.cff top-level version is missing")
    elif version and cff_version != version:
        errors.append(f"CITATION.cff version is {cff_version!r}; expected {version!r}")
    if repository and cff_repository != repository:
        errors.append(f"CITATION.cff repository-code is {cff_repository!r}; expected {repository!r}")
    if homepage and cff_url != homepage:
        errors.append(f"CITATION.cff url is {cff_url!r}; expected {homepage!r}")
    if license_id and cff_license != license_id:
        errors.append(f"CITATION.cff license is {cff_license!r}; expected {license_id!r}")

    cff_release_date = cff.get("date-released", "")
    parsed_cff_date = None
    if cff_release_date:
        parsed_cff_date = _parse_iso_date(
            cff_release_date,
            "CITATION.cff date-released",
            errors,
        )
        # CFF dates have no timezone. A release calendar date can legitimately
        # be one day ahead of a UTC CI runner (e.g. Asia/Seoul or UTC+14).
        if parsed_cff_date is not None and parsed_cff_date > date.today() + timedelta(days=1):
            errors.append("CITATION.cff date-released is too far in the future")
    if release_tag:
        expected_tag = f"v{version}" if version else ""
        if release_tag != expected_tag:
            errors.append(f"release tag is {release_tag!r}; expected {expected_tag!r}")
        if not cff_release_date:
            errors.append("CITATION.cff date-released is required for a release tag")
        if not release_date:
            errors.append("--release-date is required with --release-tag")
        else:
            _parse_iso_date(release_date, "release tag date", errors)
            if cff_release_date and cff_release_date != release_date:
                errors.append(
                    f"CITATION.cff date-released is {cff_release_date!r}; "
                    f"expected release tag date {release_date!r}"
                )

    changelog = str(general.get("changelog", "")).lstrip()
    if version and re.match(rf"{re.escape(version)}(?:\s|[-–—:]|$)", changelog) is None:
        errors.append(f"metadata.txt changelog must start with current version {version!r}")

    return errors


def main(argv=None) -> int:
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=default_root, help="repository root")
    parser.add_argument("--release-tag", help="optional tag, for example v0.2.0")
    parser.add_argument("--release-date", help="tag date in YYYY-MM-DD form")
    args = parser.parse_args(argv)
    errors = validate(
        args.root,
        release_tag=args.release_tag,
        release_date=args.release_date,
    )
    if errors:
        print("[release-identity] FAILED")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("[release-identity] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
