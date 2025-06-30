import calendar
import datetime

import flask
import htpy
import lxml.html
import markdown
import markupsafe

import jour.versions as v


def _base(content: htpy.Node) -> htpy.Node:
    return htpy.html(lang="en")[
        htpy.head[
            htpy.meta(charset="utf-8"),
            htpy.meta(
                content="width=device-width, initial-scale=1, shrink-to-fit=no",
                name="viewport",
            ),
            htpy.title["Jour"],
            htpy.link(href=flask.url_for("favicon"), rel="icon"),
            htpy.link(
                href=f"https://cdn.jsdelivr.net/npm/bootstrap@{v.bs}/dist/css/bootstrap.min.css",
                rel="stylesheet",
            ),
            htpy.link(
                href=f"https://cdn.jsdelivr.net/npm/bootstrap-icons@{v.bi}/font/bootstrap-icons.min.css",
                rel="stylesheet",
            ),
        ],
        htpy.body[
            htpy.div(".container-fluid")[
                htpy.div(".row")[
                    htpy.div(
                        ".col-12.col-sm-9.col-md-7.col-lg-6.col-xl-5.col-xxl-4.mx-auto"
                    )[content]
                ]
            ],
            htpy.script(
                src=f"https://cdn.jsdelivr.net/npm/bootstrap@{v.bs}/dist/js/bootstrap.bundle.min.js"
            ),
            htpy.script(
                src=f"https://cdn.jsdelivr.net/npm/htmx.org@{v.hx}/dist/htmx.js"
            ),
        ],
    ]


def _md(t: str) -> markupsafe.Markup:
    """Take markdown-formatted text as input and render into HTML."""
    _md = markdown.Markdown()
    doc = lxml.html.fragment_fromstring(_md.convert(t), create_parent="div")
    for el in doc.xpath("//blockquote"):
        el.classes.update(("border-3", "border-start", "ps-2"))
    result = lxml.html.tostring(doc, encoding="unicode")
    return markupsafe.Markup(result)


def build_url(endpoint: str, d: datetime.date) -> str | None:
    year = d.year
    month_ = d.strftime("%m")
    day_ = d.strftime("%d")
    if endpoint in ["month"]:
        return flask.url_for(endpoint, year=year, month_=month_)
    if endpoint in ["day", "day_delete", "day_edit", "day_update"]:
        return flask.url_for(endpoint, year=year, month_=month_, day_=day_)


def day(date: datetime.date, entry_text: str) -> str:
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


def day_edit(date: datetime.date, entry_text: str) -> str:
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


def month(date: datetime.date, dates_with_journals: list[datetime.date]) -> str:
    start = date.replace(day=1)
    prev_month = start - datetime.timedelta(days=1)
    next_month = start + datetime.timedelta(days=31)
    today = datetime.date.today()
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
        htpy.div(".justify-content-between.pt-3.row")[
            htpy.div(".col-auto")[
                htpy.a(
                    ".btn.btn-outline-primary",
                    href=build_url("month", prev_month),
                )[htpy.i(".bi-chevron-left")]
            ],
            htpy.div(".col-auto")[
                htpy.h1[calendar.month_name[start.month], " ", start.year]
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


def not_authorized() -> str:
    content = htpy.div(".pt-3.row")[htpy.div(".col")[htpy.h1["Not authorized"]]]
    return str(_base(content))


def search(results: list[dict], page: int) -> str:
    content = []
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
