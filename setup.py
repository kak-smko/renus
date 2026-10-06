from setuptools import Extension, setup
from Cython.Build import cythonize


setup(
    ext_modules=cythonize(
        [Extension("renus._speedup", ["renus/_speedup.pyx"])],
    ),
)
