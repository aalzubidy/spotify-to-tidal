#!/usr/bin/env python3
"""
Report Generator for Spotify-to-Tidal Migration

Generates self-contained HTML reports based on the JSON data files.

Usage:
    # Spotify export report
    python3 generate.py --type export --input spotify-export.json --output spotify-report.html

    # Tidal import report
    python3 generate.py --type import --input tidal-import-result.json --output tidal-report.html

    # Combined migration report
    python3 generate.py --type migration --spotify spotify-export.json --tidal tidal-import-result.json --output migration-report.html
"""

import sys
import json
import os
import argparse
from datetime import datetime


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def _html_escape_map():
    """Build the HTML escape map at runtime to avoid source encoding issues."""
    return [
        ("&", "&" + "amp;"),
        ("<", "&" + "lt;"),
        (">", "&" + "gt;"),
        ('"', "&" + "quot;"),
        ("'", "&" + "#39;"),
    ]


def escape_html(text):
    """Escape text for HTML."""
    if not isinstance(text, str):
        text = str(text)
    for char, entity in _html_escape_map():
        text = text.replace(char, entity)
    return text


def confidence_bar(conf, label=""):
    """Generate a colored CSS bar for confidence scores."""
    if conf >= 90:
        color = "#22c55e"
    elif conf >= 70:
        color = "#eab308"
    elif conf >= 50:
        color = "#f97316"
    else:
        color = "#ef4444"

    return (
        '<div style="display: flex; align-items: center; gap: 8px;">'
        '<div style="flex: 1; height: 8px; background: #333; border-radius: 4px; overflow: hidden;">'
        '<div style="width: ' + str(conf) + '%; height: 100%; background: ' + color + '; border-radius: 4px;"></div>'
        '</div>'
        '<span style="color: ' + color + '; font-weight: 600; min-width: 45px;">' + str(conf) + '%</span>'
        + ('<span style="color: #888; font-size: 12px;">' + escape_html(str(label)) + '</span>' if label else '') +
        '</div>'
    )


def status_badge(status):
    """HTML badge for import status."""
    if status == "imported":
        return '<span style="color: #22c55e;">Imported</span>'
    elif status == "partial":
        return '<span style="color: #f97316;">Partial</span>'
    else:
        return '<span style="color: #ef4444;">Failed</span>'


def format_confidence_distribution(dist):
    """Generate a stats row for confidence distribution."""
    parts = []
    parts.append('<div style="display: flex; gap: 16px; flex-wrap: wrap;">')

    items = [
        ("High (>=90%)", dist.get("high", 0), "#22c55e"),
        ("Medium (70-89%)", dist.get("medium", 0), "#eab308"),
        ("Low (50-69%)", dist.get("low", 0), "#f97316"),
        ("Failed (<50%)", dist.get("failed", 0), "#ef4444"),
    ]
    for label, value, color in items:
        parts.append(
            '<div class="stat-box" style="border-left: 3px solid ' + color + ';">'
            '<div class="stat-label">' + label + '</div>'
            '<div class="stat-value" style="color: ' + color + ';">' + str(value) + '</div>'
            '</div>'
        )
    parts.append("</div>")
    return "\n".join(parts)


def build_export_report(data):
    """Build HTML body for a Spotify export report."""
    info = data.get("export_info", {})
    parts = []

    # Header
    parts.append(
        '<div class="report-header">'
        '<h1>Spotify Library Report</h1>'
        '<div class="report-meta">'
        '<span>User: ' + escape_html(info.get("spotify_display_name", "Unknown")) + '</span>'
        '<span>Exported: ' + escape_html(info.get("exported_at", "Unknown")) + '</span>'
        '<span>Country: ' + escape_html(info.get("spotify_country", "N/A")) + '</span>'
        '</div>'
        '</div>'
    )

    # Stats cards
    parts.append("<div class='stats-grid'>")

    stats = [
        ("Liked Tracks", info.get("total_tracks", len(data.get("liked_tracks", [])))),
        ("Saved Albums", info.get("total_albums", len(data.get("saved_albums", [])))),
        ("Playlists", info.get("total_playlists", len(data.get("playlists", [])))),
        ("Followed Artists", info.get("total_followed_artists", len(data.get("followed_artists", [])))),
        ("Top Artists", len(data.get("top_artists", []))),
        ("Top Tracks", len(data.get("top_tracks", []))),
        ("Saved Episodes", info.get("total_episodes", len(data.get("saved_episodes", [])))),
        ("Saved Shows", info.get("total_shows", len(data.get("saved_shows", [])))),
    ]

    for label, value in stats:
        parts.append(
            '<div class="stat-card">'
            '<div class="stat-value">' + str(value) + '</div>'
            '<div class="stat-label">' + label + '</div>'
            '</div>'
        )
    parts.append("</div>")

    # Liked Tracks
    tracks = data.get("liked_tracks", [])
    if tracks:
        parts.append(
            '<div class="section">'
            '<h2>Liked Tracks (' + str(len(tracks)) + ')</h2>'
            '<div class="scrollable">'
            '<table>'
            '<thead><tr>'
            '<th>#</th><th>Name</th><th>Artist(s)</th><th>Album</th><th>Duration</th><th>ISRC</th>'
            '</tr></thead>'
            '<tbody>'
        )
        for i, t in enumerate(tracks[:200]):
            artists = ", ".join(a.get("name", "") for a in t.get("artists", []))
            album = t.get("album", {}).get("name", "")
            dur = t.get("duration_ms", 0)
            mins, secs = divmod(dur // 1000, 60)
            isrc = t.get("isrc", "")
            parts.append(
                '<tr>'
                '<td>' + str(i + 1) + '</td>'
                '<td>' + escape_html(t.get("name", "")) + '</td>'
                '<td>' + escape_html(artists) + '</td>'
                '<td>' + escape_html(album) + '</td>'
                '<td>' + str(mins) + ':' + str(secs).zfill(2) + '</td>'
                '<td><code>' + escape_html(isrc) + '</code></td>'
                '</tr>'
            )
        parts.append("</tbody></table></div></div>")
        if len(tracks) > 200:
            parts.append(
                '<p style="color: #888; margin-top: 8px;">'
                'Showing 200 of ' + str(len(tracks)) + ' tracks. Full data in JSON export.'
                '</p>'
            )

    # Playlists
    playlists = data.get("playlists", [])
    if playlists:
        parts.append("<div class='section'><h2>Playlists</h2>")
        for pl in playlists:
            pl_name = escape_html(pl.get("name", "Unknown"))
            pl_count = len(pl.get("tracks", []))
            parts.append(
                '<div class="subsection">'
                '<h3>' + pl_name + ' <span style="color: #888; font-size: 14px;">(' + str(pl_count) + ' tracks)</span></h3>'
                '<p style="color: #666; font-size: 13px;">' + escape_html((pl.get("description", "") or "")[:200]) + '</p>'
                '</div>'
            )
        parts.append("</div>")

    # Followed Artists
    artists = data.get("followed_artists", [])
    if artists:
        parts.append(
            '<div class="section">'
            '<h2>Followed Artists (' + str(len(artists)) + ')</h2>'
            '<div class="artist-grid">'
        )
        for a in artists[:50]:
            name = escape_html(a.get("name", ""))
            genres = ", ".join(a.get("genres", [])[:3])
            parts.append(
                '<div class="artist-card">'
                '<div class="artist-name">' + name + '</div>'
                '<div class="artist-genres">' + escape_html(genres) + '</div>'
                '</div>'
            )
        parts.append("</div></div>")

    return "\n".join(parts)


def build_import_report(data):
    """Build HTML body for a Tidal import report."""
    info = data.get("import_info", {})
    summary = data.get("summary", {})
    conf = summary.get("confidence", {})
    parts = []

    # Header
    parts.append(
        '<div class="report-header">'
        '<h1>Tidal Import Report</h1>'
        '<div class="report-meta">'
        '<span>Imported: ' + escape_html(info.get("imported_at", "Unknown")) + '</span>'
        '<span>Spotify Export: ' + escape_html(info.get("spotify_export_file", "")) + '</span>'
        '</div>'
        '</div>'
    )

    imported = summary.get("imported", 0)
    failed = summary.get("failed", 0)
    total = imported + failed
    success_rate = round((imported / total) * 100, 1) if total > 0 else 0

    parts.append(
        '<div class="stats-grid">'
        '<div class="stat-card">'
        '<div class="stat-value">' + str(total) + '</div>'
        '<div class="stat-label">Total Items</div>'
        '</div>'
        '<div class="stat-card">'
        '<div class="stat-value" style="color: #22c55e;">' + str(imported) + '</div>'
        '<div class="stat-label">Imported</div>'
        '</div>'
        '<div class="stat-card">'
        '<div class="stat-value" style="color: #ef4444;">' + str(failed) + '</div>'
        '<div class="stat-label">Failed</div>'
        '</div>'
        '<div class="stat-card">'
        '<div class="stat-value" style="color: #3b82f6;">' + str(success_rate) + '%</div>'
        '<div class="stat-label">Success Rate</div>'
        '</div>'
        '<div class="stat-card">'
        '<div class="stat-value" style="color: #a78bfa;">' + format(conf.get("average", 0), ".1f") + '%</div>'
        '<div class="stat-label">Avg Confidence</div>'
        '</div>'
        '</div>'
    )

    # Confidence distribution
    parts.append(
        '<div class="section">'
        '<h2>Confidence Distribution</h2>'
        + format_confidence_distribution(conf) +
        '</div>'
    )

    # Liked Tracks section
    lt = data.get("liked_tracks", {})
    lt_items = lt.get("items", [])
    if lt_items:
        parts.append(
            '<div class="section">'
            '<h2>Liked Tracks (' + str(lt.get("imported", 0)) + ' imported / ' + str(lt.get("failed", 0)) + ' failed)</h2>'
            '<div class="scrollable">'
            '<table>'
            '<thead><tr>'
            '<th>#</th><th>Spotify Track</th><th>Confidence</th><th>Method</th><th>Status</th><th>Tidal Match</th>'
            '</tr></thead>'
            '<tbody>'
        )
        for i, item in enumerate(lt_items[:300]):
            sp = item.get("spotify_track", {})
            name = escape_html(sp.get("name", "Unknown"))
            conf_val = item.get("confidence", 0)
            method = item.get("match_method", "")
            status = item.get("status", "failed")
            tidal = item.get("tidal_track", {})
            tidal_name = escape_html(tidal.get("title", "")) if tidal else "-"

            parts.append(
                '<tr>'
                '<td>' + str(i + 1) + '</td>'
                '<td>' + name + '</td>'
                '<td>' + confidence_bar(conf_val, method) + '</td>'
                '<td style="color: #888; font-size: 12px;">' + escape_html(method) + '</td>'
                '<td>' + status_badge(status) + '</td>'
                '<td style="color: #888; font-size: 13px;">' + tidal_name + '</td>'
                '</tr>'
            )
        parts.append("</tbody></table></div></div>")

    # Failed items
    all_failed = [i for i in lt_items if i.get("status") != "imported"]
    if all_failed:
        parts.append(
            '<div class="section">'
            '<h2>Failed Items (' + str(len(all_failed)) + ')</h2>'
            '<div class="alert alert-danger">'
            'These items could not be matched or imported. You may want to search for them manually on Tidal.'
            '</div>'
            '<div class="scrollable">'
            '<table>'
            '<thead><tr><th>#</th><th>Name</th><th>Reason</th></tr></thead>'
            '<tbody>'
        )
        for i, item in enumerate(all_failed):
            sp = item.get("spotify_track", {})
            name = escape_html(sp.get("name", "Unknown"))
            reason = escape_html(item.get("reason", "Unknown"))
            parts.append(
                '<tr><td>' + str(i + 1) + '</td><td>' + name + '</td><td>' + reason + '</td></tr>'
            )
        parts.append("</tbody></table></div></div>")

    # Playlists
    playlists = data.get("playlists", [])
    if playlists:
        parts.append("<div class='section'><h2>Playlists</h2>")
        for pl in playlists:
            sp_pl = pl.get("spotify_playlist", {})
            pl_name = escape_html(sp_pl.get("name", "Unknown"))
            imported_t = pl.get("tracks_imported", 0)
            failed_t = pl.get("tracks_failed", 0)
            total_t = imported_t + failed_t
            status = pl.get("status", "failed")
            conf_data = pl.get("confidence", {})
            bar_rate = round((imported_t / total_t) * 100) if total_t else 0
            parts.append(
                '<div class="subsection">'
                '<h3>' + pl_name + ' ' + status_badge(status) + '</h3>'
                '<div style="margin: 8px 0;">'
                '<span style="color: #22c55e;">' + str(imported_t) + ' imported</span>'
                '<span style="margin: 0 8px;">|</span>'
                '<span style="color: #ef4444;">' + str(failed_t) + ' failed</span>'
                '<span style="margin: 0 8px;">|</span>'
                '<span style="color: #a78bfa;">Avg confidence: ' + format(conf_data.get("average", 0), ".1f") + '%</span>'
                '</div>'
                + confidence_bar(bar_rate, "success rate") +
                '</div>'
            )
        parts.append("</div>")

    return "\n".join(parts)


def build_migration_report(spotify_data, tidal_data):
    """Build a combined migration overview report."""
    sp_info = spotify_data.get("export_info", {})
    td_info = tidal_data.get("import_info", {})
    td_summary = tidal_data.get("summary", {})
    td_conf = td_summary.get("confidence", {})

    imported = td_summary.get("imported", 0)
    failed = td_summary.get("failed", 0)
    total = imported + failed
    success_rate = round((imported / total) * 100, 1) if total > 0 else 0

    parts = []
    parts.append(
        '<div class="report-header">'
        '<h1>Spotify to Tidal Migration Report</h1>'
        '<div class="report-meta">'
        '<span>Spotify Export: ' + escape_html(sp_info.get("exported_at", "Unknown")) + '</span>'
        '<span>Tidal Import: ' + escape_html(td_info.get("imported_at", "Unknown")) + '</span>'
        '</div>'
        '</div>'
    )

    parts.append(
        '<div class="stats-grid">'
        '<div class="stat-card">'
        '<div class="stat-value" style="color: #1DB954;">' + escape_html(str(sp_info.get("total_tracks", 0))) + '</div>'
        '<div class="stat-label">Spotify Tracks</div>'
        '</div>'
        '<div class="stat-card">'
        '<div class="stat-value" style="color: #3b82f6;">' + str(total) + '</div>'
        '<div class="stat-label">Items Processed</div>'
        '</div>'
        '<div class="stat-card">'
        '<div class="stat-value" style="color: #22c55e;">' + str(imported) + '</div>'
        '<div class="stat-label">Imported</div>'
        '</div>'
        '<div class="stat-card">'
        '<div class="stat-value" style="color: #ef4444;">' + str(failed) + '</div>'
        '<div class="stat-label">Failed</div>'
        '</div>'
        '<div class="stat-card">'
        '<div class="stat-value" style="color: #3b82f6;">' + str(success_rate) + '%</div>'
        '<div class="stat-label">Success Rate</div>'
        '</div>'
        '<div class="stat-card">'
        '<div class="stat-value" style="color: #a78bfa;">' + format(td_conf.get("average", 0), ".1f") + '%</div>'
        '<div class="stat-label">Avg Confidence</div>'
        '</div>'
        '</div>'
    )

    parts.append(
        '<div class="section">'
        '<h2>Confidence Distribution</h2>'
        + format_confidence_distribution(td_conf) +
        '</div>'
    )

    if failed == 0:
        migration_status = "Complete"
    else:
        migration_status = "Complete with failures"

    parts.append(
        '<div class="section" style="text-align: center; padding: 32px;">'
        '<p style="font-size: 18px; margin-bottom: 16px;">'
        'Overall Migration: ' + migration_status +
        '</p>'
        '<p style="color: #888;">'
        + str(success_rate) + '% of items were successfully migrated from Spotify to Tidal. '
        + (str(failed) + ' items could not be matched.' if failed > 0 else 'All items matched successfully!') +
        '</p>'
        '</div>'
    )

    return "\n".join(parts)


def get_css():
    """Return the embedded CSS for all report types."""
    return """/* Spotify-to-Tidal Migration Report Styles */
:root {
    --bg: #0a0a0a;
    --card-bg: #141414;
    --section-bg: #1a1a1a;
    --text: #e5e5e5;
    --text-muted: #888;
    --border: #2a2a2a;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    max-width: 1200px;
    margin: 0 auto;
    padding: 24px 16px;
}
.report-header {
    text-align: center;
    padding: 32px 0;
    border-bottom: 1px solid var(--border);
    margin-bottom: 32px;
}
.report-header h1 {
    font-size: 32px;
    margin-bottom: 12px;
    background: linear-gradient(135deg, #1DB954 0%, #00ffff 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}
.report-meta {
    display: flex;
    justify-content: center;
    gap: 24px;
    color: var(--text-muted);
    font-size: 13px;
    flex-wrap: wrap;
}
.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 16px;
    margin-bottom: 32px;
}
.stat-card {
    background: var(--card-bg);
    border-radius: 12px;
    padding: 20px;
    text-align: center;
    border: 1px solid var(--border);
}
.stat-value {
    font-size: 32px;
    font-weight: 700;
    margin-bottom: 4px;
}
.stat-label {
    font-size: 13px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.stat-box {
    background: var(--card-bg);
    border-radius: 8px;
    padding: 12px 16px;
    min-width: 120px;
}
.section {
    background: var(--section-bg);
    border-radius: 12px;
    padding: 24px;
    margin-bottom: 24px;
    border: 1px solid var(--border);
}
.section h2 {
    font-size: 20px;
    margin-bottom: 16px;
    color: var(--text);
}
.subsection {
    background: var(--card-bg);
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 12px;
    border: 1px solid var(--border);
}
.subsection h3 {
    font-size: 16px;
    margin-bottom: 8px;
}
.scrollable { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th {
    text-align: left;
    padding: 10px 12px;
    border-bottom: 2px solid var(--border);
    color: var(--text-muted);
    font-weight: 600;
    font-size: 12px;
    text-transform: uppercase;
}
td { padding: 10px 12px; border-bottom: 1px solid var(--border); }
tr:hover { background: rgba(255, 255, 255, 0.02); }
code {
    background: rgba(255, 255, 255, 0.05);
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 12px;
}
.artist-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 12px;
}
.artist-card {
    background: var(--card-bg);
    border-radius: 8px;
    padding: 12px;
    border: 1px solid var(--border);
}
.artist-name { font-weight: 600; margin-bottom: 4px; }
.artist-genres { font-size: 12px; color: var(--text-muted); }
.alert { border-radius: 8px; padding: 16px; margin-bottom: 16px; }
.alert-danger {
    background: rgba(239, 68, 68, 0.1);
    border: 1px solid rgba(239, 68, 68, 0.3);
    color: #fca5a5;
}
.footer {
    text-align: center;
    padding: 24px;
    color: var(--text-muted);
    font-size: 12px;
    border-top: 1px solid var(--border);
    margin-top: 32px;
}
@media (max-width: 768px) {
    body { padding: 12px 8px; }
    .stats-grid { grid-template-columns: repeat(2, 1fr); }
}"""


def build_html(body, title):
    """Wrap body content in a full HTML document."""
    return (
        '<!DOCTYPE html>\n'
        '<html lang="en">\n'
        '<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        '<title>' + escape_html(title) + '</title>\n'
        '<style>\n' + get_css() + '\n</style>\n'
        '</head>\n'
        '<body>\n'
        + body + '\n'
        '<div class="footer">\n'
        '<p>Spotify to Tidal Migration Tool | Generated: ' + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + '</p>\n'
        '</div>\n'
        '</body>\n'
        '</html>'
    )


def build_verification_report(data):
    """Build HTML body for a Tidal verification report."""
    info = data.get("verification_info", {})
    summary = data.get("summary", {})
    tidal_state = info.get("tidal_state", {})
    parts = []

    # Header
    parts.append(
        '<div class="report-header">'
        '<h1>Tidal Import Verification Report</h1>'
        '<div class="report-meta">'
        '<span>Verified: ' + escape_html(info.get("verified_at", "Unknown")) + '</span>'
        '<span>Spotify Export: ' + escape_html(info.get("spotify_export_file", "")) + '</span>'
        '</div>'
        '</div>'
    )

    # Overall health
    health = summary.get("health_percentage", 0)
    passed = summary.get("verification_passed", False)
    health_color = "#22c55e" if passed else "#ef4444"

    parts.append(
        '<div class="stats-grid">'
        '<div class="stat-card">'
        '<div class="stat-value" style="color: ' + health_color + ';">' + format(health, ".1f") + '%</div>'
        '<div class="stat-label">Health Score</div>'
        '</div>'
        '<div class="stat-card">'
        '<div class="stat-value" style="color: #22c55e;">' + str(summary.get("total_verified", 0)) + '</div>'
        '<div class="stat-label">Verified</div>'
        '</div>'
        '<div class="stat-card">'
        '<div class="stat-value" style="color: #ef4444;">' + str(summary.get("total_missing", 0)) + '</div>'
        '<div class="stat-label">Missing</div>'
        '</div>'
        '<div class="stat-card">'
        '<div class="stat-value" style="color: #f97316;">' + str(summary.get("total_mismatch", 0)) + '</div>'
        '<div class="stat-label">Mismatches</div>'
        '</div>'
        '<div class="stat-card">'
        '<div class="stat-value" style="color: #3b82f6;">'
        + str(tidal_state.get("total_favorite_tracks", 0)) + '</div>'
        '<div class="stat-label">Tidal Tracks</div>'
        '</div>'
        '<div class="stat-card">'
        '<div class="stat-value" style="color: #a78bfa;">'
        + str(tidal_state.get("total_playlists", 0)) + '</div>'
        '<div class="stat-label">Tidal Playlists</div>'
        '</div>'
        '</div>'
    )

    # Status badge
    status_class = "success" if passed else "failed"
    status_icon = "✅" if passed else "⚠️"
    status_text = "All items verified successfully!" if passed else "Discrepancies found — review the details below."
    parts.append(
        '<div class="section" style="text-align: center;">'
        '<p style="font-size: 20px; margin-bottom: 8px;">' + status_icon + ' Verification: <strong>' + status_text + '</strong></p>'
        '</div>'
    )

    # Liked Tracks verification
    lt = data.get("liked_tracks", {})
    lt_items = lt.get("items", [])
    lt_missing = [i for i in lt_items if i.get("actual_status") == "missing"]
    if lt_items:
        parts.append(
            '<div class="section">'
            '<h2>Liked Tracks (' + str(lt.get("verified", 0)) + ' verified / ' + str(lt.get("missing", 0)) + ' missing)</h2>'
        )
        if lt_missing:
            parts.append(
                '<div class="alert alert-danger">'
                + str(len(lt_missing)) + ' tracks were marked as imported but NOT found in Tidal favorites. They may need re-importing.'
                '</div>'
                '<div class="scrollable">'
                '<table>'
                '<thead><tr><th>#</th><th>Track</th><th>Expected Tidal ID</th><th>Issue</th></tr></thead>'
                '<tbody>'
            )
            for i, item in enumerate(lt_missing):
                sp = item.get("spotify_track", {})
                name = escape_html(sp.get("name", "Unknown"))
                tid = escape_html(str(item.get("expected_tidal_id", "N/A")))
                issue = escape_html(item.get("issue", ""))
                parts.append(
                    '<tr><td>' + str(i + 1) + '</td><td>' + name + '</td>'
                    '<td><code>' + tid + '</code></td><td>' + issue + '</td></tr>'
                )
            parts.append("</tbody></table></div>")
        parts.append("</div>")

    # Saved Albums verification
    sa = data.get("saved_albums", {})
    sa_items = sa.get("items", [])
    sa_missing = [i for i in sa_items if i.get("actual_status") == "missing"]
    if sa_missing:
        parts.append(
            '<div class="section">'
            '<h2>Saved Albums (' + str(sa.get("verified", 0)) + ' verified / ' + str(sa.get("missing", 0)) + ' missing)</h2>'
            '<div class="alert alert-danger">'
            + str(len(sa_missing)) + ' albums were marked as imported but NOT found in Tidal.'
            '</div>'
            '<div class="scrollable">'
            '<table>'
            '<thead><tr><th>#</th><th>Album</th><th>Expected Tidal ID</th><th>Issue</th></tr></thead>'
            '<tbody>'
        )
        for i, item in enumerate(sa_missing):
            sp = item.get("spotify_album", {})
            name = escape_html(sp.get("name", "Unknown"))
            tid = escape_html(str(item.get("expected_tidal_id", "N/A")))
            issue = escape_html(item.get("issue", ""))
            parts.append(
                '<tr><td>' + str(i + 1) + '</td><td>' + name + '</td>'
                '<td><code>' + tid + '</code></td><td>' + issue + '</td></tr>'
            )
        parts.append("</tbody></table></div></div>")

    # Followed Artists verification
    fa = data.get("followed_artists", {})
    fa_items = fa.get("items", [])
    fa_missing = [i for i in fa_items if i.get("actual_status") == "missing"]
    if fa_missing:
        parts.append(
            '<div class="section">'
            '<h2>Followed Artists (' + str(fa.get("verified", 0)) + ' verified / ' + str(fa.get("missing", 0)) + ' missing)</h2>'
            '<div class="alert alert-danger">'
            + str(len(fa_missing)) + ' artists were marked as followed but NOT found in Tidal.'
            '</div>'
            '<div class="scrollable">'
            '<table>'
            '<thead><tr><th>#</th><th>Artist</th><th>Expected Tidal ID</th><th>Issue</th></tr></thead>'
            '<tbody>'
        )
        for i, item in enumerate(fa_missing):
            sp = item.get("spotify_artist", {})
            name = escape_html(sp.get("name", "Unknown"))
            tid = escape_html(str(item.get("expected_tidal_id", "N/A")))
            issue = escape_html(item.get("issue", ""))
            parts.append(
                '<tr><td>' + str(i + 1) + '</td><td>' + name + '</td>'
                '<td><code>' + tid + '</code></td><td>' + issue + '</td></tr>'
            )
        parts.append("</tbody></table></div></div>")

    # Playlists verification
    pl_verifications = data.get("playlists", [])
    if pl_verifications:
        parts.append("<div class='section'><h2>Playlists</h2>")
        for pl in pl_verifications:
            sp_pl = pl.get("spotify_playlist", {})
            pl_name = escape_html(sp_pl.get("name", "Unknown"))
            pl_status = pl.get("actual_status", "unknown")
            pl_issue = pl.get("issue", "")
            track_stats = pl.get("tracks", {})
            t_verified = track_stats.get("verified", 0)
            t_missing = track_stats.get("missing", 0)
            t_mismatch = track_stats.get("mismatch", 0)

            if pl_status == "found" or pl_status == "confirmed_failed":
                status_color = "#22c55e" if t_missing == 0 else "#f97316"
                status_text = "Found ✅" if t_missing == 0 else "Partial ⚠️"
            elif pl_status == "missing":
                status_color = "#ef4444"
                status_text = "Missing ❌"
            else:
                status_color = "#ef4444"
                status_text = pl_status

            parts.append(
                '<div class="subsection">'
                '<h3>' + pl_name + ' <span style="color: ' + status_color + ';">' + status_text + '</span></h3>'
                '<div style="margin: 8px 0;">'
                '<span style="color: #22c55e;">' + str(t_verified) + ' verified</span>'
                '<span style="margin: 0 8px;">|</span>'
                '<span style="color: #ef4444;">' + str(t_missing) + ' missing</span>'
                '<span style="margin: 0 8px;">|</span>'
                '<span style="color: #f97316;">' + str(t_mismatch) + ' mismatches</span>'
                '</div>'
            )
            if pl_issue:
                parts.append('<p style="color: #ef4444; font-size: 13px;">Issue: ' + escape_html(pl_issue) + '</p>')

            # List missing tracks for this playlist
            pl_track_items = track_stats.get("items", [])
            pl_missing_tracks = [t for t in pl_track_items if t.get("actual_status") == "missing"]
            if pl_missing_tracks:
                parts.append(
                    '<div style="margin-top: 8px; font-size: 12px; color: #888;">'
                    '<strong>Missing tracks:</strong> '
                    + escape_html(", ".join(t.get("spotify_track", {}).get("name", "?") for t in pl_missing_tracks[:20]))
                    + ('...' if len(pl_missing_tracks) > 20 else '')
                    + '</div>'
                )

            parts.append("</div>")
        parts.append("</div>")

    # Final status
    if passed:
        parts.append(
            '<div class="section" style="text-align: center; padding: 32px; border-color: #22c55e;">'
            '<p style="font-size: 18px; color: #22c55e;">✅ All items verified — import is healthy!</p>'
            '</div>'
        )
    else:
        parts.append(
            '<div class="section" style="text-align: center; padding: 32px; border-color: #ef4444;">'
            '<p style="font-size: 18px; color: #ef4444;">⚠️ ' + str(summary.get("total_missing", 0))
            + ' items are missing. Consider re-running the import or adding them manually.</p>'
            '</div>'
        )

    return "\n".join(parts)


def build_missing_tracks_report(sp_data, cache):
    """Build HTML body for a missing-tracks report.

    sp_data: spotify-export.json (flat track structure: t["isrc"], t["name"], t["artists"], t["album"])
    cache:   tidal-match-cache.json (keys: "tracks" for hits, "track_misses" for misses)
    """
    miss_isrcs = set(cache.get("track_misses", {}).keys())
    hits = cache.get("tracks", {})

    # Build ISRC -> display info from Spotify export
    info = {}
    for t in sp_data.get("liked_tracks", []):
        isrc = (t.get("isrc") or "").upper().strip()
        if isrc and isrc in miss_isrcs and isrc not in info:
            info[isrc] = {
                "name":     t.get("name", "Unknown"),
                "artist":   ", ".join(a.get("name", "") for a in t.get("artists", [])),
                "album":    (t.get("album") or {}).get("name", ""),
                "playlists": [],
            }
    for pl in sp_data.get("playlists", []):
        pl_name = pl.get("name", "")
        for t in pl.get("tracks", []):
            if not t:
                continue
            isrc = (t.get("isrc") or "").upper().strip()
            if isrc and isrc in miss_isrcs:
                if isrc not in info:
                    info[isrc] = {
                        "name":     t.get("name", "Unknown"),
                        "artist":   ", ".join(a.get("name", "") for a in t.get("artists", [])),
                        "album":    (t.get("album") or {}).get("name", ""),
                        "playlists": [],
                    }
                if pl_name and pl_name not in info[isrc]["playlists"]:
                    info[isrc]["playlists"].append(pl_name)
    for isrc in miss_isrcs:
        if isrc not in info:
            info[isrc] = {"name": "(ISRC: " + isrc + ")", "artist": "", "album": "", "playlists": []}

    rows = sorted(info.values(), key=lambda x: (x["artist"].lower(), x["name"].lower()))
    total_isrcs = len(hits) + len(miss_isrcs)
    match_rate = round(len(hits) / total_isrcs * 100, 1) if total_isrcs else 0

    def rate_color(r):
        return "#22c55e" if r >= 97 else ("#eab308" if r >= 90 else "#ef4444")

    parts = []
    parts.append(
        '<div class="report-header">'
        '<h1>Tracks Not Found on Tidal</h1>'
        '<div class="report-meta">'
        '<span>' + str(len(rows)) + ' tracks unavailable in Tidal catalog or region-locked</span>'
        '</div>'
        '</div>'
    )
    parts.append(
        '<div class="stats-grid">'
        '<div class="stat-card"><div class="stat-value" style="color:#ef4444;">' + str(len(rows)) + '</div>'
        '<div class="stat-label">Missing tracks</div></div>'
        '<div class="stat-card"><div class="stat-value" style="color:#22c55e;">' + str(len(hits)) + '</div>'
        '<div class="stat-label">Matched tracks</div></div>'
        '<div class="stat-card"><div class="stat-value">' + str(total_isrcs) + '</div>'
        '<div class="stat-label">Total unique ISRCs</div></div>'
        '<div class="stat-card"><div class="stat-value" style="color:' + rate_color(match_rate) + ';">' + str(match_rate) + '%</div>'
        '<div class="stat-label">Match rate</div></div>'
        '</div>'
    )
    rows_html = ""
    for r in rows:
        pl_badges = "".join(
            '<span style="display:inline-block;background:#1a1a2e;border-radius:4px;padding:1px 7px;font-size:11px;margin:1px;">'
            + escape_html(p) + '</span>'
            for p in r["playlists"]
        ) or '<span style="color:#888;font-size:11px">liked only</span>'
        rows_html += (
            '<tr>'
            '<td><strong>' + escape_html(r["name"]) + '</strong></td>'
            '<td>' + escape_html(r["artist"]) + '</td>'
            '<td style="color:#888;font-size:12px">' + escape_html(r["album"]) + '</td>'
            '<td>' + pl_badges + '</td>'
            '</tr>'
        )
    parts.append(
        '<div class="section">'
        '<input type="text" id="search" placeholder="Search by track, artist, album, or playlist…"'
        ' oninput="filterTable(this.value)"'
        ' style="background:#141414;border:1px solid #2a2a2a;border-radius:6px;padding:8px 14px;'
        'color:#e5e5e5;font-size:14px;outline:none;width:100%;margin-bottom:16px;">'
        '<table class="data-table">'
        '<thead><tr><th>Track</th><th>Artist</th><th>Album</th><th>In playlists</th></tr></thead>'
        '<tbody id="tbody">' + rows_html + '</tbody>'
        '</table>'
        '</div>'
        '<script>function filterTable(q){q=q.toLowerCase();'
        'document.querySelectorAll(\'#tbody tr\').forEach(function(r){'
        'r.style.display=r.textContent.toLowerCase().includes(q)?\'\':\'none\';});}'
        '</script>'
    )
    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description="Generate migration reports")
    parser.add_argument("--type", required=True, choices=["export", "import", "migration", "verify", "missing"],
                        help="Type of report to generate")
    parser.add_argument("--input", help="Input JSON file (for export/import/verify reports)")
    parser.add_argument("--spotify", help="Spotify export JSON (for migration/missing reports)")
    parser.add_argument("--tidal", help="Tidal import result JSON (for migration report)")
    parser.add_argument("--cache", help="Tidal match cache JSON (for missing report)")
    parser.add_argument("--output", required=True, help="Output HTML file path")
    args = parser.parse_args()

    if args.type == "export":
        if not args.input:
            print("Error: --input required for export report", file=sys.stderr)
            sys.exit(1)
        data = load_json(args.input)
        body = build_export_report(data)
        title = "Spotify Library Report - " + str(data.get("export_info", {}).get("spotify_display_name", "User"))

    elif args.type == "import":
        if not args.input:
            print("Error: --input required for import report", file=sys.stderr)
            sys.exit(1)
        data = load_json(args.input)
        body = build_import_report(data)
        title = "Tidal Import Report"

    elif args.type == "migration":
        if not args.spotify or not args.tidal:
            print("Error: --spotify and --tidal required for migration report", file=sys.stderr)
            sys.exit(1)
        sp_data = load_json(args.spotify)
        td_data = load_json(args.tidal)
        body = build_migration_report(sp_data, td_data)
        title = "Spotify to Tidal Migration Report"

    elif args.type == "verify":
        if not args.input:
            print("Error: --input required for verify report", file=sys.stderr)
            sys.exit(1)
        data = load_json(args.input)
        body = build_verification_report(data)
        title = "Tidal Import Verification Report"

    elif args.type == "missing":
        if not args.spotify or not args.cache:
            print("Error: --spotify and --cache required for missing report", file=sys.stderr)
            sys.exit(1)
        sp_data = load_json(args.spotify)
        cache = load_json(args.cache)
        body = build_missing_tracks_report(sp_data, cache)
        title = "Tracks Not Found on Tidal"

    html = build_html(body, title)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        f.write(html)

    print("Report saved to: " + args.output)


if __name__ == "__main__":
    main()