from setuptools import find_packages, setup


setup(
    name="attack-knowledge-bases-mindmaps",
    version="0.1.0",
    description="Generate CAPEC/CWE pseudo-schemas and PlantUML mindmap PDFs from XSD schemas",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.10",
    entry_points={
        "console_scripts": [
            "akbm-parse=akbm.parser:main",
            "akbm-generate-mindmaps=akbm.generate_mindmaps:main",
        ]
    },
)
