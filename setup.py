import setuptools

setuptools.setup(
    name="psdelta",
    version="0.1.0",
    description="Manage processes and services based on snapshots (Process Delta Tool)",
    long_description=open("README.md", encoding="utf-8").read(),  # optional
    long_description_content_type="text/markdown",                # optional if using README.md
    author="Dustin Darcy",
    author_email="dustin@scarcityhypothesis.org",
    url="https://github.com/djdarcy/listall",   # or your repo link
    py_modules=["listall"],  # our script is 'listall.py'
    packages=setuptools.find_packages(),
    include_package_data=True,
    install_requires=[
        "psutil",
        "pywin32; platform_system=='Windows'"
    ],
    entry_points={
        "console_scripts": [
            "psdelta=psdelta.psdelta:main"
        ],
    },
    classifiers=[
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent"
    ],
    python_requires=">=3.6",
)
