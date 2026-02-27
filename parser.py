from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET


XSD_NS = "{http://www.w3.org/2001/XMLSchema}"


@dataclass
class Expr:
    kind: str
    value: object


@dataclass
class Field:
    name: str
    expr: Expr


def _snake_case(name: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z]+", "_", name)
    cleaned = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", cleaned)
    return cleaned.strip("_").lower()


def _strip_ns(tag_or_type: str) -> str:
    if not tag_or_type:
        return ""
    if "}" in tag_or_type:
        return tag_or_type.split("}", 1)[1]
    if ":" in tag_or_type:
        return tag_or_type.split(":", 1)[1]
    return tag_or_type


def _read_ignored_keys(ignored_keys_path: str | None) -> set[str]:
    if not ignored_keys_path:
        return set()
    path = Path(ignored_keys_path)
    if not path.exists():
        return set()
    ignored: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        ignored.add(_snake_case(line))
    return ignored


class XSDSchemaCompiler:
    def __init__(self, schema_path: str, ignored_keys: Iterable[str] | None = None):
        self.schema_path = Path(schema_path)
        self.tree = self._load_tree(self.schema_path)
        self.root = self.tree.getroot()
        self.simple_types: dict[str, ET.Element] = {}
        self.complex_types: dict[str, ET.Element] = {}
        self.global_elements: dict[str, ET.Element] = {}
        self.ignored_keys = set(ignored_keys or ())
        self._index_schema()

    def _load_tree(self, schema_path: Path) -> ET.ElementTree:
        try:
            return ET.parse(schema_path)
        except ET.ParseError:
            raw = schema_path.read_text(encoding="utf-8")
            sanitized = re.sub(r"<x/[^>]*:documentation>", "<xs:documentation>", raw)
            sanitized = re.sub(r"</x/[^>]*:documentation>", "</xs:documentation>", sanitized)
            root = ET.fromstring(sanitized)
            return ET.ElementTree(root)

    def _index_schema(self) -> None:
        for child in self.root:
            local = _strip_ns(child.tag)
            name = child.get("name")
            if not name:
                continue
            if local == "simpleType":
                self.simple_types[name] = child
            elif local == "complexType":
                self.complex_types[name] = child
            elif local == "element":
                self.global_elements[name] = child

    def _builtin_scalar(self, xsd_type: str) -> str:
        t = _strip_ns(xsd_type)
        mapping = {
            "string": "string",
            "token": "string",
            "normalizedString": "string",
            "integer": "int",
            "int": "int",
            "long": "int",
            "short": "int",
            "nonNegativeInteger": "int",
            "positiveInteger": "int",
            "boolean": "bool",
            "date": "date",
            "gYear": "string",
            "gMonth": "string",
            "gDay": "string",
            "anyURI": "string",
            "decimal": "float",
            "double": "float",
            "float": "float",
        }
        return mapping.get(t, "string")

    def _enum_values_from_simple_type(self, node: ET.Element) -> list[str]:
        restriction = node.find(f"{XSD_NS}restriction")
        if restriction is None:
            return []
        values: list[str] = []
        for enum_node in restriction.findall(f"{XSD_NS}enumeration"):
            value = enum_node.get("value")
            if value is not None:
                values.append(value)
        return values

    def _expr_for_simple_type(self, node: ET.Element) -> Expr:
        enums = self._enum_values_from_simple_type(node)
        if enums:
            quoted = ", ".join(f'"{v}"' for v in enums)
            return Expr("scalar", f"enum({quoted})")
        restriction = node.find(f"{XSD_NS}restriction")
        if restriction is not None and restriction.get("base"):
            return Expr("scalar", self._builtin_scalar(restriction.get("base", "xs:string")))
        return Expr("scalar", "string")

    def _base_value_name(self, base_scalar: str, context_name: str) -> str:
        ctx = context_name.lower()
        if "name" in ctx and base_scalar == "string":
            return "name"
        if ctx in {"skill"}:
            return "value"
        if base_scalar == "structured_text":
            return "text" if ctx in {"technique"} else "content"
        return "value"

    def _expr_for_type_name(self, type_name: str, context_name: str = "") -> Expr:
        local = _strip_ns(type_name)
        if type_name.startswith("xs:") or local in {
            "string",
            "integer",
            "int",
            "long",
            "short",
            "nonNegativeInteger",
            "positiveInteger",
            "boolean",
            "date",
            "gYear",
            "gMonth",
            "gDay",
            "anyURI",
            "decimal",
            "double",
            "float",
            "token",
            "normalizedString",
        }:
            return Expr("scalar", self._builtin_scalar(type_name))

        if local == "StructuredTextType":
            return Expr("scalar", "structured_text")

        if local in self.simple_types:
            return self._expr_for_simple_type(self.simple_types[local])

        if local in self.complex_types:
            return self._expr_for_complex_type(self.complex_types[local], context_name=context_name)

        return Expr("scalar", "string")

    def _attribute_to_field(self, attr: ET.Element) -> Field:
        name = _snake_case(attr.get("name", "attribute"))
        attr_type = attr.get("type")
        inline_simple = attr.find(f"{XSD_NS}simpleType")
        if attr_type:
            expr = self._expr_for_type_name(attr_type, context_name=name)
        elif inline_simple is not None:
            expr = self._expr_for_simple_type(inline_simple)
        else:
            expr = Expr("scalar", "string")

        required = attr.get("use") == "required"
        if not required:
            expr = Expr("optional", expr)
        return Field(name, expr)

    def _element_occurs_wrapped(self, expr: Expr, node: ET.Element) -> Expr:
        min_occurs = node.get("minOccurs", "1")
        max_occurs = node.get("maxOccurs", "1")

        if max_occurs != "1":
            expr = Expr("list", expr)
        if min_occurs == "0":
            expr = Expr("optional", expr)
        return expr

    def _expr_for_element_content(self, node: ET.Element) -> Expr:
        element_name = _snake_case(node.get("name", "item"))
        element_type = node.get("type")
        if element_type:
            return self._expr_for_type_name(element_type, context_name=element_name)

        inline_simple = node.find(f"{XSD_NS}simpleType")
        if inline_simple is not None:
            return self._expr_for_simple_type(inline_simple)

        inline_complex = node.find(f"{XSD_NS}complexType")
        if inline_complex is not None:
            return self._expr_for_complex_type(inline_complex, context_name=element_name)

        return Expr("scalar", "string")

    def _element_to_field(self, node: ET.Element) -> Field:
        name = _snake_case(node.get("name", "item"))
        expr = self._expr_for_element_content(node)
        expr = self._element_occurs_wrapped(expr, node)
        return Field(name, expr)

    def _expr_for_complex_type(self, node: ET.Element, context_name: str = "") -> Expr:
        complex_content = node.find(f"{XSD_NS}complexContent")
        if complex_content is not None:
            extension = complex_content.find(f"{XSD_NS}extension")
            if extension is not None:
                base = extension.get("base", "xs:string")
                base_expr = self._expr_for_type_name(base, context_name=context_name)
                if base_expr.kind == "scalar":
                    base_field_name = self._base_value_name(str(base_expr.value), context_name)
                    fields = [Field(base_field_name, base_expr)]
                else:
                    fields = [Field("value", base_expr)]
                for attr in extension.findall(f"{XSD_NS}attribute"):
                    fields.append(self._attribute_to_field(attr))
                return Expr("object", self._filter_fields(fields))

        simple_content = node.find(f"{XSD_NS}simpleContent")
        if simple_content is not None:
            extension = simple_content.find(f"{XSD_NS}extension")
            if extension is not None:
                base = extension.get("base", "xs:string")
                base_expr = self._expr_for_type_name(base, context_name=context_name)
                if base_expr.kind == "scalar":
                    base_field_name = self._base_value_name(str(base_expr.value), context_name)
                    fields = [Field(base_field_name, base_expr)]
                else:
                    fields = [Field("value", base_expr)]
                for attr in extension.findall(f"{XSD_NS}attribute"):
                    fields.append(self._attribute_to_field(attr))
                return Expr("object", self._filter_fields(fields))

        fields: list[Field] = []
        sequence = node.find(f"{XSD_NS}sequence")
        if sequence is not None:
            elements = sequence.findall(f"{XSD_NS}element")
            if len(elements) == 1 and not node.findall(f"{XSD_NS}attribute"):
                child = elements[0]
                child_min = child.get("minOccurs", "1")
                child_max = child.get("maxOccurs", "1")
                if child_min == "1" and child_max != "1":
                    child_expr = self._expr_for_element_content(child)
                    return Expr("list", child_expr)

            for element in elements:
                fields.append(self._element_to_field(element))

        for attr in node.findall(f"{XSD_NS}attribute"):
            fields.append(self._attribute_to_field(attr))

        return Expr("object", self._filter_fields(fields))

    def _filter_fields(self, fields: list[Field]) -> list[Field]:
        return [f for f in fields if f.name not in self.ignored_keys]

    def compile_root(self, root_identifier: str) -> tuple[str, Expr]:
        aliases = {
            "attack_pattern": "AttackPatternType",
            "weakness": "WeaknessType",
            "attack_pattern_catalog": "Attack_Pattern_Catalog",
            "weakness_catalog": "Weakness_Catalog",
        }

        lookup = root_identifier
        if root_identifier in aliases:
            lookup = aliases[root_identifier]

        if lookup in self.global_elements:
            root_element = self.global_elements[lookup]
            expr = self._expr_for_element_content(root_element)
            name = _snake_case(root_identifier)
            return name, expr

        if lookup in self.complex_types:
            expr = self._expr_for_complex_type(self.complex_types[lookup], context_name=lookup)
            name = _snake_case(root_identifier)
            return name, expr

        raise ValueError(f"Root '{root_identifier}' introuvable dans le schéma: {self.schema_path}")

    def _render_expr(self, expr: Expr, indent: int) -> list[str]:
        pad = "  " * indent
        if expr.kind == "scalar":
            return [pad + str(expr.value)]

        if expr.kind == "object":
            lines: list[str] = []
            for field in expr.value:  # type: ignore[union-attr]
                lines.extend(self._render_field(field, indent))
            return lines or [pad + "{}"]

        if expr.kind == "list":
            inner: Expr = expr.value  # type: ignore[assignment]
            if inner.kind == "scalar":
                return [pad + f"list<{inner.value}>"]
            lines = [pad + "list<"]
            lines.extend(self._render_expr(inner, indent + 1))
            lines.append(pad + ">")
            return lines

        if expr.kind == "optional":
            inner = expr.value  # type: ignore[assignment]
            if inner.kind == "scalar":
                return [pad + f"optional<{inner.value}>"]
            lines = [pad + "optional<"]
            lines.extend(self._render_expr(inner, indent + 1))
            lines.append(pad + ">")
            return lines

        return [pad + "string"]

    def _render_field(self, field: Field, indent: int) -> list[str]:
        pad = "  " * indent
        expr = field.expr
        if expr.kind == "object":
            lines = [pad + f"{field.name}:"]
            lines.extend(self._render_expr(expr, indent + 1))
            return lines

        rendered = self._render_expr(expr, indent)
        first = rendered[0][len(pad):] if rendered else "string"
        lines = [pad + f"{field.name}: {first}"]
        if len(rendered) > 1:
            lines.extend(rendered[1:])
        return lines

    def render(self, root_name: str, expr: Expr) -> str:
        if expr.kind == "object":
            lines = [f"{root_name}:"]
            lines.extend(self._render_expr(expr, 1))
            return "\n".join(lines) + "\n"

        rendered = self._render_expr(expr, 0)
        first = rendered[0] if rendered else "string"
        lines = [f"{root_name}: {first}"]
        lines.extend(rendered[1:])
        return "\n".join(lines) + "\n"


def parse(input_path: str, output_dir: str, root: str, ignored_keys_path=None):
    ignored_keys = _read_ignored_keys(ignored_keys_path)
    compiler = XSDSchemaCompiler(input_path, ignored_keys=ignored_keys)
    root_name, expr = compiler.compile_root(root)
    rendered = compiler.render(root_name, expr)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_file = out_dir / f"{root_name}.schema.txt"
    output_file.write_text(rendered, encoding="utf-8")
    return str(output_file)


def main() -> None:
    cli = argparse.ArgumentParser(description="Compile un schéma XSD en pseudo-langage.")
    cli.add_argument("--schema", required=True, help="Chemin du fichier XSD")
    cli.add_argument("--root", required=True, help="Nom logique du type racine (ex: attack_pattern)")
    cli.add_argument("--output-dir", default=".", help="Répertoire de sortie")
    cli.add_argument("--ignored-keys", default=None, help="Fichier de clés à ignorer")

    args = cli.parse_args()
    out = parse(
        input_path=args.schema,
        output_dir=args.output_dir,
        root=args.root,
        ignored_keys_path=args.ignored_keys,
    )
    print(out)


if __name__ == "__main__":
    main()
