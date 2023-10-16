from setuptools import setup, find_packages

setup(
    name='gsv-bias',
    version='1.0',
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'gsv-metadata-scraper = gsv-metadata-scraper:main',
            'visualize = visualization:main'
        ]
    },
)