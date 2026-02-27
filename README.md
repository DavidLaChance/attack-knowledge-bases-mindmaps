# attack-knowledge-bases-mindmaps

Generate CAPEC/CWE pseudo-schemas and PDF mindmaps from XSD files.

## Structure

```text
.
├── parser.py
├── generate_mindmaps.py
├── schemas/
│   ├── ap_schema_latest.xsd.xml
│   └── cwe_schema_latest.xsd.xml
├── generated/
│   ├── schemas/
│   ├── puml/
│   └── pdf/
├── capec_ignored_keys.txt
└── cwe_ignored_keys.txt
```

## Usage

### Generate a single pseudo-schema

```bash
python parser.py \
  --schema schemas/ap_schema_latest.xsd.xml \
  --root attack_pattern \
  --output-dir generated/schemas \
  --ignored-keys capec_ignored_keys.txt
```

### Generate CAPEC + CWE + PDFs

```bash
python generate_mindmaps.py
```

Outputs:
- `generated/schemas/*.schema.txt`
- `generated/puml/*.puml`
- `generated/pdf/*.pdf`

## PlantUML Note

PDF generation is intentionally strict: only one direct PlantUML -> PDF conversion.
If PDF generation fails, fix the Java/PlantUML/Batik installation.