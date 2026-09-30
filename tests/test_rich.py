import re

import pytest

from renus.rich import Progress, Terminal
from renus.rich import _style as style_mod

@pytest.fixture(autouse=True)
def no_color():
    original = style_mod.color_enabled
    style_mod.color_enabled = False
    yield
    style_mod.color_enabled = original

@pytest.fixture
def color():
    original = style_mod.color_enabled
    style_mod.color_enabled = True
    yield
    style_mod.color_enabled = original

class TestExports:

    def test_terminal_progress_returns_progress(self):
        assert isinstance(Terminal.progress(10), Progress)

class TestTable:
    def test_multiline_cells_and_headers_are_rendered_as_aligned_rows(self):
        table = Terminal.table(headers=["Name\n(full)", "Details"])

        rendered = table([["item", "first\nsecond"]])

        assert rendered == "\n".join(
            [
                "┌──────────────────┐",
                "│ Name   │ Details │",
                "│ (full) │         │",
                "├──────────────────┤",
                "│ item   │ first   │",
                "│        │ second  │",
                "└──────────────────┘",
            ]
        )

    def test_ragged_rows_are_padded_to_the_same_column_count(self):
        rendered = Terminal.table()([["one", "two"], ["only one"]])

        assert "│ only one │     │" in rendered

    def test_ansi_styling_does_not_affect_column_alignment(self, color):
        rendered = Terminal.table(headers=["Column", "Value"])(
            [[Terminal.red("x"), "long"], ["longer", "y"]]
        )
        plain = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", rendered)
        body_lines = [line for line in plain.splitlines() if line.startswith("│")]

        assert len({len(line) for line in plain.splitlines()}) == 1
        assert len({line.index(" │ ") for line in body_lines}) == 1

    def test_ansi_style_is_reapplied_to_each_multiline_cell_line(self, color):
        rendered = Terminal.table(headers=["Value", "Other"])(
            [[Terminal.red("first\nsecond"), "a longer value"]]
        )
        styled_lines = [
            line for line in rendered.splitlines() if "first" in line or "second" in line
        ]

        assert len(styled_lines) == 2
        for line in styled_lines:
            assert "\x1b[91m" in line
            assert "\x1b[0m" in line
            assert line.index("\x1b[0m") < line.index(" │ ")


class TestProgress:
    def test_starts_empty(self):
        bar = Terminal.progress(10)
        assert bar.render() == "░" * 40 + " 0% 0/10"

    def test_complete_fills_bar(self):
        bar = Terminal.progress(10).complete()
        assert bar.render() == "█" * 40 + " 100% 10/10"

    def test_advance_moves_progress(self):
        bar = Terminal.progress(10)
        for _ in range(4):
            bar.advance()
        filled = int(round(0.4 * 40))
        assert bar.render() == "█" * filled + "░" * (40 - filled) + " 40% 4/10"

    def test_update_with_current_sets_absolute(self):
        bar = Terminal.progress(100)
        bar.update(current=25)
        filled = int(round(0.25 * 40))
        assert bar.render() == "█" * filled + "░" * (40 - filled) + " 25% 25/100"

    def test_advance_clamped_at_total(self):
        bar = Terminal.progress(3).update(advance=99)
        assert bar.render().endswith("100% 3/3")

    def test_label_appears_first(self):
        bar = Terminal.progress(10, label="draining").advance()
        assert bar.render().startswith("draining ")

    def test_update_can_rename_label(self):
        bar = Terminal.progress(10).advance().update(label="new")
        assert bar.render().startswith("new ")

    def test_zero_total_stays_idle(self):
        assert Terminal.progress(0).render().endswith("0% 0/0")
        assert Terminal.progress(0).advance().render().endswith("0% 0/0")

    def test_call_returns_render(self):
        assert Terminal.progress(4)() == Terminal.progress(4).render()

    @pytest.mark.parametrize("label", [None, "work"])
    def test_context_manager_completes_on_exit(self, capsys, label):
        with Terminal.progress(5, label=label) as bar:
            bar.advance()
            bar.advance()
        out = capsys.readouterr().out
        assert "100% 5/5" in out

    def test_print_updates_in_place_until_complete(self, capsys):
        bar = Terminal.progress(6, label="ctx")
        for i in range(4):
            bar.update(current=i + 1).print()
        out = capsys.readouterr().out

        assert "\n" not in out
        assert out.count("\r") == 4
        assert "67% 4/6" in out

    def test_print_complete_settles_with_newline(self, capsys):
        bar = Terminal.progress(6).complete().print()
        out = capsys.readouterr().out
        assert out.endswith("100% 6/6\n")

    def test_print_explicit_end_forces_newline(self, capsys):
        bar = Terminal.progress(6).update(advance=3).print(end="\n")
        out = capsys.readouterr().out
        assert out.endswith("50% 3/6\n")

    def test_finish_settles_incomplete_bar(self, capsys):
        bar = Terminal.progress(6).update(advance=2)
        assert bar.finish() is bar
        assert capsys.readouterr().out.endswith("33% 2/6\n")

    def test_finish_can_complete_first(self, capsys):
        bar = Terminal.progress(6).update(advance=2).finish(complete=True)
        assert capsys.readouterr().out.endswith("100% 6/6\n")

    def test_custom_styles_resolve_from_terminal(self, color):
        bar = Terminal.progress(2, bar_style="red", width=5).complete()
        assert "\x1b[91m" in bar.render() and "█" in bar.render()

    def test_unknown_style_falls_back_to_plain(self, color):
        bar = Terminal.progress(2, bar_style="nope", width=5).complete()
        assert "█" in bar.render() and "\x1b[" not in bar.render()

    def test_respects_disabled_color(self, no_color):
        bar = Terminal.progress(2, width=5).update(advance=1)
        assert "\x1b[" not in bar.render()
