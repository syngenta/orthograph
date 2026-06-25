"""Shared Dash profile explorer — a self-contained mini-package for notebooks.

Import this from within the ``notebooks/`` directory (the conftest.py in that
folder adds it to ``sys.path``), or run it as a standalone script:

    python shared/dash_app.py

The application exposes a single ``create_app(profile)`` factory that accepts a
:class:`~orthograph.graph_profile.models.GraphProfile` and returns a configured
:class:`dash.Dash` instance.  It does not start a server; callers control the
lifecycle via ``app.run(debug=True)``.

Two entry-points are provided for 06.02:

- ``create_app_from_profile(profile)`` — use a pre-built profile object.
- ``create_app_from_connection(uri, username, password, backend)`` — inspect a
  live database and build the profile on the fly.  Requires the appropriate
  orthograph backend extra (``neo4j`` or ``gqlalchemy``).

The UI has three tabs:

1. **Overview** — node and relationship counts as a bar chart and summary table.
2. **Property detail** — completeness and type breakdown per node/rel type.
3. **Cardinality** — degree distribution per relationship type (when available).
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import dash

    from orthograph.graph_profile.models import GraphProfile

# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------


def _overview_tab(profile: "GraphProfile"):
    """Return the content for the Overview tab."""
    import dash_bootstrap_components as dbc
    from dash import dash_table, dcc, html

    node_rows = [
        {
            "Label": label,
            "Count": ntp.count,
            "Properties": len(ntp.property_profiles),
        }
        for label, ntp in sorted(profile.node_type_profiles.items())
    ]
    rel_rows = [
        {
            "Type": rt,
            "Count": rtp.count,
            "Source": rtp.source_label,
            "Target": rtp.target_label,
        }
        for rt, rtp in sorted(profile.rel_type_profiles.items())
    ]

    # Bar chart: node counts
    node_labels = [r["Label"] for r in node_rows]
    node_counts = [r["Count"] for r in node_rows]
    rel_types = [r["Type"] for r in rel_rows]
    rel_counts = [r["Count"] for r in rel_rows]

    fig = {
        "data": [
            {
                "type": "bar",
                "name": "Nodes",
                "x": node_labels,
                "y": node_counts,
                "marker": {"color": "#4C78A8"},
            },
            {
                "type": "bar",
                "name": "Relationships",
                "x": rel_types,
                "y": rel_counts,
                "marker": {"color": "#F58518"},
            },
        ],
        "layout": {
            "title": "Entity counts",
            "barmode": "group",
            "xaxis": {"title": "Label / Type"},
            "yaxis": {"title": "Count"},
            "legend": {"orientation": "h"},
            "margin": {"t": 40, "b": 60},
        },
    }

    return html.Div(
        [
            dcc.Graph(figure=fig, style={"height": "350px"}),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H5("Node types"),
                            dash_table.DataTable(
                                data=node_rows,
                                columns=[{"name": c, "id": c} for c in node_rows[0]]
                                if node_rows
                                else [],
                                style_table={"overflowX": "auto"},
                                style_cell={"textAlign": "left", "padding": "4px 8px"},
                                style_header={"fontWeight": "bold"},
                                page_size=10,
                            ),
                        ],
                        width=6,
                    ),
                    dbc.Col(
                        [
                            html.H5("Relationship types"),
                            dash_table.DataTable(
                                data=rel_rows,
                                columns=[{"name": c, "id": c} for c in rel_rows[0]]
                                if rel_rows
                                else [],
                                style_table={"overflowX": "auto"},
                                style_cell={"textAlign": "left", "padding": "4px 8px"},
                                style_header={"fontWeight": "bold"},
                                page_size=10,
                            ),
                        ],
                        width=6,
                    ),
                ]
            ),
        ]
    )


def _property_tab(profile: "GraphProfile"):
    """Return the content for the Property detail tab."""
    from dash import dash_table, html

    rows = []
    for label, ntp in sorted(profile.node_type_profiles.items()):
        for prop_name, pp in sorted(ntp.property_profiles.items()):
            rows.append(
                {
                    "Entity": label,
                    "Kind": "node",
                    "Property": prop_name,
                    "Completeness": f"{pp.completeness:.1%}",
                    "Present": pp.present_count,
                    "Total": pp.total_count,
                    "Types": ", ".join(pp.observed_types),
                    "Constraint": (
                        "yes"
                        if pp.constraint_required is True
                        else "no"
                        if pp.constraint_required is False
                        else "—"
                    ),
                }
            )
    for rt, rtp in sorted(profile.rel_type_profiles.items()):
        for prop_name, pp in sorted(rtp.property_profiles.items()):
            rows.append(
                {
                    "Entity": rt,
                    "Kind": "relationship",
                    "Property": prop_name,
                    "Completeness": f"{pp.completeness:.1%}",
                    "Present": pp.present_count,
                    "Total": pp.total_count,
                    "Types": ", ".join(pp.observed_types),
                    "Constraint": (
                        "yes"
                        if pp.constraint_required is True
                        else "no"
                        if pp.constraint_required is False
                        else "—"
                    ),
                }
            )

    if not rows:
        return html.P("No property profiles available.")

    columns = list(rows[0].keys())
    return html.Div(
        [
            html.H5("Property completeness and type breakdown"),
            dash_table.DataTable(
                data=rows,
                columns=[{"name": c, "id": c} for c in columns],
                style_table={"overflowX": "auto"},
                style_cell={"textAlign": "left", "padding": "4px 8px"},
                style_header={"fontWeight": "bold"},
                filter_action="native",
                sort_action="native",
                page_size=20,
                style_data_conditional=[
                    {
                        "if": {
                            "filter_query": "{Completeness} < '100.0%'",
                            "column_id": "Completeness",
                        },
                        "color": "#c0392b",
                    }
                ],
            ),
        ]
    )


def _cardinality_tab(profile: "GraphProfile"):
    """Return the content for the Cardinality tab."""
    from dash import dcc, html

    charts = []
    for rt, rtp in sorted(profile.rel_type_profiles.items()):
        cs = rtp.cardinality_stats
        if cs is None:
            continue

        min_v = cs.min if cs.min is not None else "—"
        max_v = cs.max if cs.max is not None else "—"
        mean_v = f"{cs.mean:.2f}" if cs.mean is not None else "—"
        std_v = f"{cs.std:.2f}" if cs.std is not None else "—"

        # Histogram if available
        fig_data = []
        if cs.histogram:
            degrees = sorted(
                cs.histogram.keys(),
                key=lambda x: float(x)
                if x.replace(".", "").lstrip("-").isdigit()
                else 0,
            )
            counts = [cs.histogram[d] for d in degrees]
            fig_data = [
                {
                    "type": "bar",
                    "x": degrees,
                    "y": counts,
                    "marker": {"color": "#4C78A8"},
                }
            ]

        charts.append(
            html.Div(
                [
                    html.H5(f"{rt}  ({rtp.source_label} → {rtp.target_label})"),
                    html.P(
                        f"min={min_v}  max={max_v}  mean={mean_v}  std={std_v}  "
                        f"(nodes assessed: {cs.count})"
                    ),
                    dcc.Graph(
                        figure={
                            "data": fig_data,
                            "layout": {
                                "title": f"{rt} — per-source degree distribution",
                                "xaxis": {"title": "Degree"},
                                "yaxis": {"title": "Node count"},
                                "margin": {"t": 40, "b": 50},
                            },
                        },
                        style={"height": "280px"},
                    )
                    if fig_data
                    else html.P("No per-degree histogram available."),
                ],
                style={"marginBottom": "24px"},
            )
        )

    if not charts:
        return html.P("No cardinality statistics available in this profile.")

    return html.Div(charts)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    profile: "GraphProfile", *, title: str = "Graph Profile Explorer"
) -> dash.Dash:
    """Build and return a :class:`dash.Dash` application from *profile*.

    The app is **not** started here.  Call ``app.run(debug=True)`` in the
    notebook or script entry-point.

    Parameters
    ----------
    profile:
        The :class:`~orthograph.graph_profile.models.GraphProfile` to explore.
    title:
        Browser title and H1 heading.
    """
    import dash
    import dash_bootstrap_components as dbc
    from dash import dcc, html

    app = dash.Dash(
        __name__,
        external_stylesheets=[dbc.themes.BOOTSTRAP],
        title=title,
    )

    source_line = profile.source
    ts = profile.timestamp.strftime("%Y-%m-%d %H:%M:%S") if profile.timestamp else "—"

    app.layout = dbc.Container(
        [
            html.H1(title, className="mt-3 mb-1"),
            html.P(
                [
                    html.Strong("Source: "),
                    source_line,
                    "  ",
                    html.Strong("Snapshot: "),
                    ts,
                ],
                className="text-muted",
            ),
            dcc.Tabs(
                [
                    dcc.Tab(
                        label="Overview",
                        children=[_overview_tab(profile)],
                        style={"padding": "12px"},
                    ),
                    dcc.Tab(
                        label="Properties",
                        children=[_property_tab(profile)],
                        style={"padding": "12px"},
                    ),
                    dcc.Tab(
                        label="Cardinality",
                        children=[_cardinality_tab(profile)],
                        style={"padding": "12px"},
                    ),
                ]
            ),
        ],
        fluid=True,
    )

    return app


# ---------------------------------------------------------------------------
# Live-DB convenience wrapper
# ---------------------------------------------------------------------------


def create_app_from_profile(profile: "GraphProfile", **kwargs) -> dash.Dash:
    """Convenience alias — same as :func:`create_app`."""
    return create_app(profile, **kwargs)


def create_app_from_connection(
    uri: str,
    username: str,
    password: str,
    *,
    backend: str = "neo4j",
    title: str = "Graph Profile Explorer",
) -> dash.Dash:
    """Inspect a live database and build the Dash app from the resulting profile.

    Parameters
    ----------
    uri:
        Database connection URI (e.g. ``\"bolt://localhost:7687\"``).
    username / password:
        Authentication credentials.
    backend:
        ``"neo4j"`` (default) or ``"memgraph"``.  The corresponding
        orthograph backend extra must be installed.
    title:
        Browser title for the app.

    Raises
    ------
    ImportError
        If the requested backend's driver package is not installed.
    ValueError
        If *backend* is not a recognised value.
    """
    if backend == "neo4j":
        from neo4j import GraphDatabase

        from orthograph.api.database import inspect

        driver = GraphDatabase.driver(uri, auth=(username, password))
        try:
            profile = inspect("neo4j", driver)
        finally:
            driver.close()

    elif backend == "memgraph":
        from gqlalchemy import Memgraph

        from orthograph.api.database import inspect

        host, _, port = uri.replace("bolt://", "").partition(":")
        mg = Memgraph(host=host, port=int(port) if port else 7687)
        profile = inspect("memgraph", mg)

    else:
        raise ValueError(f"Unknown backend {backend!r}. Use 'neo4j' or 'memgraph'.")

    return create_app(profile, title=title)


# ---------------------------------------------------------------------------
# Standalone entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Demo mode: use the shared canonical filmography profile.
    from profiles import FILMOGRAPHY_PROFILE

    _app = create_app(FILMOGRAPHY_PROFILE, title="Graph Profile Explorer — Demo")
    print("Starting demo server at http://127.0.0.1:8050/")
    _app.run(debug=True)
