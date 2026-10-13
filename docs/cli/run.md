# Running the server

`renus run` starts an ASGI application with Uvicorn. Install the server extra first:

```bash
python -m pip install "renus[server]"
```

From the project directory, run the development server:

```bash
renus run
```

Development mode is the default. It enables reload, binds to `127.0.0.1`, and uses port `8000`. Production mode disables reload and binds to `0.0.0.0`:

```bash
renus run prod
```

The command looks for `main.py` first, then `app.py`, and expects the ASGI application to be named `app` in that module. To use a different import target, pass `--app module:object`:

```bash
renus run dev --app myproject.asgi:application
```

Host, port, reload, and other Uvicorn options can be provided as flags. For example:

```bash
renus run dev --host 0.0.0.0 --port 9000 --reload
renus run prod --host 0.0.0.0 --port 8000
```

Boolean and null-like values are converted from `true`, `false`, `none`, or `null`. A `--no-<option>` flag sets an option to false. Options are passed through to `uvicorn.run`; consult the [Uvicorn settings](https://www.uvicorn.org/settings/) for supported options.

If Uvicorn is missing, install `renus[server]` (or install `uvicorn` directly). You can also run an application with `App.run()` as described in the [application guide](../development/app.md).
