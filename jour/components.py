import calendar
import datetime as dt
from typing import Literal

import flask
import htpy
import lxml.html
import markdown
import markupsafe

import jour.models as m
import jour.versions as v

CDN = "https://cdn.jsdelivr.net/npm"
BOOTSTRAP_CSS = htpy.link(
    href=f"{CDN}/bootstrap@{v.bs}/dist/css/bootstrap.min.css", rel="stylesheet"
)
BOOTSTRAP_ICONS_CSS = htpy.link(
    href=f"{CDN}/bootstrap-icons@{v.bi}/font/bootstrap-icons.min.css", rel="stylesheet"
)
BOOTSTRAP_JS = htpy.script(
    src=f"{CDN}/bootstrap@{v.bs}/dist/js/bootstrap.bundle.min.js"
)
HTMX_JS = htpy.script(src=f"{CDN}/htmx.org@{v.hx}/dist/htmx.js")


def _user_menu(email: str, *, is_admin: bool) -> htpy.Node:
    return htpy.div(".d-flex.justify-content-end.pt-3")[
        htpy.div(".dropdown")[
            htpy.button(
                ".btn.btn-outline-secondary.dropdown-toggle",
                aria_label="User menu",
                data_bs_toggle="dropdown",
                type="button",
            )[htpy.i(".bi-person-circle")],
            htpy.ul(".dropdown-menu.dropdown-menu-end")[
                htpy.li[htpy.span(".dropdown-item-text.text-body-secondary")[email]],
                htpy.li[htpy.hr(".dropdown-divider")],
                htpy.li[
                    htpy.a(".dropdown-item", href=flask.url_for("admin_users"))[
                        htpy.i(".bi-shield-lock.me-2"), "Admin"
                    ]
                ]
                if is_admin
                else None,
                htpy.li[
                    htpy.form(action=flask.url_for("sign_out"), method="post")[
                        htpy.button(".dropdown-item", type="submit")[
                            htpy.i(".bi-box-arrow-right.me-2"), "Sign out"
                        ]
                    ]
                ],
            ],
        ]
    ]


def _base(content: htpy.Node, *, wide: bool = False) -> htpy.Node:
    email = flask.g.get("email")
    column = (
        ".col-12.col-lg-10.col-xl-8.mx-auto"
        if wide
        else ".col-12.col-sm-9.col-md-7.col-lg-6.col-xl-5.col-xxl-4.mx-auto"
    )
    return htpy.html(lang="en")[
        htpy.head[
            htpy.meta(charset="utf-8"),
            htpy.meta(
                content="width=device-width, initial-scale=1, shrink-to-fit=no",
                name="viewport",
            ),
            htpy.title["Jour"],
            htpy.link(href=flask.url_for("favicon"), rel="icon"),
            BOOTSTRAP_CSS,
            BOOTSTRAP_ICONS_CSS,
        ],
        htpy.body[
            htpy.div(".container-fluid")[
                htpy.div(".row")[
                    htpy.div(column)[
                        _user_menu(email, is_admin=bool(flask.g.get("is_admin")))
                        if email
                        else None,
                        content,
                    ]
                ]
            ],
            BOOTSTRAP_JS,
            HTMX_JS,
        ],
    ]


def _md(t: str) -> markupsafe.Markup:
    """Take markdown-formatted text as input and render into HTML."""
    md = markdown.Markdown()
    doc = lxml.html.fragment_fromstring(md.convert(t), create_parent="div")
    for el in doc.xpath("//blockquote"):
        el.classes.update(("border-3", "border-start", "ps-2"))
    result = lxml.html.tostring(doc, encoding="unicode")
    return markupsafe.Markup(result)  # noqa: S704


Endpoint = Literal["day", "day_delete", "day_edit", "day_update", "month"]


def build_url(endpoint: Endpoint, d: dt.date) -> str:
    year = d.year
    month_ = d.strftime("%m")
    day_ = d.strftime("%d")
    if endpoint == "month":
        return flask.url_for(endpoint, year=year, month_=month_)
    elif endpoint in ["day", "day_delete", "day_edit", "day_update"]:
        return flask.url_for(endpoint, year=year, month_=month_, day_=day_)
    else:
        return flask.url_for("index")


def day(date: dt.date, entry_text: str) -> str:
    content = [
        htpy.div(".justify-content-between.pt-3.row")[
            htpy.div(".col-auto")[
                htpy.a(".btn.btn-outline-dark", href=build_url("month", date))[
                    htpy.i(".bi-chevron-left")
                ]
            ],
            htpy.div(".col-auto.text-center")[
                htpy.h1[date.day, date.strftime(" %b %Y")], htpy.p[date.strftime("%A")]
            ],
            htpy.div(".col-auto")[
                htpy.a(".btn.btn-outline-success", href=build_url("day_edit", date))[
                    htpy.i(".bi-pencil")
                ]
            ],
        ],
        htpy.div(".pt-3.row")[htpy.div(".col")[_md(entry_text)]],
    ]
    return str(_base(content))


def day_edit(date: dt.date, entry_text: str) -> str:
    content = [
        htpy.div(".justify-content-between.pt-3.row")[
            htpy.div(".col-auto")[
                htpy.a(".btn.btn-outline-dark", href=build_url("day", date))[
                    htpy.i(".bi-chevron-left")
                ]
            ],
            htpy.div(".col-auto.text-center")[
                htpy.h1[date.day, date.strftime(" %b %Y")], htpy.p[date.strftime("%A")]
            ],
            htpy.div(".col-auto")[
                htpy.button(".btn.btn-outline-success", form="form", type="submit")[
                    htpy.i(".bi-check-lg")
                ]
            ],
        ],
        htpy.div(".pt-3.row")[
            htpy.div(".col")[
                htpy.form("#form", action=build_url("day_update", date), method="post")[
                    htpy.div(".mb-3")[
                        htpy.textarea(
                            ".form-control",
                            aria_label="Journal entry",
                            name="entry-text",
                            rows=20,
                        )[entry_text]
                    ],
                    htpy.div(".mb-3")[
                        htpy.button(
                            ".btn.btn-outline-danger",
                            formaction=build_url("day_delete", date),
                            type="submit",
                        )[htpy.i(".bi-trash")]
                    ],
                ]
            ]
        ],
    ]
    return str(_base(content))


def favicon() -> str:
    # https://icons.getbootstrap.com/icons/journal-bookmark-fill/
    content = htpy.svg(
        ".bi.bi-journal-bookmark-fill",
        fill="#146c43",
        height=16,
        viewBox="0 0 16 16",
        width=16,
        xmlns="http://www.w3.org/2000/svg",
    )[
        htpy.path(
            d="M6 1h6v7a.5.5 0 0 1-.757.429L9 7.083 6.757 8.43A.5.5 0 0 1 6 8z",
            fill_rule="evenodd",
        ),
        htpy.path(
            d=(
                "M3 0h10a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2v-1h1v1a1 1 0 "
                "0 0 1 1h10a1 1 0 0 0 1-1V2a1 1 0 0 0-1-1H3a1 1 0 0 0-1 1v1H1V2a2 2 "
                "0 0 1 2-2"
            )
        ),
        htpy.path(
            d=(
                "M1 5v-.5a.5.5 0 0 1 1 0V5h.5a.5.5 0 0 1 0 1h-2a.5.5 0 0 1 0-1zm0 "
                "3v-.5a.5.5 0 0 1 1 0V8h.5a.5.5 0 0 1 0 1h-2a.5.5 0 0 1 0-1zm0 "
                "3v-.5a.5.5 0 0 1 1 0v.5h.5a.5.5 0 0 1 0 1h-2a.5.5 0 0 1 0-1z"
            )
        ),
    ]
    return str(content)


def knock() -> str:
    content = htpy.form(method="post")[
        htpy.input(".form-control", name="pw", type="password")
    ]
    return str(_base(content))


def landing() -> str:
    content = htpy.main(
        ".d-flex.flex-column.justify-content-center.min-vh-100.py-5.text-center"
    )[
        htpy.div(".mb-4")[
            htpy.i(
                ".bi.bi-journal-bookmark-fill.display-3.text-success",
                aria_hidden="true",
            )
        ],
        htpy.h1(".display-3.fw-semibold.mb-3")["Jour"],
        htpy.h2(".h3.fw-normal.mb-3")["A little space for every day."],
        htpy.p(".lead.mb-4.text-body-secondary")[
            "Capture your thoughts, remember the small moments, "
            "and come back to the days that matter."
        ],
        htpy.ul(
            ".d-flex.flex-wrap.gap-3.justify-content-center.list-unstyled"
            ".mb-5.small.text-body-secondary"
        )[
            htpy.li["Write in Markdown"],
            htpy.li["Browse by date"],
            htpy.li["Search past entries"],
        ],
        htpy.div[
            htpy.a(".btn.btn-success.btn-lg.px-5", href=flask.url_for("sign_in"))[
                "Sign in"
            ]
        ],
        htpy.p(".mt-3.mb-0.small.text-body-secondary")["Sign in to open your journal."],
    ]
    return str(_base(content))


def month(date: dt.date, dates_with_journals: list[dt.date]) -> str:
    start = date.replace(day=1)
    prev_month = start - dt.timedelta(days=1)
    next_month = start + dt.timedelta(days=31)
    today = dt.datetime.now(tz=dt.UTC).astimezone().date()
    cal = calendar.Calendar(firstweekday=calendar.SUNDAY)
    day_names = (calendar.day_name[i][0:2] for i in cal.iterweekdays())
    cal_tds = {}
    for w in cal.monthdatescalendar(start.year, start.month):
        for d in w:
            if d.month == start.month:
                if d > today:
                    cal_tds[d] = htpy.td(".text-secondary")[d.day]
                elif d in dates_with_journals:
                    cal_tds[d] = htpy.td(".table-success")[
                        htpy.a(
                            ".link-success.text-decoration-none",
                            href=build_url("day", d),
                        )[d.day]
                    ]
                else:
                    cal_tds[d] = htpy.td[
                        htpy.a(".text-decoration-none", href=build_url("day_edit", d))[
                            d.day
                        ]
                    ]
            else:
                cal_tds[d] = htpy.td
    content = [
        htpy.div(".align-items-center.justify-content-between.pt-3.row")[
            htpy.div(".col-auto")[
                htpy.a(
                    ".btn.btn-outline-primary",
                    href=build_url("month", prev_month),
                )[htpy.i(".bi-chevron-left")]
            ],
            htpy.div(".col-auto")[
                htpy.form[
                    htpy.div(".input-group")[
                        htpy.select(
                            ".form-select", hx_post=flask.url_for("go"), name="month"
                        )[
                            (
                                htpy.option(selected=(i == start.month), value=i)[m_]
                                for i, m_ in enumerate(calendar.month_name[1:], start=1)
                            )
                        ],
                        htpy.select(
                            ".form-select", hx_post=flask.url_for("go"), name="year"
                        )[
                            (
                                htpy.option(selected=(y == start.year))[y]
                                for y in range(today.year, 1982, -1)
                            )
                        ],
                    ]
                ]
            ],
            htpy.div(".col-auto")[
                htpy.a(
                    ".btn.btn-outline-primary",
                    href=build_url("month", next_month),
                )[htpy.i(".bi-chevron-right")]
                if start < today.replace(day=1)
                else htpy.button(".btn.invisible", disabled=True)[
                    markupsafe.Markup("&rarr;")
                ]
            ],
        ],
        htpy.div(".pt-3.row")[
            htpy.div(".col")[
                htpy.table(".fs-4.table.text-center")[
                    htpy.thead[htpy.tr[(htpy.th[d] for d in day_names)]],
                    htpy.tbody[
                        (
                            htpy.tr[(cal_tds[d] for d in w)]
                            for w in cal.monthdatescalendar(start.year, start.month)
                        )
                    ],
                ]
            ]
        ],
        htpy.div(".pt-3.row")[
            htpy.div(".col")[
                htpy.form[
                    htpy.input(
                        ".form-control",
                        aria_label="Search",
                        hx_post=flask.url_for("search"),
                        hx_target="#search-results",
                        hx_trigger="search, keyup changed delay:300ms",
                        name="q",
                        placeholder="Search...",
                        type="search",
                    )
                ]
            ]
        ],
        htpy.div(".pt-3.row")[htpy.div("#search-results.col")],
    ]
    return str(_base(content))


def search(results: list[m.journals.SearchResult], page: int) -> str:
    content: list[htpy.Node] = []
    for i, r in enumerate(results):
        if i < 11:
            content.append(
                htpy.div(".card.mb-2")[
                    htpy.div(".card-body")[
                        htpy.div(".row")[
                            htpy.div(".col-auto")[
                                htpy.h5(".card-title")[
                                    r.get("journal_date").isoformat(),
                                    htpy.small(".text-body-secondary")[
                                        r.get("journal_date").strftime(" / %A")
                                    ],
                                ]
                            ],
                            htpy.div(".col-auto.ms-auto")[
                                htpy.span(".badge.text-bg-primary")[r.get("score")]
                            ],
                        ],
                        htpy.p(".card-text")[
                            r.get("snip"),
                            htpy.a(
                                ".stretched-link",
                                href=build_url("day", r.get("journal_date")),
                            ),
                        ],
                    ]
                ]
            )
        else:
            content.append(
                htpy.div(
                    hx_include="form",
                    hx_post=flask.url_for("search", page=page + 1),
                    hx_swap="outerHTML",
                    hx_trigger="revealed",
                )[htpy.span(".htmx-indicator.spinner-border.spinner-border-sm")]
            )
    if not content:
        content.append("no results")
    return str(htpy.fragment[content])


def _admin_page(active: str, content: htpy.Node) -> str:
    def tab(endpoint: str, label: str, icon: str) -> htpy.Node:
        link_class = ".nav-link.active" if endpoint == active else ".nav-link"
        return htpy.li(".nav-item")[
            htpy.a(link_class, href=flask.url_for(endpoint))[
                htpy.i(f".{icon}.me-2"), label
            ]
        ]

    page = [
        htpy.div(".align-items-center.justify-content-between.pt-3.row")[
            htpy.div(".col-auto")[
                htpy.a(".btn.btn-outline-dark", href=flask.url_for("index"))[
                    htpy.i(".bi-chevron-left"), " Journal"
                ]
            ],
            htpy.div(".col-auto")[htpy.h1(".h3.mb-0")["Admin"]],
        ],
        htpy.ul(".mt-3.nav.nav-tabs")[
            tab("admin_users", "Users", "bi-people"),
            tab("admin_settings", "Settings", "bi-gear"),
        ],
        htpy.div(".pt-3")[content],
    ]
    return str(_base(page, wide=True))


def _fmt_ts(value: str | None) -> str:
    if not value:
        return "Never"
    return value[:16].replace("T", " ") + " UTC"


def _fmt_size(size: int) -> str:
    kb = 1024
    if size < kb:
        return f"{size} B"
    if size < kb * kb:
        return f"{size / kb:.0f} KB"
    return f"{size / kb / kb:.1f} MB"


def _user_action(
    user: dict, action: str, label: str, icon: str, style: str
) -> htpy.Node:
    attrs = {}
    if action == "delete":
        attrs["onclick"] = (
            "return confirm('Delete this user and all of their journal entries? "
            "This cannot be undone.')"
        )
    return htpy.form(
        ".d-inline",
        action=flask.url_for(f"admin_user_{action}", user_id=user["user_id"]),
        method="post",
    )[
        htpy.button(
            f".btn.btn-sm.btn-outline-{style}",
            aria_label=label,
            title=label,
            type="submit",
            **attrs,
        )[htpy.i(f".{icon}")]
    ]


def admin_users(users: list[dict]) -> str:
    def row(u: dict) -> htpy.Node:
        badges: list[htpy.Node] = []
        if u["is_admin"]:
            badges.append(htpy.span(".badge.text-bg-success.ms-2")["admin"])
        if u["is_disabled"]:
            badges.append(htpy.span(".badge.text-bg-secondary.ms-2")["disabled"])
        actions: list[htpy.Node] = []
        if not u["is_admin"]:
            if u["is_disabled"]:
                actions.append(
                    _user_action(u, "enable", "Enable", "bi-person-check", "success")
                )
            else:
                actions.append(
                    _user_action(u, "disable", "Disable", "bi-person-slash", "warning")
                )
            actions.append(_user_action(u, "delete", "Delete", "bi-trash", "danger"))
        return htpy.tr[
            htpy.td[u["email"], badges],
            htpy.td[_fmt_ts(u["created_at"])],
            htpy.td[_fmt_ts(u["last_sign_in_at"])],
            htpy.td(".text-end")["?" if u["entries"] is None else u["entries"]],
            htpy.td(".text-end")[_fmt_size(u["size"])],
            htpy.td(".text-end.text-nowrap")[actions],
        ]

    content = htpy.div(".table-responsive")[
        htpy.table(".align-middle.table.table-sm")[
            htpy.thead[
                htpy.tr[
                    htpy.th["Email"],
                    htpy.th["Created"],
                    htpy.th["Last sign-in"],
                    htpy.th(".text-end")["Entries"],
                    htpy.th(".text-end")["Size"],
                    htpy.th,
                ]
            ],
            htpy.tbody[(row(u) for u in users)],
        ]
    ]
    return _admin_page("admin_users", content)


def admin_settings(
    values: dict[str, str],
    errors: list[str],
    *,
    saved: bool = False,
    secret_is_set: bool = False,
) -> str:
    def field(name: str, label: str, hint: str = "", type_: str = "text") -> htpy.Node:
        return htpy.div(".mb-3")[
            htpy.label(".form-label", for_=name)[label],
            htpy.input(
                ".form-control",
                id=name,
                name=name,
                type=type_,
                value=values.get(name, ""),
            ),
            htpy.div(".form-text")[hint] if hint else None,
        ]

    policy = values.get("signup_policy") or "allowlist"
    policy_radios = [
        htpy.div(".form-check")[
            htpy.input(
                ".form-check-input",
                checked=(policy == value),
                id=f"policy-{value}",
                name="signup_policy",
                type="radio",
                value=value,
            ),
            htpy.label(".form-check-label", for_=f"policy-{value}")[text],
        ]
        for value, text in (
            ("allowlist", "Only the administrator and the allowlist below"),
            ("open", "Anyone who can sign in with the identity provider"),
        )
    ]
    secret_hint = (
        "A secret is set. Leave blank to keep it."
        if secret_is_set
        else "No secret is set."
    )
    content = htpy.form(method="post")[
        htpy.div(".alert.alert-success")["Settings saved."] if saved else None,
        htpy.div(".alert.alert-danger")[htpy.ul(".mb-0")[(htpy.li[e] for e in errors)]]
        if errors
        else None,
        htpy.h2(".h5")["Sign-up"],
        htpy.div(".mb-3")[
            htpy.div(".form-label")["Who can create an account"],
            policy_radios,
            htpy.div(".form-text")["Existing users are never affected by this."],
        ],
        htpy.div(".mb-4")[
            htpy.label(".form-label", for_="signup_allowlist")["Allowlist"],
            htpy.textarea(
                ".form-control", id="signup_allowlist", name="signup_allowlist", rows=4
            )[values.get("signup_allowlist", "")],
            htpy.div(".form-text")[
                "One entry per line: an email address, or @example.com for a domain."
            ],
        ],
        htpy.h2(".h5")["Administrator"],
        htpy.div(".mb-4")[
            field(
                "admin_email",
                "Admin email",
                "Changing this to another address removes your own admin access.",
                "email",
            )
        ],
        htpy.h2(".h5")["Identity provider"],
        field("openid_client_id", "Client ID"),
        field("openid_client_secret", "Client secret", secret_hint, "password"),
        field("openid_discovery_document", "Discovery document URL", type_="url"),
        htpy.div(".mb-3")[
            htpy.label(".form-label", for_="scheme")["Redirect URI scheme"],
            htpy.select(".form-select", id="scheme", name="scheme")[
                (
                    htpy.option(selected=(values.get("scheme") == s), value=s)[s]
                    for s in ("https", "http")
                )
            ],
        ],
        htpy.button(".btn.btn-success", type="submit")["Save"],
    ]
    return _admin_page("admin_settings", content)


def _message_page(title: str, text: str) -> str:
    content = htpy.div(".pt-3.row")[
        htpy.div(".col")[htpy.h1[title], htpy.p(".lead")[text]]
    ]
    return str(_base(content))


def forbidden() -> str:
    return _message_page("Forbidden", "You do not have access to this page.")


def not_invited() -> str:
    return _message_page(
        "Not invited",
        "This journal is not open to new accounts. Ask the administrator for access.",
    )


def account_disabled() -> str:
    return _message_page(
        "Account disabled", "Your account has been disabled by the administrator."
    )
