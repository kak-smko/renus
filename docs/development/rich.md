# Rich Terminal

Renus ships a small, dependency-free `renus.rich` package for rendering styled terminal output. It is used throughout Renus' own CLI and logging to give consistent colored output for text, headers, tables, progress bars, and Markdown. It emits ANSI escape codes directly and requires no third-party dependencies.

The public API is a `Terminal` namespace, a `markdown` helper, and a `Progress` bar class:

```python
from renus.rich import Terminal, Progress, markdown
```

## Colors are automatic

Styles only apply color when the output is a terminal and color is enabled. By default, Renus checks the `color` key in the `app` config module:

- if `color` is `True`, styles are always colored,
- if `color` is `False`, styles are stripped,
- if `color` is unset, colors are enabled only when `sys.stdout` is a TTY.

```python
# config/app.py
color = False   # disable ANSI colors everywhere
```

When colors are disabled (or stdout is not a TTY), styled output falls back to plain text, so piping output stays clean.

## The `Terminal` namespace

`Terminal` exposes ready-made text styles, background styles, and a set of semantic level styles, all callable on any object to decorate it. Each attribute is an instance of a lightweight `_Style` that wraps text in the matching ANSI codes.

```python
from renus.rich import Terminal

print(Terminal.bold("Renus"))
print(Terminal.green("Created migration: x"))
print(Terminal.red("Backup file does not exist."))
```

Styles are composable. Calling a style attribute on a style combines their ANSI codes, so you can chain modifiers and colors:

```python
print(Terminal.bold.cyan("Version 1.2.0"))
```

A style also has `.print()` and `.write()` helpers that print the decorated text directly:

```python
Terminal.green.print("All migrations are consistent.")
Terminal.cyan.print(DESCRIPTION)
```

### Text styles

| Style              | Effect      |
| ------------------ | ----------- |
| `Terminal.bold`    | Bold        |
| `Terminal.dim`     | Dim / faint |
| `Terminal.italic`  | Italic      |
| `Terminal.underline` | Underline |
| `Terminal.blink`   | Blink       |
| `Terminal.inverse` | Inverse     |
| `Terminal.hidden`  | Hidden      |
| `Terminal.strike`  | Strikethrough |

### Foreground colors

| Attribute             | Color     |
| --------------------- | --------- |
| `Terminal.black`      | Black     |
| `Terminal.red`        | Red       |
| `Terminal.green`      | Green     |
| `Terminal.yellow`     | Yellow    |
| `Terminal.blue`       | Blue      |
| `Terminal.magenta`    | Magenta   |
| `Terminal.pink`       | Pink (same as magenta) |
| `Terminal.cyan`       | Cyan      |
| `Terminal.white`      | White     |
| `Terminal.grey`       | Grey      |

### Background colors

`Terminal.bg_black`, `Terminal.bg_red`, `Terminal.bg_green`, `Terminal.bg_yellow`, `Terminal.bg_blue`, `Terminal.bg_magenta`, `Terminal.bg_pink`, `Terminal.bg_cyan`, `Terminal.bg_grey`, and `Terminal.bg_white`.

### Semantic level styles

`Terminal.ok` (green), `Terminal.info` (cyan), `Terminal.warn` (yellow), `Terminal.error` (red), and `Terminal.faint` (dim).

## Headers

`Terminal.header()` builds a centered header line with a fixed total width (default `60`), padded with `=` characters. Call it to get the decorated string, or use `.print()` to write it:

```python
term = Terminal.header(width=60)   # optionally pass a custom width
term.print("Migration Status")      # ─── Migration Status ───
```

Any style can also produce a matching header via its `.header()` method:

```python
Terminal.bold.header().print("Done")
```

## Tables

`Terminal.table()` creates an ASCII table, optionally with column headers and a styled separator. Call the returned table with rows to render it, or use `.print()`:

```python
table = Terminal.table(headers=["Version", "Name", "Status"], style_sep="bold")
table.print([
    ["001", "create_users", "applied"],
    ["002", "add_posts", "pending"],
])
```

The table draws rounded borders (`┌ ─ │ ┘`), left-aligns cells to the widest column, and inserts a separator line beneath the header row.

## Markdown

`Terminal.markdown(text)` (equivalently the module-level `markdown(text)`) renders a Markdown string to styled terminal output. It understands headings, horizontal rules, blockquotes, bullet and ordered lists, inline code, bold, italic, links, and fenced code blocks:

```python
from renus.rich import Terminal

md = """
# Renus

Run with **--reload** in development.

- create projects
- run servers
- manage migrations
"""

print(Terminal.markdown(md))
```

Links render as `title (url)`, and tables are rendered with the ASCII table builder (see `_collect_table`). This is how Renus formats CLI help and descriptions.

## Progress bars

`Terminal.progress()` returns a `Progress` instance that renders an in-place progress bar.

```python
with Terminal.progress(10, label="draining") as bar:
    for _ in range(10):
        ...  # do work
        bar.advance()
```

When used as a context manager, the bar is completed and printed on a fresh line on exit.

### Building and updating

```python
bar = Terminal.progress(total=100, width=40)
bar.advance()                  # move forward by 1
bar.update(current=25)         # set an absolute position
bar.update(advance=5)          # or advance by an amount
bar.update(label="new label")  # relabel while running
bar.complete()                 # jump straight to 100%
```

The current position is clamped to `[0, total]`; a `total` of `0` stays idle at `0% 0/0`. `render()` returns the bar string, and calling the instance (`bar()`) is equivalent.

### Printing

- `bar.print()` redraws the bar over the same line using `\r`, adding a trailing newline only once it reaches its total.
- `bar.print_inplace()` prints with no trailing newline.
- `bar.finish(complete=True)` optionally completes the bar, then prints it on a fresh line.

```python
for i in range(6):
    bar = Terminal.progress(6, label="ctx")
    bar.update(current=i + 1).print()
```

### Styling

`bar_style` and `label_style` accept either a `Terminal` style name (e.g. `"green"`, `"cyan"`) or a style instance. Unknown style names fall back to plain output.

```python
bar = Terminal.progress(10, label="Uploaded", bar_style="green", label_style="cyan")
```

## Color and your terminal

All rendering flows through `renus.rich._style`, which resolves a single `color_enabled` flag at import time. When disabled, every style returns text unchanged, so progress bars, tables, and Markdown all degrade gracefully to plain output — safe to redirect to files or logs.

If you need colored output regardless of TTY detection, set `color = True` in `config/app.py`.
