#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
A tool for synchronizing data between Timewax and
Toggl timekeeping services.

Author: Jochem Bijlard
"""
import setuptools

import os
import re

VERSIONFILE=os.path.join('toggl_timewax', '__init__.py')
verstrline = open(VERSIONFILE, "rt").read()
VSRE = r"^__version__ = ['\"]([^'\"]*)['\"]"
mo = re.search(VSRE, verstrline, re.M)
if mo:
    version_string = mo.group(1)
else:
    raise RuntimeError("Unable to find version string in {}.".format(VERSIONFILE,))

with open("requirements.txt", 'r') as f:
    required_packages = f.read().splitlines()


setuptools.setup(
    name="toggl-timewax",
    version=version_string,
    url="https://www.github.com/jochemb/toggl-timewax/",

    author="Jochem Bijlard",
    author_email="j.bijlard@gmail.com",

    keywords=['toggl', 'timewax'],

    download_url='https://github.com/jochemb/toggl-timewax/tarball/{}/'.format(version_string),

    install_requires=required_packages,

    entry_points={
        'console_scripts': [
            'toggl-timewax = toggl_timewax.cli:cli'
        ]
    },

    classifiers=[
        'Programming Language :: Python',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
    ],
)