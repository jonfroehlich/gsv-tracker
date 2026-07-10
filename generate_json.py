import logging
import os

from streetscape_metadata_tracker import get_default_data_dir
from streetscape_metadata_tracker.json_summarizer import (
    generate_aggregate_summary_as_json,
    generate_missing_city_json_files,
)

logger = logging.getLogger(__name__)


def main():
    """Command-line entry point for metadata generation."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate missing JSON metadata files for run data"
    )

    parser.add_argument(
        "--data-dir",
        type=str,
        default=get_default_data_dir(),
        help="Directory containing run metadata files (default: project data directory)",
    )

    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set the logging level (default: INFO)",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.debug(f"Input parameters: {args}")
    logger.debug(f"Logging level set to: {args.log_level}")
    logger.debug(f"Data directory: {args.data_dir}")

    if not os.path.exists(args.data_dir):
        print(f"Error: Directory {args.data_dir} does not exist")
        return 1

    generate_missing_city_json_files(args.data_dir)
    generate_aggregate_summary_as_json(args.data_dir)

    return 0


if __name__ == "__main__":
    main()
