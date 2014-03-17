# -*- mode: python; encoding: utf-8 -*-
#
# Copyright 2012 Jens Lindström, Opera Software ASA
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License.  You may obtain a copy of
# the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.  See the
# License for the specific language governing permissions and limitations under
# the License.

try:
    import configuration
except ImportError:
    IntegrityError = ProgrammingError = TransactionRollbackError = Exception

    def connect():
        raise Exception("not supported")
else:
    if configuration.database.DRIVER == "postgresql":
        import psycopg2

        IntegrityError = psycopg2.IntegrityError
        ProgrammingError = psycopg2.ProgrammingError
        TransactionRollbackError = psycopg2.extensions.TransactionRollbackError

        def connect():
            return psycopg2.connect(**configuration.database.PARAMETERS)
    else:
        import sys
        import os
        import sqlite3
        import datetime

        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        import installation.qs

        IntegrityError = sqlite3.IntegrityError
        ProgrammingError = sqlite3.ProgrammingError

        # SQLite doesn't appear to be throwing this type of error.
        class TransactionRollbackError(Exception):
            pass

        def convert_date(value):
            try:
                return datetime.datetime.fromtimestamp(int(value))
            except ValueError:
                return datetime.datetime.strptime(value, "%Y-%m-%d")

        def convert_datetime(value):
            try:
                return datetime.datetime.fromtimestamp(int(value))
            except ValueError:
                return datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")

        def convert_interval(value):
            try:
                return datetime.timedelta(seconds=int(value))
            except ValueError:
                return 0

        def convert_boolean(value):
            return bool(int(value))

        def connect():
            class Cursor(object):
                def __init__(self, connection):
                    self.cursor = connection.cursor()

                def massage(self, query, parameters):
                    self.flags = set()
                    if " NULLS FIRST" in query:
                        self.flags.add("nulls_first")
                        query = query.replace(" NULLS FIRST", "")
                    elif " NULLS LAST" in query:
                        self.flags.add("nulls_last")
                        query = query.replace(" NULLS LAST", "")
                    while "=ANY (%s)" in query:
                        for index, parameter in enumerate(parameters):
                            if isinstance(parameter, (list, set, tuple)):
                                query = query.replace("=ANY (%s)", " IN (%s)" % ", ".join(["?"] * len(parameter)), 1)
                                parameters[index:index + 1] = parameter
                                break
                        else:
                            assert False, "Failed to translate all occurrences of '=ANY (%s)' in query!"
                    if query.endswith(" RETURNING id"):
                        self.flags.add("returning_id")
                        query = query[:-len(" RETURNING id")]
                    tokens = installation.qs.sqlite.sqltokens(query.replace("%s", "?"))
                    installation.qs.sqlite.replace(
                        tokens,
                        "EXTRACT ('epoch' FROM NOW() - $1)",
                        "strftime('%s', 'now') - strftime('%s', $1)")
                    installation.qs.sqlite.replace(
                        tokens,
                        "EXTRACT ('epoch' FROM (MIN($1) - NOW()))",
                        "strftime('%s', MIN($1)) - strftime('%s', 'now')")
                    installation.qs.sqlite.replace(tokens, "NOW()", "cast(strftime('%s', 'now') as integer)")
                    installation.qs.sqlite.replace(tokens, "TRUE", "1")
                    installation.qs.sqlite.replace(tokens, "FALSE", "0")
                    installation.qs.sqlite.replace(tokens, "'1 day'", str(24 * 60 * 60))
                    installation.qs.sqlite.replace(tokens, "next::text", "datetime(next, 'unixepoch')")
                    installation.qs.sqlite.replace(tokens, "commit", '"commit"')
                    installation.qs.sqlite.replace(tokens, "transaction", '"transaction"')
                    installation.qs.sqlite.replace(tokens, "MD5($1)", "$1")
                    installation.qs.sqlite.replace(tokens, "FETCH FIRST ROW ONLY", "")
                    installation.qs.sqlite.replace(tokens, "chaincomments(commentchains.id)", "0")
                    installation.qs.sqlite.replace(tokens, "chainunread(commentchains.id, ?)", "ifnull(0, ?)")
                    installation.qs.sqlite.replace(tokens, "character_length(", "length(")
                    return " ".join(tokens)

                def execute(self, query, parameters=()):
                    parameters = list(parameters)
                    query = self.massage(query, parameters)
                    try:
                        self.cursor.execute(query, parameters)
                    except sqlite3.OperationalError as error:
                        raise Exception("Invalid query: %r %r" % (error.message, query))
                    except sqlite3.InterfaceError as error:
                        raise Exception("Invalid parameters: %r %r for %r" % (error.message, parameters, query))
                    if "returning_id" in self.flags:
                        self.cursor.execute("SELECT last_insert_rowid()")

                def executemany(self, query, parameters=()):
                    parameters = list(parameters)
                    query = self.massage(query, parameters)
                    self.cursor.executemany(query, parameters)

                def fetchone(self):
                    return self.cursor.fetchone()
                def fetchall(self):
                    return self.cursor.fetchall()

                def __iter__(self):
                    return iter(self.cursor)

            class Connection(object):
                def __init__(self):
                    self.connection = sqlite3.connect(configuration.database.PARAMETERS["database"],
                                                      detect_types=sqlite3.PARSE_DECLTYPES)
                    self.connection.text_factory = str
                def cursor(self):
                    return Cursor(self.connection)
                def commit(self):
                    return self.connection.commit()
                def rollback(self):
                    return self.connection.rollback()
                def close(self):
                    return self.connection.close()

            return Connection()

        sqlite3.register_converter("DATE", convert_date)
        sqlite3.register_converter("TIMESTAMP", convert_datetime)
        sqlite3.register_converter("INTERVAL", convert_interval)
        sqlite3.register_converter("BOOLEAN", convert_boolean)
