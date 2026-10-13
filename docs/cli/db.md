# Database commands

`renus db` runs database maintenance tasks using the database configured for the current project. Run it without arguments to print the command summary:

```bash
renus db
```

## Backup, restore, and drop

```bash
renus db --backup
renus db --restore
renus db --drop
```

Backup writes JSON files to `./db` by default; restore reads from that directory. `--path` changes the backup or restore directory, and `--table` limits the operation to one table:

```bash
renus db --backup --path ./backups --table users
renus db --restore --path ./backups --table users
renus db --drop --table users
```

`--drop` deletes records from the selected table, or from all tables if `--table` is omitted. It does not mean dropping the database schema.

## Migrations

Migration files are stored in `migrations/` by default. Use `--migrations` to select another directory:

```bash
renus db migrate create add_users
renus db migrate status
renus db migrate upgrade
renus db migrate check
```

Available subcommands:

| Subcommand | Action |
| --- | --- |
| `create <name>` | Create a migration file. |
| `upgrade` | Apply pending migrations. `--to <version>` can specify a target; `--fake` records the migration without applying it. |
| `downgrade` | Revert migrations. Use `--steps <n>` or `--to <version>` to select a target; `--fake` records the change without applying it. |
| `status` | Show applied and pending migrations. |
| `check` | Verify applied migration files are consistent. |
| `reset` | Revert all migrations. |

Migration commands also accept `--connection <name>`. The active database adapter and its settings come from the project's configuration; configure the database before running maintenance or migrations. See [database configuration](../configuration/database.md) and [migrations](../database/migrations.md) for details.

Database operations can modify or delete data. Verify the selected database and backup important data before using `--restore`, `--drop`, or migration downgrade/reset commands.
