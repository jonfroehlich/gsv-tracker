"""
Filename conventions for GSV metadata files.

This module is the single source of truth for generating and parsing the
data filenames used throughout the project. Three filename generations
exist on disk and all must parse:

1. Legacy (undated):        seattle--wa_width_1000_height_1000_step_20.csv.gz
2. Legacy (buggy float):    seattle--wa_width_1000_height_1000_step_20.0.csv.gz
3. Dated runs (current):    seattle--washington--united-states_width_1000_height_1000_step_20_2026-07-02.csv.gz

New files always use form 3: integer dimensions plus an ISO run date, so a
city can accumulate multiple dated snapshots over time.
"""

import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

# Accepts int or float numeric groups and an optional trailing ISO run date.
FILENAME_RE = re.compile(
    r'^(?P<slug>.+?)'
    r'_width_(?P<w>\d+(?:\.\d+)?)'
    r'_height_(?P<h>\d+(?:\.\d+)?)'
    r'_step_(?P<s>\d+(?:\.\d+)?)'
    r'(?:_(?P<date>\d{4}-\d{2}-\d{2}))?$'
)

# Extensions stripped before parsing, longest first.
_KNOWN_EXTENSIONS = ('.csv.gz', '.json.gz', '.csv', '.json', '.html')


@dataclass(frozen=True)
class ParsedFilename:
    """Components extracted from a GSV metadata filename."""
    slug: str                    # sanitized location slug, e.g. 'grand-marais--mn'
    city_query_str: str          # human-readable reconstruction, e.g. 'Grand Marais, MN'
    width_meters: int
    height_meters: int
    step_meters: int
    run_date: Optional[date]     # None for legacy undated files


def sanitize_city_query_str(city_query_str: str) -> str:
    r"""
    Sanitize a city query string for use in filenames.

    Uses single dash (-) for spaces within location components and
    double dash (--) to separate location components (city, state, country).

    Handles problematic characters across Windows, macOS, and Linux:
    - Replaces spaces with single dashes
    - Uses double dashes to separate location components (e.g., city--state--country)
    - Removes characters that are invalid on Windows (< > : " / \ | ? *)
    - Removes any leading/trailing periods
    - Converts to lowercase

    Args:
        city_query_str: Query string that may contain city, state, and/or country.

    Returns:
        Sanitized string safe for filenames

    Examples:
        >>> sanitize_city_query_str("St. Louis, MO, USA")
        'st.-louis--mo--usa'
        >>> sanitize_city_query_str("Grand Marais, MN")
        'grand-marais--mn'
        >>> sanitize_city_query_str("Grand Marais")
        'grand-marais'

    Note: interior periods are preserved (only leading/trailing ones are
    stripped) — this matches the slugs of all previously collected data
    files, so it must not change.
    """
    parts = [p.strip() for p in city_query_str.split(',')]

    cleaned_parts = []
    for part in parts:
        # \s (not ' ') so Unicode whitespace like the non-breaking spaces
        # Nominatim sometimes returns (e.g. "Ann\xa0Arbor") is normalized too
        cleaned = re.sub(r'\s', '-', part)
        cleaned = re.sub(r'[<>:"/\\|?*]', '', cleaned)
        cleaned = cleaned.strip('.-')
        cleaned = cleaned.lower()
        cleaned_parts.append(cleaned)

    return '--'.join(cleaned_parts)


def slug_to_query_str(slug: str) -> str:
    """
    Reconstruct a human-readable query string from a sanitized slug.

    >>> slug_to_query_str("grand-marais--mn--usa")
    'Grand Marais, Mn, Usa'
    """
    processed_parts = []
    for part in slug.split('--'):
        words = part.split('-')
        processed_parts.append(' '.join(word.capitalize() for word in words))
    return ', '.join(processed_parts)


def parse_filename(filename: str) -> ParsedFilename:
    """
    Parse a GSV metadata filename to extract its parameters.

    Accepts all filename generations: legacy undated names with integer or
    float-formatted numbers (an old bug wrote `_step_20.0`), and current
    dated names with a trailing `_YYYY-MM-DD` run date.

    Args:
        filename: Name or path of the data file (any known extension)

    Returns:
        ParsedFilename with slug, reconstructed query string, integer
        dimensions, and run_date (None for legacy undated files).

    Raises:
        ValueError: If the filename doesn't match the expected format

    Examples:
        >>> p = parse_filename("grand-marais--mn_width_1000_height_1000_step_20.csv.gz")
        >>> (p.city_query_str, p.width_meters, p.run_date)
        ('Grand Marais, Mn', 1000, None)
        >>> p = parse_filename("bend--or_width_5000_height_5000_step_20.0_2026-07-02.csv.gz")
        >>> (p.step_meters, p.run_date.isoformat())
        (20, '2026-07-02')
    """
    base = os.path.basename(filename)
    for ext in _KNOWN_EXTENSIONS:
        if base.endswith(ext):
            base = base[:-len(ext)]
            break

    match = FILENAME_RE.match(base)
    if not match:
        raise ValueError(f"Filename {filename} doesn't match expected format")

    run_date = None
    if match.group('date'):
        run_date = date.fromisoformat(match.group('date'))

    slug = match.group('slug')
    return ParsedFilename(
        slug=slug,
        city_query_str=slug_to_query_str(slug),
        width_meters=int(float(match.group('w'))),
        height_meters=int(float(match.group('h'))),
        step_meters=int(float(match.group('s'))),
        run_date=run_date,
    )


def generate_base_filename(
    city_query_str: str,
    grid_width: float,
    grid_height: float,
    step_length: float
) -> str:
    """
    Generate a legacy (undated) base filename for GSV metadata files.

    Used only for locating pre-existing undated files; new downloads should
    use generate_run_filename() which appends the run date.

    Examples:
        >>> generate_base_filename("St. Louis, MO, USA", 1000, 1000, 20)
        'st-louis--mo--usa_width_1000_height_1000_step_20'
    """
    safe_name = sanitize_city_query_str(city_query_str)
    return f"{safe_name}_width_{int(grid_width)}_height_{int(grid_height)}_step_{int(step_length)}"


def generate_run_filename(
    city_id: str,
    grid_width: float,
    grid_height: float,
    step_length: float,
    run_date: date
) -> str:
    """
    Generate the dated base filename (no extension) for a collection run.

    Args:
        city_id: canonical sanitized city slug (see db.register_city)
        grid_width/grid_height/step_length: grid geometry in meters
        run_date: the run's date, embedded as an ISO suffix

    Examples:
        >>> from datetime import date
        >>> generate_run_filename("bend--oregon--united-states", 5000, 5000, 20, date(2026, 7, 2))
        'bend--oregon--united-states_width_5000_height_5000_step_20_2026-07-02'
    """
    return (f"{city_id}_width_{int(grid_width)}_height_{int(grid_height)}"
            f"_step_{int(step_length)}_{run_date.isoformat()}")
