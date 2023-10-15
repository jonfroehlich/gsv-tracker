from setuptools import setup, find_packages

setup(
    name='gsv-bias-scraper',
    version='1.0',
    packages=find_packages(),
    install_requires=[
        'numpy',
        'folium',
        'tqdm',
        'matplotlib',
        'pandas',
        'geopy',
        'httpx',
        'tenacity',
        'asyncio'
    ],
    entry_points={
        'console_scripts': [
            'gsv-bias-scraper = scraper:main'
        ]
    },
)
