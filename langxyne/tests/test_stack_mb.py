import unittest

from langxyne.tests.support import FIXTURE, KITCHEN_SINK, assert_objection, load, mutate, objections

SEND = '[function.send]\n_return = "status"\n'


def with_stack_mb(value: str, text: str = FIXTURE) -> str:
    """`text` with `_stack_mb = <value>`, a TOML value, on function.send."""
    return mutate(text, SEND, f"{SEND}_stack_mb = {value}\n")


class StackMb(unittest.TestCase):
    """SPEC "The definition": `_stack_mb` on a function names a positive `untyped_const` entry."""

    def test_the_entry_named_is_the_functions(self) -> None:
        api = load(with_stack_mb('"max_units"'))
        [send] = [fn for fn in api.functions if fn.name == "send"]
        self.assertEqual((send.stack_mb.name, send.stack_mb.value), ("max_units", 16))
        self.assertTrue(all(fn.stack_mb is None for fn in api.functions if fn.name != "send"))

    def test_an_entry_of_no_untyped_const_group(self) -> None:
        for entry in ("big", "ok", "feat_a", "product"):
            with self.subTest(entry=entry):
                assert_objection(
                    self,
                    with_stack_mb(f'"{entry}"'),
                    f"function.send._stack_mb: '{entry}' is not an untyped_const entry",
                )

    def test_an_entry_not_positive(self) -> None:
        text = mutate(FIXTURE, "max_units = 16\n", "max_units = 16\nnone_left = 0\nbelow = -1\n")
        for entry, value in (("none_left", 0), ("below", -1)):
            with self.subTest(entry=entry):
                assert_objection(
                    self,
                    with_stack_mb(f'"{entry}"', text),
                    f"function.send._stack_mb: '{entry}' is {value}, not positive",
                )

    def test_a_value_that_is_not_a_name(self) -> None:
        assert_objection(self, with_stack_mb("16"), "function.send._stack_mb must name an untyped_const entry")

    def test_a_callback_type_has_no_stack_mb(self) -> None:
        text = mutate(KITCHEN_SINK, "[callback.on_mode]\n", '[callback.on_mode]\n_stack_mb = "max_units"\n')
        self.assertEqual(
            objections(text),
            [
                "callback.on_mode: unknown key(s) _stack_mb",
                *(f"function.notify.{p}: unknown type 'on_mode'" for p in ("first", "second")),
            ],
        )
