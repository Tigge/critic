import sqlite3
import os
import re

import installation

def sqltokens(command):
    return re.findall(r"""\$\d+|!=|<>|<=|>=|'(?:''|[^'])*'|"(?:[^"])*"|\w+|[^\s]""", command)

def sqlcommands(filename):
    path = os.path.join(installation.root_dir, "installation", "data", filename)
    script = []
    with open(path) as script_file:
        for line in script_file:
            fragment, _, comment = line.strip().partition("--")
            fragment = fragment.strip()
            if fragment:
                script.append(fragment)
    script = " ".join(script)
    return filter(None, map(str.strip, script.split(";")))

def replace(query, old, new):
    tokens = query if isinstance(query, list) else sqltokens(query)
    old = sqltokens(old)
    new = sqltokens(new)
    start = 0
    try:
        while True:
            for anchor_offset, anchor_token in enumerate(old):
                if anchor_token[0] != "$":
                    break
            offset = map(str.upper, tokens).index(old[anchor_offset].upper(), start) - anchor_offset
            data = {}
            for index in range(len(old)):
                if old[index][0] == "$":
                    data[old[index]] = tokens[offset + index]
                elif tokens[offset + index].upper() != old[index].upper():
                    start = offset + 1
                    break
            else:
                if data:
                    use_new = map(lambda token: data.get(token, token), new)
                else:
                    use_new = new
                tokens[offset:offset + len(old)] = use_new
                start = offset + len(use_new)
    except ValueError:
        return " ".join(tokens)

def import_schema(database_path, filenames, quiet=False):
    failed = False
    enumerations = {}
    commands = []
    db = sqlite3.connect(database_path)

    for filename in filenames:
        commands.extend(sqlcommands(filename))

    for command in commands:
        if command.startswith("SET "):
            # Skip SET; only used to control the output from psql.
            continue
        elif re.match(r"CREATE (?:UNIQUE )?INDEX \w+_(?:md5|gin)", command) \
                or re.match(r"CREATE (?:UNIQUE )?INDEX .* WHERE ", command):
            # Fancy index stuff not supported by sqlite.  Since they are
            # optional (sans performance requirements) we just skip them.
            continue
        elif command.startswith("CREATE TABLE ") \
                or command.startswith("CREATE INDEX ") \
                or command.startswith("CREATE UNIQUE INDEX ") \
                or command.startswith("CREATE VIEW ") \
                or command.startswith("INSERT INTO "):
            tokens = sqltokens(command)
            replace(tokens, "DEFAULT NOW()", "DEFAULT (cast(strftime('%s', 'now') as integer))")
            replace(tokens, "TRUE", "1")
            replace(tokens, "FALSE", "0")
            replace(tokens, "INTERVAL '0'", "0")
            replace(tokens, "SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY")
            replace(tokens, "commit", '"commit"')
            replace(tokens, "transaction", '"transaction"')
            for name, values in enumerations.items():
                replace(tokens, "$1 " + name, "$1 text check ($1 in (%s))" % ", ".join(values))
            command = " ".join(tokens)
        elif re.match(r"CREATE TYPE \w+ AS ENUM", command):
            tokens = sqltokens(command)
            name = tokens[2]
            values = filter(lambda token: re.match("'.*'$", token),
                            tokens[tokens.index("(") + 1:tokens.index(")")])
            enumerations[name] =  values
            continue
        elif command.startswith("ALTER TABLE "):
            # Used to add constraints after table creation, which sqlite doesn't
            # support.
            continue
        else:
            print "Unrecognized:", command
            failed = True

        if not quiet:
            words = command.split()
            for word in words:
                if word.upper() != word:
                    print word
                    break
                print word,

        try:
            db.execute(command)
        except Exception as error:
            print "Failed:", command
            print "  " + str(error)
            failed = True

    if not failed:
        db.commit()

    return not failed

if __name__ == "__main__":
    os.unlink("test.db")
    db = sqlite3.connect("test.db")
    import_schema(db, "installation/data/dbschema.sql")
    import_schema(db, "installation/data/dbschema.comments.sql")
    import_schema(db, "installation/data/dbschema.extensions.sql")
