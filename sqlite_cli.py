
#!/usr/bin/env python3
"""
sqlite_cli.py — lightweight CLI to run arbitrary SQL against a SQLite DB.

Defaults to ./resume_analyzer.db in read-only mode, but can be switched to RW.
Provides a REPL if no -e/--execute or -f/--file is given.

Extras:
- Registers SQL function timediff_str(start, end) -> human-readable delta.
- Registers SQL function timediff_seconds(start, end) -> integer seconds.
- Commands inside REPL (all start with a backslash):
  \q                 quit
  \help              show help
  \tables            list tables
  \schema [table]    show CREATE for DB or a table
  \headers on|off    toggle header row
  \mode table|csv|tsv  set output format
  \nullvalue <str>   set NULL display token
"""

import argparse
import csv
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

DEFAULT_DB = "resume_analyzer.db"

# ---------- time parsing & helpers ----------

def _parse_ts(x):
    """
    Accepts:
      - None -> None
      - int/float epoch seconds
      - str in common SQLite formats:
          'YYYY-MM-DD HH:MM:SS[.fff][+ZZ:ZZ]' or 'YYYY-MM-DDTHH:MM:SS'
          'YYYY-MM-DD' (assumed 00:00:00)
    Returns timezone-aware datetime in UTC, or None if cannot parse.
    """
    if x is None:
        return None
    if isinstance(x, (int, float)):
        try:
            return datetime.fromtimestamp(float(x), tz=timezone.utc)
        except Exception:
            return None
    if not isinstance(x, str):
        return None

    s = x.strip()
    # Try ISO-like
    try:
        # Python handles "YYYY-MM-DD HH:MM:SS[.ffffff][±HH:MM]" as of 3.11 fairly well
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        pass

    # Common SQLite strftime storage formats
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            continue
    return None


def _format_hms(total_seconds: int) -> str:
    if total_seconds is None:
        return None
    neg = total_seconds < 0
    s = abs(int(total_seconds))
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m, sec = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h or d:
        parts.append(f"{h}h")
    if m or h or d:
        parts.append(f"{m}m")
    parts.append(f"{sec}s")
    out = " ".join(parts)
    return f"-{out}" if neg else out


# ---------- SQLite SQL functions ----------

def sql_timediff_seconds(start, end):
    """Return (end - start) in integer seconds. NULL if either is NULL or unparsable."""
    a = _parse_ts(start)
    b = _parse_ts(end)
    if not a or not b:
        return None
    return int((b - a).total_seconds())

def sql_timediff_str(start, end):
    """Return (end - start) as a compact human-readable string, e.g., '1d 2h 3m 4s'."""
    secs = sql_timediff_seconds(start, end)
    return _format_hms(secs) if secs is not None else None


# ---------- output formatting ----------

def _print_table(rows, headers, mode="table", show_headers=True, nullvalue="NULL"):
    if mode == "csv":
        w = csv.writer(sys.stdout)
        if show_headers:
            w.writerow(headers)
        for r in rows:
            w.writerow([_coalesce(v, "") for v in r])
        return
    if mode == "tsv":
        if show_headers:
            sys.stdout.write("\t".join(headers) + "\n")
        for r in rows:
            sys.stdout.write("\t".join(_to_tsv_cell(v, nullvalue) for v in r) + "\n")
        return

    # table mode
    cols = len(headers)
    # compute widths
    widths = [len(h) if show_headers else 0 for h in headers]
    for r in rows:
        for i in range(cols):
            cell = _display(v := r[i], nullvalue)
            if len(cell) > widths[i]:
                widths[i] = len(cell)

    def sep(char="-", cross="+"):
        return cross + cross.join(char * (w + 2) for w in widths) + cross

    if show_headers:
        print(sep())
        print("| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)) + " |")
    print(sep())
    for r in rows:
        line = "| " + " | ".join(_display(r[i], nullvalue).ljust(widths[i]) for i in range(cols)) + " |"
        print(line)
    print(sep())

def _display(v, nullvalue):
    return nullvalue if v is None else str(v)

def _coalesce(v, fallback):
    return fallback if v is None else v

def _to_tsv_cell(v, nullvalue):
    if v is None:
        return nullvalue
    s = str(v)
    return s.replace("\t", "    ").replace("\n", " ")

# ---------- REPL ----------

HELP_TEXT = r"""
Commands (prefix with '\'):
  \q                       Quit
  \help                    Show this help
  \tables                  List tables
  \schema [table]          Show CREATE statements
  \headers on|off          Toggle header row
  \mode table|csv|tsv      Set output format
  \nullvalue <text>        Set displayed token for NULLs

Notes:
- You can enter multi-line SQL; end with a semicolon ';' to execute.
- Registered SQL helpers:
    timediff_seconds(start, end) -> integer seconds (or NULL)
    timediff_str(start, end)     -> 'Xd Yh Zm Ws' string (or NULL)
"""

def run_repl(conn: sqlite3.Connection):
    conn.row_factory = sqlite3.Row
    show_headers = True
    mode = "table"
    nullvalue = "NULL"
    buf = []

    def exec_and_print(sql: str):
        try:
            cur = conn.execute(sql)
            # Some statements don't return rows
            if cur.description is None:
                # e.g., PRAGMA, DDL; print change count if any
                ch = conn.total_changes
                print("(ok)")
                return
            headers = [d[0] for d in cur.description]
            rows = cur.fetchall()
            _print_table([tuple(r) for r in rows], headers, mode=mode, show_headers=show_headers, nullvalue=nullvalue)
        except sqlite3.Error as e:
            print(f"[sqlite error] {e}")

    print("SQLite REPL. Type \\help for commands. End SQL with ';'.")
    while True:
        try:
            prompt = "... " if buf else "sql> "
            line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not buf and line.startswith("\\"):
            cmd = line.strip()
            if cmd in ("\\q", "\\quit", "\\exit"):
                break
            elif cmd in ("\\help", "\\h"):
                print(HELP_TEXT.strip())
            elif cmd.startswith("\\headers"):
                parts = cmd.split()
                if len(parts) == 2 and parts[1].lower() in ("on", "off"):
                    show_headers = parts[1].lower() == "on"
                    print(f"(headers {'on' if show_headers else 'off'})")
                else:
                    print("Usage: \\headers on|off")
            elif cmd.startswith("\\mode"):
                parts = cmd.split()
                if len(parts) == 2 and parts[1].lower() in ("table", "csv", "tsv"):
                    mode = parts[1].lower()
                    print(f"(mode {mode})")
                else:
                    print("Usage: \\mode table|csv|tsv")
            elif cmd.startswith("\\nullvalue"):
                parts = cmd.split(maxsplit=1)
                if len(parts) == 2:
                    nullvalue = parts[1]
                    print(f"(nullvalue '{nullvalue}')")
                else:
                    print("Usage: \\nullvalue <text>")
            elif cmd.startswith("\\tables"):
                try:
                    cur = conn.execute(
                        "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                    )
                    names = [r[0] for r in cur.fetchall()]
                    print("\n".join(names) if names else "(no tables)")
                except sqlite3.Error as e:
                    print(f"[sqlite error] {e}")
            elif cmd.startswith("\\schema"):
                parts = cmd.split()
                try:
                    if len(parts) == 1:
                        cur = conn.execute("SELECT type, name, sql FROM sqlite_schema WHERE sql IS NOT NULL ORDER BY type, name")
                    else:
                        cur = conn.execute(
                            "SELECT type, name, sql FROM sqlite_schema WHERE name = ? AND sql IS NOT NULL",
                            (parts[1],),
                        )
                    rows = cur.fetchall()
                    if not rows:
                        print("(no schema)")
                    else:
                        for t, n, s in rows:
                            print(s.rstrip(";\n") + ";")
                except sqlite3.Error as e:
                    print(f"[sqlite error] {e}")
            else:
                print("Unknown command. Type \\help for help.")
            continue

        buf.append(line)
        if any(";" in part for part in _split_sql_lines(line)):
            # join, execute each statement separated by semicolon
            sql_text = "\n".join(buf)
            statements = [s.strip() for s in sql_text.split(";") if s.strip()]
            for stmt in statements:
                exec_and_print(stmt)
            buf = []  # reset buffer

def _split_sql_lines(line: str):
    # Simple splitter that respects quoted strings (single/double)
    out = []
    current = []
    quote = None
    it = iter(range(len(line)))
    i = 0
    while i < len(line):
        ch = line[i]
        current.append(ch)
        if quote:
            if ch == quote:
                quote = None
            elif ch == "\\":
                # skip next char after escape in strings
                nxt = i + 1
                if nxt < len(line):
                    current.append(line[nxt])
                    i = nxt
        else:
            if ch in ("'", '"'):
                quote = ch
        i += 1
    out.append("".join(current))
    return out

# ---------- main ----------

def connect_db(path: str, readonly: bool) -> sqlite3.Connection:
    if readonly:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, isolation_level=None)
    else:
        conn = sqlite3.connect(path)
    # Performance/behavioral pragmas (safe defaults)
    conn.execute("PRAGMA foreign_keys=ON;")
    # Register helper functions
    conn.create_function("timediff_seconds", 2, sql_timediff_seconds)
    conn.create_function("timediff_str", 2, sql_timediff_str)
    return conn

def main():
    ap = argparse.ArgumentParser(description="Run arbitrary SQL against a SQLite DB (with extras).")
    ap.add_argument("--db", default=DEFAULT_DB, help=f"Path to SQLite database (default: {DEFAULT_DB})")
    ap.add_argument("--read-only", action="store_true", help="Open database in read-only mode (default)")
    ap.add_argument("--read-write", action="store_true", help="Open database read-write (create if missing)")
    ap.add_argument("-e", "--execute", help="Execute a single SQL statement and exit")
    ap.add_argument("-f", "--file", help="Execute SQL from a file and exit")
    ap.add_argument("--mode", choices=["table", "csv", "tsv"], default="table", help="Output format (non-REPL)")
    ap.add_argument("--no-headers", action="store_true", help="Suppress header row (non-REPL)")
    ap.add_argument("--nullvalue", default="NULL", help="Token to show for NULLs")
    args = ap.parse_args()

    # Determine mode
    readonly = not args.read_write

    if not os.path.exists(args.db) and readonly:
        sys.stderr.write(f"error: database not found (read-only): {args.db}\n")
        sys.exit(2)

    try:
        conn = connect_db(args.db, readonly=readonly)
    except sqlite3.Error as e:
        sys.stderr.write(f"error: cannot open database: {e}\n")
        sys.exit(1)

    try:
        if args.execute or args.file:
            sql_text = args.execute or open(args.file, "r", encoding="utf-8").read()
            conn.row_factory = sqlite3.Row
            # Execute possibly multiple statements separated by ';'
            statements = [s.strip() for s in sql_text.split(";") if s.strip()]
            last_rows = None
            last_headers = None
            for stmt in statements:
                cur = conn.execute(stmt)
                if cur.description is not None:
                    last_headers = [d[0] for d in cur.description]
                    last_rows = cur.fetchall()
            # Print only the last result set (common CLI behavior)
            if last_headers is not None:
                _print_table(
                    [tuple(r) for r in last_rows],
                    last_headers,
                    mode=args.mode,
                    show_headers=(not args.no_headers),
                    nullvalue=args.nullvalue,
                )
            else:
                print("(ok)")
        else:
            run_repl(conn)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
