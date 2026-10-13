# Extensions

The `renus extension` command installs extensions published by the Codenus extension service. Run it from the project directory. The project can declare extensions in `extension.json` under an `apps` object:

```json
{
  "apps": {
    "codenus/kit": "*"
  }
}
```

Install a configured extension set, or install one extension by its namespace/name:

```bash
renus extension
renus extension codenus/kit
renus extension codenus/kit==1.2.*
```

A version of `*` selects the latest available version. A wildcard prefix such as `1.2.*` selects the latest matching version. The command downloads extension packages from `codenus.com`, processes their install metadata, and records installed versions in `extension-lock.json`.

Manage extensions already in the lock file with:

```bash
renus extension --update
renus extension --upgrade codenus/kit
renus extension --remove codenus/kit
renus extension --remove
```

`--update` and `--upgrade` without a package target apply to all installed extensions; `--remove` without a target removes all installed extensions. Do not combine `--remove` with `--update` or `--upgrade`.

## Local extensions

Projects generated with the `extension` project template include a project-local `renus local` command. It operates on packages in the project's `extension/` directory rather than downloading them:

```bash
renus local --new-extension test/blog
renus local --install
renus local --update
renus local --upgrade
renus local --remove
```

The local command can also take extension names after an operation flag to limit which packages are processed. It writes its installed-extension lock file under `extension/extension-lock.json`. This command is supplied by that project template; it is not one of the framework's built-in CLI commands.
