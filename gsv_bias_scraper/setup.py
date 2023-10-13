from setuptools import setup, find_packages

setup(
    name='gsv_bias_scraper',
    version='1.0',
    packages=find_packages(),
    install_requires=[
        'numpy',
        'folium',
        'tqdm',
        'matplotlib',
        'pandas',
        'geopy',
        'asyncio',
        'httpx',
        'tenacity',
    ],
    entry_points={
        'console_scripts': [
            'gsv_bias_scraper = scraper:main'
        ]
    },
)
