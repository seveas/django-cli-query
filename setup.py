import os
from setuptools import setup, find_packages
 
setup(name='django-cli-query',
    version="1.1",
    description='Management command for commandline querying',
    author='Dennis Kaarsemaker',
    author_email='dennis@kaarsemaker.net',
    url='http://github.com/seveas/django-cli-query',
    packages=find_packages(),
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Framework :: Django",
        "Intended Audience :: Developers",
        "Operating System :: OS Independent",
        "Topic :: Software Development"
    ],
)
