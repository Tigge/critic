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

import re

import htmlutils
import configuration

from request import NoDefault, MovedTemporarily, DisplayMessage, \
                    InvalidParameterValue, decodeURIComponent, Request, \
                    NeedLogin

from textutils import json_encode, json_decode

LINK_RELS = { "Home": "home",
              "Dashboard": "contents",
              "Branches": "index",
              "Tutorial": "help",
              "Back to Review": "up" }

class NotModified:
    pass

def YesOrNo(value):
    if value == "yes": return True
    elif value == "no": return False
    else: raise DisplayMessage("invalid parameter value; expected 'yes' or 'no'")

def generateEmpty(target):
    pass

def generateHeader(target, db, user, generate_right=None, current_page=None, extra_links=[], profiler=None):
    target.addExternalStylesheet("resource/third-party/jquery-ui.css")
    target.addExternalStylesheet("resource/third-party/chosen.css")
    target.addExternalStylesheet("resource/third-party/bootstrap.css")
    target.addExternalStylesheet("resource/third-party/bootstrap-theme.css")
    target.addExternalStylesheet("resource/overrides.css")
    target.addExternalStylesheet("resource/basic.css")
    target.addInternalStylesheet(".defaultfont, body { %s }" % user.getPreference(db, "style.defaultFont"))
    target.addInternalStylesheet(".sourcefont { %s }" % user.getPreference(db, "style.sourceFont"))
    target.addExternalScript("resource/third-party/jquery.js")
    target.addExternalScript("resource/third-party/jquery-ui.js")
    target.addExternalScript("resource/third-party/jquery-ui-autocomplete-html.js")
    target.addExternalScript("resource/third-party/chosen.js")
    target.addExternalScript("resource/third-party/bootstrap.js")
    target.addExternalScript("resource/basic.js")

    target.noscript().h1("noscript").blink().text("Please enable scripting support!")

    opera_class = "opera"
    if configuration.debug.IS_DEVELOPMENT:
        opera_class += " development"
    navigation_bar = BootstrapNavbar(target.div("navigation"), "Critic", opera_class)

    # Links
    navigation_bar.add_item("dashboard", "Dashboard")
    navigation_bar.add_item("branches", "Branches")
    navigation_bar.add_item("search", "Search")

    if user.hasRole(db, "administrator"):
        navigation_bar.add_item("services", "Services")
    if user.hasRole(db, "repositories"):
        navigation_bar.add_item("repositories", "Repositories")
    navigation_bar.add_item("tutorial", "Tutorial")

    if profiler:
        profiler.check("generateHeader (basic)")

    if user.isAnonymous():
        count = 0
    else:
        cursor = db.cursor()
        cursor.execute("""SELECT COUNT(*)
                            FROM newsitems
                 LEFT OUTER JOIN newsread ON (item=id AND uid=%s)
                           WHERE uid IS NULL""",
                       (user.id,))
        count = cursor.fetchone()[0]

    if count:
        navigation_bar.add_item("news", "News (%d)" % count, "There are %d unread news items!" % count)
    else:
        navigation_bar.add_item("news", "News")

    if profiler:
        profiler.check("generateHeader (news)")

    req = target.getRequest()

    for url, label in extra_links:
        navigation_bar.add_item(url, label)

    # User menu
    if not user.isAnonymous():
        #right_menu.li().a(href="home").text(user.fullname)

        user_dropdown = navigation_bar.add_dropdown(user.fullname)

        user_dropdown.add_item("home", "Profile")
        user_dropdown.add_item("config", "Settings")

        if configuration.extensions.ENABLED:
            from extensions.extension import Extension

            updated = Extension.getUpdatedExtensions(db, user)

            if updated:
                link_title = "\n".join([("%s by %s can be updated!" % (extension_name, author_fullname)) for author_fullname, extension_name in updated])
                user_dropdown.add_item("manageextensions", "Extensions (%d)" % len(updated), link_title)
            else:
                user_dropdown.add_item("manageextensions", "Extensions")

            if profiler:
                profiler.check("generateHeader (updated extensions)")

        if configuration.base.AUTHENTICATION_MODE != "host" and configuration.base.SESSION_TYPE == "cookie":
            user_dropdown.add_separator()
            user_dropdown.add_item("javascript:signOut();", "Sign out")

    elif configuration.base.AUTHENTICATION_MODE != "host" and configuration.base.SESSION_TYPE == "cookie":
        navigation_bar.add_item("javascript:void(location.href='/login?target='+encodeURIComponent(location.href));", "Sign in", BootstrapNavbar.Position.RIGHT)

    # Inject extensions
    if req and configuration.extensions.ENABLED:
        import extensions.role.inject

        injected = {}

        extensions.role.inject.execute(db, req, user, target, links, injected, profiler=profiler)

        for url in injected.get("stylesheets", []):
            target.addExternalStylesheet(url, use_static=False, order=1)

        for url in injected.get("scripts", []):
            target.addExternalScript(url, use_static=False, order=1)
    else:
        injected = None

    if generate_right:
        generate_right(navigation_bar.left)
    else:
        navigation_bar.left.div("buttons").span("buttonscope buttonscope-global")

    if profiler:
        profiler.check("generateHeader (finish)")

    return injected

def getParameter(req, name, default=NoDefault(), filter=lambda value: value):
    match = re.search("(?:^|&)" + name + "=([^&]*)", str(req.query))
    if match:
        try: return filter(decodeURIComponent(match.group(1)))
        except DisplayMessage: raise
        except: raise DisplayMessage("Invalid parameter value: %s=%r" % (name, match.group(1)))
    elif isinstance(default, NoDefault): raise DisplayMessage("Required parameter missing: %s" % name)
    else: return default

def renderShortcuts(target, page, **kwargs):
    shortcuts = []

    def addShortcut(keyCode, keyName, description):
        shortcuts.append((keyCode, keyName, description))

    if page == "showcommit":
        what = "files"

        merge_parents = kwargs.get("merge_parents")
        if merge_parents > 1:
            for index in range(min(9, merge_parents)):
                order = ("first", "second", "third", "fourth", "fifth", "seventh", "eight", "ninth")[index]
                addShortcut(ord('1') + index, "%d" % (index + 1), " changes relative to %s parent" % order)
    elif page == "showcomments":
        what = "comments"

    if page == "showcommit" or page == "showcomments":
        addShortcut(ord("e"), "e", "expand all %s" % what)
        addShortcut(ord("c"), "c", "collapse all %s" % what)
        addShortcut(ord("s"), "s", "show all %s" % what)
        addShortcut(ord("h"), "h", "hide all %s" % what)

        if page == "showcommit":
            addShortcut(ord("m"), "m", "detect moved code")

            if kwargs.get("squashed_diff"):
                addShortcut(ord("b"), "b", "blame")

            addShortcut(32, "SPACE", "scroll or show/expand next file")

    if page == "showcomment":
        addShortcut(ord("m"), "m", "show more context")
        addShortcut(ord("l"), "l", "show less context")

    if page == "filterchanges":
        addShortcut(ord("a"), "a", "select everything")
        addShortcut(ord("g"), "g", "go / display diff")

    container = target.div("pagefooter shortcuts")

    if shortcuts:
        container.text("Shortcuts: ")

        def renderShortcut(keyCode, ch, text, is_last=False):
            a = container.a("shortcut", href="javascript:void(handleKeyboardShortcut(%d));" % keyCode)
            a.b().text("(%s)" % ch)
            a.text(" %s" % text)
            if not is_last:
                container.text(", ")

        for index, (keyCode, keyName, description) in enumerate(shortcuts):
            renderShortcut(keyCode, keyName, description, index == len(shortcuts) - 1)

def generateFooter(target, db, user, current_page):
    renderShortcuts(target, current_page)

def displayMessage(db, req, user, title, review=None, message=None, page_title=None, is_html=False):
    document = htmlutils.Document(req)

    if page_title:
        document.setTitle(page_title)

    document.addExternalStylesheet("resource/message.css")

    html = document.html()
    head = html.head()
    body = html.body()

    if review:
        import reviewing.utils as review_utils

        def generateRight(target):
            review_utils.renderDraftItems(db, user, review, target)

        back_to_review = ("r/%d" % review.id, "Back to Review")

        generateHeader(body, db, user, generate_right=generateRight, extra_links=[back_to_review])
    else:
        generateHeader(body, db, user)

    target = body.div("message paleyellow")

    if message:
        target.h1("title").text(title)

        if callable(message): message(target)
        elif is_html: target.innerHTML(message)
        else: target.p().text(message)
    else:
        target.h1("center").text(title)

    return document


class BootstrapDropdown():
    def __init__(self, target, text):
        target.setAttribute("class", "dropdown")
        target.a("dropdown-toggle", data_toggle="dropdown").text(text + " ").span("caret")
        self.dropdown = target.ul("dropdown-menu", role="menu")

    def add_item(self, href, text):
        self.dropdown.li().a(href=href).text(text)

    def add_separator(self):
        self.dropdown.li("divider")


class BootstrapNavbar:

    class Position:
        LEFT = 0
        RIGHT = 1

    def __init__(self, target, title, title_class=""):
        self.navbar = target.nav("navbar navbar-default", role="navigation").div("container-fluid")

        self.header = self.navbar.div("navbar-header")
        self.header.a("navbar-brand " + title_class, href="#").text(title)

        self.left = self.navbar.ul("nav navbar-nav navbar-left")
        self.right = self.navbar.ul("nav navbar-nav navbar-right")

    def add_item(self, href, text, position=Position.LEFT):
        target = self.left if position == BootstrapNavbar.Position.LEFT else self.right
        target.li().a(href=href).text(text)

    def add_dropdown(self, text):
        return BootstrapDropdown(self.right.li(), text)


class PaleYellowTable:
    def __init__(self, target, title, columns=[10, 60, 30]):
        if not target.hasTitle():
            target.setTitle(title)

        self.table = target.div("main").table("table", align="center").tbody()
        self.columns = columns

        colgroup = self.table.colgroup()
        for column in columns: colgroup.col(width="%d%%" % column)

        h1 = self.table.tr().td("h1", colspan=len(columns)).h1()
        h1.text(title)
        self.titleRight = h1.span("right")

        self.table.tr("spacer").td(colspan=len(self.columns))

    def addSection(self, title, extra=None):
        h2 = self.table.tr().td("h2", colspan=len(self.columns)).h2()
        h2.text(title)
        if extra is not None:
            h2.span().text(extra)

    def addItem(self, heading, value, description=None, buttons=None):
        row = self.table.tr("item")
        row.td("name").innerHTML(htmlutils.htmlify(heading).replace(" ", "&nbsp;") + ":")
        cell = row.td("value", colspan=2).preformatted()
        if callable(value): value(cell)
        else: cell.text(str(value))
        if buttons:
            div = cell.div("buttons")
            for label, onclick in buttons:
                div.button(onclick=onclick).text(label)
        if description is not None:
            self.table.tr("help").td(colspan=len(self.columns)).text(description)

    def addCentered(self, content=None):
        row = self.table.tr("centered")
        cell = row.td(colspan=len(self.columns))
        if callable(content): content(cell)
        elif content: cell.text(str(content))
        return cell

    def addSeparator(self):
        self.table.tr("separator").td(colspan=len(self.columns)).div()

def generateRepositorySelect(db, user, target, allow_selecting_none=False,
                             placeholder_text=None, selected=None, **attributes):
    select = target.select("repository-select", **attributes)

    cursor = db.cursor()
    cursor.execute("""SELECT id, name, path
                        FROM repositories
                    ORDER BY name""")

    rows = cursor.fetchall()

    if not rows:
        # Note: not honoring 'placeholder_text' here; callers typically don't
        # take into account the possibility that there are no repositories.
        select.setAttribute("data-placeholder", "No repositories")
        select.option(value="", selected="selected")
        return

    if selected is None:
        selected = user.getPreference(db, "defaultRepository")

    if not selected or allow_selecting_none:
        if placeholder_text is None:
            placeholder_text = "Select a repository"
        select.setAttribute("data-placeholder", placeholder_text)
        select.option(value="", selected="selected")

    highlighted_ids = set()

    cursor.execute("""SELECT DISTINCT repository
                        FROM filters
                       WHERE uid=%s""",
                   (user.id,))
    highlighted_ids.update(repository_id for (repository_id,) in cursor)

    cursor.execute("""SELECT DISTINCT repository
                        FROM branches
                        JOIN reviews ON (reviews.branch=branches.id)
                        JOIN reviewusers ON (reviewusers.review=reviews.id)
                       WHERE reviewusers.uid=%s
                         AND reviewusers.owner""",
                   (user.id,))
    highlighted_ids.update(repository_id for (repository_id,) in cursor)

    if not highlighted_ids or len(highlighted_ids) == len(rows):
        # Do not group options when there will be only one group.
        highlighted = select
        other = select
    else:
        highlighted = select.optgroup(label="Highlighted")
        other = select.optgroup(label="Other")

    html_format = ("<span class=repository-name>%s</span>"
                   "<span class=repository-path>%s</span>")

    for repository_id, name, path in rows:
        if repository_id in highlighted_ids:
            optgroup = highlighted
        else:
            optgroup = other

        if repository_id == selected or name == selected:
            is_selected = "selected"
        else:
            is_selected = None

        html = html_format % (name, path)

        option = optgroup.option("repository flex",
                                 value=name, selected=is_selected,
                                 data_text=name, data_html=html)
        option.text(name)
