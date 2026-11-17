"""The schema and the registry have to agree, or fields silently vanish."""

from __future__ import annotations

import unittest

from spica.build import DERIVATIONS
from spica.schema import (
    FIELDS,
    FIELDS_BY_NAME,
    SECTIONS,
    FieldSpec,
    check_type,
    fields_for_source,
)
from spica.sources import SOURCES_BY_KEY


class TestSchema(unittest.TestCase):
    def test_field_names_are_unique(self):
        names = [spec.name for spec in FIELDS]
        self.assertEqual(len(names), len(set(names)))

    def test_every_field_belongs_to_a_known_section(self):
        for spec in FIELDS:
            self.assertIn(spec.section, SECTIONS, spec.name)

    def test_every_field_has_a_source_that_exists(self):
        for spec in FIELDS:
            if spec.derived:
                continue
            self.assertIn(spec.source, SOURCES_BY_KEY, spec.name)

    def test_every_source_owns_at_least_one_field(self):
        for key in SOURCES_BY_KEY:
            self.assertTrue(fields_for_source(key), f"{key} owns no fields")

    def test_derived_fields_name_real_inputs_and_have_a_derivation(self):
        for spec in FIELDS:
            if not spec.derived:
                continue
            self.assertTrue(spec.derived_from, spec.name)
            self.assertIn(spec.name, DERIVATIONS, spec.name)
            for name in spec.derived_from:
                self.assertIn(name, FIELDS_BY_NAME, f"{spec.name} needs {name}")

    def test_derived_fields_come_after_their_inputs(self):
        # The builder derives in schema order, so an input must be built first.
        position = {spec.name: index for index, spec in enumerate(FIELDS)}
        for spec in FIELDS:
            for name in spec.derived_from:
                self.assertLess(position[name], position[spec.name])


class TestCheckType(unittest.TestCase):
    def spec(self, kind: str) -> FieldSpec:
        return FieldSpec("x", "identity", "X", kind, "hgnc")

    def test_accepts_what_it_should(self):
        cases = [
            ("text", "PCSK9"),
            ("sequence", "MGTV"),
            ("text_list", ["a", "b"]),
            ("integer", 692),
            ("number", 1.5),
            ("number", 2),
            ("number_map", {"Liver": 77.41}),
            ("text_map", {"liver": "High"}),
        ]
        for kind, value in cases:
            self.assertEqual(check_type(self.spec(kind), value), "", f"{kind}={value}")

    def test_rejects_what_it_should(self):
        cases = [
            ("text", ""),
            ("text", 3),
            ("text_list", []),
            ("text_list", "a"),
            ("text_list", ["a", ""]),
            ("integer", 1.5),
            ("integer", True),  # bool is an int, but never a measurement
            ("number", "1.5"),
            ("number_map", {"Liver": "77.41"}),
            ("number_map", {}),
            ("text_map", {"liver": 3}),
        ]
        for kind, value in cases:
            self.assertNotEqual(check_type(self.spec(kind), value), "", f"{kind}={value}")


if __name__ == "__main__":
    unittest.main()
