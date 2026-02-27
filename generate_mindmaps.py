from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

from parser import parse


def schema_txt_to_puml(schema_txt_path: Path, puml_path: Path, title: str | None = None) -> None:
    lines = schema_txt_path.read_text(encoding="utf-8").splitlines()
    puml_lines = ["@startmindmap"]

    if title:
        puml_lines.append(f"title {title}")

    for raw in lines:
        if not raw.strip():
            continue
        indent_spaces = len(raw) - len(raw.lstrip(" "))
        level = indent_spaces // 2
        stars = "*" * (level + 1)
        puml_lines.append(f"{stars} {raw.strip()}")

    puml_lines.append("@endmindmap")
    puml_path.write_text("\n".join(puml_lines) + "\n", encoding="utf-8")


def _plantuml_base_command() -> list[str]:
    brew_opt_roots = [Path("/usr/local/opt"), Path("/opt/homebrew/opt")]
    java_bin = shutil.which("java")
    for root in brew_opt_roots:
        plantuml_jar = root / "plantuml" / "libexec" / "plantuml.jar"
        batik_lib = root / "batik" / "libexec" / "lib"
        if java_bin and plantuml_jar.exists() and batik_lib.exists():
            return [
                java_bin,
                "-cp",
                f"{plantuml_jar}:{batik_lib}/*",
                "net.sourceforge.plantuml.Run",
            ]

    plantuml_bin = shutil.which("plantuml")
    if plantuml_bin:
        return [plantuml_bin]

    plantuml_jar = os.environ.get("PLANTUML_JAR")
    if plantuml_jar:
        return ["java", "-jar", plantuml_jar]

    raise RuntimeError(
        "PlantUML introuvable. Installez 'plantuml' ou définissez PLANTUML_JAR vers plantuml.jar"
    )


def render_pdf(puml_path: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"{puml_path.stem}.pdf"

    cmd_pdf = _plantuml_base_command() + ["-tpdf", "-o", str(out_dir), str(puml_path)]
    subprocess.run(cmd_pdf, check=True)

    if pdf_path.exists() and pdf_path.stat().st_size > 0:
        return pdf_path

    raise RuntimeError(
        f"PlantUML n'a pas produit un PDF valide pour {puml_path.name}. "
        "Vérifiez l'installation PlantUML/JRE (support PDF, ex. Batik)."
    )


def generate_one(
    schema_path: Path,
    root: str,
    ignored_keys_path: Path | None,
    schema_output_dir: Path,
    puml_output_dir: Path,
    pdf_output_dir: Path,
) -> tuple[Path, Path, Path]:
    schema_txt = Path(
        parse(
            input_path=str(schema_path),
            output_dir=str(schema_output_dir),
            root=root,
            ignored_keys_path=str(ignored_keys_path) if ignored_keys_path else None,
        )
    )

    puml_output_dir.mkdir(parents=True, exist_ok=True)
    puml_path = puml_output_dir / f"{root}.puml"
    schema_txt_to_puml(schema_txt, puml_path, title=f"{root} mindmap")
    pdf_path = render_pdf(puml_path, pdf_output_dir)
    return schema_txt, puml_path, pdf_path


def main() -> None:
    cli = argparse.ArgumentParser(
        description="Génère les mindmaps CAPEC/CWE puis lance PlantUML pour produire des PDF."
    )
    cli.add_argument("--base-dir", default=".", help="Racine du projet")
    cli.add_argument("--capec-schema", default="schemas/ap_schema_latest.xsd.xml")
    cli.add_argument("--cwe-schema", default="schemas/cwe_schema_latest.xsd.xml")
    cli.add_argument("--capec-ignored", default="capec_ignored_keys.txt")
    cli.add_argument("--cwe-ignored", default="cwe_ignored_keys.txt")
    cli.add_argument("--schema-out", default="generated/schemas")
    cli.add_argument("--puml-out", default="generated/puml")
    cli.add_argument("--pdf-out", default="generated/pdf")

    args = cli.parse_args()
    base_dir = Path(args.base_dir).resolve()

    capec_schema = (base_dir / args.capec_schema).resolve()
    cwe_schema = (base_dir / args.cwe_schema).resolve()
    capec_ignored = (base_dir / args.capec_ignored).resolve()
    cwe_ignored = (base_dir / args.cwe_ignored).resolve()

    schema_out = (base_dir / args.schema_out).resolve()
    puml_out = (base_dir / args.puml_out).resolve()
    pdf_out = (base_dir / args.pdf_out).resolve()

    try:
        capec_schema_txt, capec_puml, capec_pdf = generate_one(
            schema_path=capec_schema,
            root="attack_pattern",
            ignored_keys_path=capec_ignored if capec_ignored.exists() else None,
            schema_output_dir=schema_out,
            puml_output_dir=puml_out,
            pdf_output_dir=pdf_out,
        )

        cwe_schema_txt, cwe_puml, cwe_pdf = generate_one(
            schema_path=cwe_schema,
            root="weakness",
            ignored_keys_path=cwe_ignored if cwe_ignored.exists() else None,
            schema_output_dir=schema_out,
            puml_output_dir=puml_out,
            pdf_output_dir=pdf_out,
        )
    except subprocess.CalledProcessError as exc:
        print(f"Erreur PlantUML: commande échouée ({exc})", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print(f"Erreur: {exc}", file=sys.stderr)
        sys.exit(1)

    print("CAPEC")
    print(f"- schema: {capec_schema_txt}")
    print(f"- puml:   {capec_puml}")
    print(f"- pdf:    {capec_pdf}")
    print("CWE")
    print(f"- schema: {cwe_schema_txt}")
    print(f"- puml:   {cwe_puml}")
    print(f"- pdf:    {cwe_pdf}")


if __name__ == "__main__":
    main()
