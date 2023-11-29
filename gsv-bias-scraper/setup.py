from setuptools import setup

setup(
    name='gsv-bias-scraper',
    version='1.1',
    entry_points={
        'console_scripts': [
            'gsv_metadata_scrape = gsv_metadata_scraper:main',
            'gsv_visualize = gsv_visualizer:main',
            'gsv_historic_dates_scrape = gsv_historic_dates_scraper:main',
        ]
    },
)
