from setuptools import setup, find_packages

setup(
    name='renus',
    version='2.0.5',
    description='Renus Core Framework',
    url='https://github.com/smkoBa/renus',
    author='Smko Bayazidi',
    author_email='ba.smko@gmail.com',
    license='BSD',
    packages=find_packages(),
    include_package_data=True,
    python_requires=">=3.8",
    install_requires=['anyio', 'python-multipart', 'pymongo', 'requests', 'setuptools']
)
