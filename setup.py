#!/usr/bin/env python
# -*- coding: utf-8 -*-
import re

from os.path import join
from setuptools import setup, find_packages

RE_REQUIREMENT = re.compile(r'^\s*-r\s*(?P<filename>.*)$')


def pip(filename):
    '''Parse pip requirement file and transform it to setuptools requirements'''
    requirements = []
    for line in open(join('requirements', filename)).readlines():
        match = RE_REQUIREMENT.match(line)
        if match:
            requirements.extend(pip(match.group('filename')))
        else:
            requirements.append(line)
    return requirements


setup(
    name='djangotables',
    version='1.1',
    description='Django + Datatables',
    url='https://github.com/c475/djangotables',
    author='Cobras',
    packages=find_packages(),
    include_package_data=True,
    install_requires=pip('install.pip'),
    use_2to3=True,
    zip_safe=False
)
