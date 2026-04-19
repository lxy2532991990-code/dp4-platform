from setuptools import find_packages, setup


setup(
    name="dp4_platform",
    version="0.1.0",
    description="Standalone ORCA/Gaussian DP4-style workflow platform",
    packages=find_packages(),
    include_package_data=True,
    package_data={"dp4_platform": ["data/*.json"]},
    install_requires=[
        "numpy>=1.20",
        "PyQt6>=6.5",
        "pyvista>=0.43",
        "pyvistaqt>=0.11",
    ],
    entry_points={
        "console_scripts": [
            "dp4-platform=dp4_platform.cli:main",
            "dp4-platform-gui=dp4_platform.gui:main",
        ]
    },
    python_requires=">=3.10,<3.15",
)
