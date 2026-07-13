"""
Cython build script for production deployment. v2.0.0

Compiles all .py files in src/ to .so shared objects.
Usage: python exportApp.py build_ext --inplace
"""

from setuptools import setup
from Cython.Build import cythonize
import os

src_files = []
for root, dirs, files in os.walk("src"):
    for f in files:
        if f.endswith(".py") and f != "__init__.py":
            src_files.append(os.path.join(root, f))

setup(
    name="meter-app-v2",
    version="2.0.0",
    ext_modules=cythonize(src_files, compiler_directives={'language_level': "3"}),
)
