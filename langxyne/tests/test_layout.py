import unittest

from langxyne.tests.support import MINIMAL, load

# Fields each at the next offset its alignment allows: `b` after a byte, `c` after a word, and
# `held` holding the padded struct after a halfword, the text type after it.
LAID_OUT = (
    MINIMAL
    + '\n[[struct]]\n[struct.padded]\na = "u8"\nb = "u32"\nc = "u16"\n'
    + '\n[struct.holder]\nx = "u16"\nheld = "padded"\nlabel = "text"\ny = "u8"\n'
)


class FieldOffsets(unittest.TestCase):
    """SPEC "The definition": a struct lays its fields out as C does, each at the next offset its
    alignment allows."""

    def test_a_padded_struct(self) -> None:
        api = load(LAID_OUT)
        self.assertEqual(api.field_offsets("padded"), (("a", "u8", 0), ("b", "u32", 4), ("c", "u16", 8)))
        self.assertEqual(api.layout("padded"), (12, 4))

    def test_a_nested_struct_and_the_text_type(self) -> None:
        api = load(LAID_OUT)
        self.assertEqual(
            api.field_offsets("holder"),
            (("x", "u16", 0), ("held", "padded", 4), ("label", "text", 16), ("y", "u8", 24)),
        )
        self.assertEqual(api.field_offsets("text"), (("offset", "u32", 0), ("length", "u32", 4)))
