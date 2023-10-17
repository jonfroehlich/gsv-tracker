from setuptools import setup, find_packages

setup(
    name='gsv-bias',
    version='1.0',
    entry_points={
        'console_scripts': [
            'scrape = scraper:main',
            'visualize = visualization:main',
        ]
    },
)
