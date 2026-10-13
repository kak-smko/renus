# App package scaffolding

`renus app` generates a feature package in the current Renus project and registers its routes. Supply a package name, or run the command without one to be prompted:

```bash
renus app blog
```

Package names may use dot-separated folders to create a nested package:

```bash
renus app admin.blog
```

The command creates controller, model, route, and Vue view files under `app/` and `frontend/admin/src/views/`. It also registers the backend route module in the application index and, when the frontend admin router exists, adds the view route there.

The project must have the expected Renus project structure for the generated files and route registration to be useful. The command does not accept template or database options; it scaffolds a package within the current project rather than creating a new project. See [project scaffolding](create.md) to generate a project.
