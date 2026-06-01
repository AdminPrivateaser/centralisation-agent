"""Create audit pages in Notion database."""
import os
from datetime import date
from typing import Optional
from notion_client import AsyncClient

NOTION_DB_ID = os.getenv("NOTION_DB_ID", "f0f6bce981e74219af0d612ae90870a8")


def _score_select(score: int) -> str:
    if score >= 80:
        return "🟢 Excellent (≥80)"
    elif score >= 50:
        return "🟠 Moyen (50-79)"
    return "🔴 Faible (<50)"


def _quanti_select(quanti_ok: Optional[bool]) -> str:
    if quanti_ok is None:
        return "N/A"
    return "✅ OK" if quanti_ok else "❌ KO"


def _channel_emoji(channel: str) -> str:
    return {"website": "🌐", "gmb": "📍", "rwg": "🔵", "instagram": "📸"}.get(channel, "📦")


def _channel_name(channel: str) -> str:
    return {"website": "Site Web", "gmb": "Google My Business", "rwg": "Reserve with Google", "instagram": "Instagram"}.get(channel, channel)


def _color_to_notion(color: str) -> str:
    return {"green": "green", "orange": "orange", "red": "red"}.get(color, "default")


def _build_channel_blocks(channel_key: str, channel_data: dict) -> list:
    if not channel_data.get("available", True):
        return []

    emoji = _channel_emoji(channel_key)
    name = _channel_name(channel_key)
    quanti_ok = channel_data.get("quanti_ok", False)
    quanti_emoji = "🟢" if quanti_ok else "❌"
    quali = channel_data.get("quali_score", 0)
    quali_max = channel_data.get("quali_max", 0)
    quali_color = "green" if quali >= quali_max * 0.8 else ("orange" if quali >= quali_max * 0.5 else "red")
    quali_emoji = "🟢" if quali_color == "green" else ("🟠" if quali_color == "orange" else "🔴")

    blocks = [
        {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": f"{emoji} {name}"}}]}},
        {
            "type": "callout",
            "callout": {
                "rich_text": [
                    {"type": "text", "text": {"content": f"Quanti : {quanti_emoji} {'setup min OK' if quanti_ok else 'setup min KO'}\nQuali : {quali_emoji} {quali} / {quali_max} pts"}},
                ],
                "color": "gray_background",
                "icon": {"type": "emoji", "emoji": emoji}
            }
        },
    ]

    # Criteria table
    criteria = channel_data.get("criteria", [])
    if criteria:
        table_rows = [
            {
                "type": "table_row",
                "table_row": {"cells": [
                    [{"type": "text", "text": {"content": "Critère"}}],
                    [{"type": "text", "text": {"content": "Résultat"}}],
                    [{"type": "text", "text": {"content": "Points"}}],
                ]}
            }
        ]
        for c in criteria:
            status_emoji = {"ok": "✅ OK", "ko": "❌ KO", "partial": "⚠️ Partiel"}.get(c.get("status", "ko"), "❌ KO")
            table_rows.append({
                "type": "table_row",
                "table_row": {"cells": [
                    [{"type": "text", "text": {"content": c.get("label", "")}}],
                    [{"type": "text", "text": {"content": status_emoji}}],
                    [{"type": "text", "text": {"content": f"+{c.get('points', 0)} pts"}}],
                ]}
            })
        blocks.append({
            "type": "table",
            "table": {
                "table_width": 3,
                "has_column_header": True,
                "has_row_header": False,
                "children": table_rows
            }
        })

    action = channel_data.get("priority_action")
    if action:
        blocks.append({
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"type": "text", "text": {"content": "Action prioritaire : "}, "annotations": {"bold": True}},
                    {"type": "text", "text": {"content": action}},
                ]
            }
        })

    blocks.append({"type": "divider", "divider": {}})
    return blocks


async def create_audit_page(venue_params: dict, audit_result: dict, railway_url: str) -> str:
    """Create a Notion page for the audit and return its URL."""
    notion = AsyncClient(auth=os.getenv("NOTION_API_KEY"))
    scores = audit_result.get("scores", {})
    channels = audit_result.get("channels", {})
    priority_actions = audit_result.get("priority_actions", [])

    venue_name = venue_params.get("venue_name", "Venue inconnue")
    today = date.today().strftime("%d %B %Y")
    global_score = scores.get("global_score", 0)
    color_emoji = scores.get("color_emoji", "🔴")
    color = scores.get("color", "red")

    # Score table rows
    score_table_rows = [
        {"type": "table_row", "table_row": {"cells": [
            [{"type": "text", "text": {"content": ""}}],
            [{"type": "text", "text": {"content": "Note"}}],
            [{"type": "text", "text": {"content": "Détail"}}],
            [{"type": "text", "text": {"content": "Action"}}],
        ]}},
        {"type": "table_row", "table_row": {"cells": [
            [{"type": "text", "text": {"content": "Note globale"}, "annotations": {"bold": True}}],
            [{"type": "text", "text": {"content": f"{color_emoji} {global_score} / 100"}, "annotations": {"bold": True}}],
            [{"type": "text", "text": {"content": "Quanti × 40% + Quali × 60%"}, "annotations": {"bold": True}}],
            [{"type": "text", "text": {"content": "NA"}, "annotations": {"bold": True}}],
        ]}},
        {"type": "table_row", "table_row": {"cells": [
            [{"type": "text", "text": {"content": "Note quanti"}}],
            [{"type": "text", "text": {"content": f"🔵 {scores.get('quanti_score', 0)} / 100"}}],
            [{"type": "text", "text": {"content": scores.get("quanti_detail", "")}}],
            [{"type": "text", "text": {"content": "RAS" if scores.get("quanti_score", 0) == 100 else "Voir actions"}}],
        ]}},
        {"type": "table_row", "table_row": {"cells": [
            [{"type": "text", "text": {"content": "Note quali"}}],
            [{"type": "text", "text": {"content": f"🟠 {scores.get('quali_score', 0)} / 100"}}],
            [{"type": "text", "text": {"content": scores.get("quali_detail", "")}}],
            [{"type": "text", "text": {"content": f"{len(priority_actions)} actions pour gagner les pts manquants"}}],
        ]}},
    ]

    # Priority actions table
    action_rows = [
        {"type": "table_row", "table_row": {"cells": [
            [{"type": "text", "text": {"content": "Priorité"}}],
            [{"type": "text", "text": {"content": "Canal"}}],
            [{"type": "text", "text": {"content": "Point de fuite"}}],
            [{"type": "text", "text": {"content": "Action"}}],
            [{"type": "text", "text": {"content": "Gain"}}],
        ]}}
    ]
    for a in priority_actions[:5]:
        priority_num = a.get("priority", 1)
        priority_emoji = "🔴" if priority_num <= 2 else "🟠"
        action_rows.append({"type": "table_row", "table_row": {"cells": [
            [{"type": "text", "text": {"content": f"{priority_emoji} {priority_num}"}}],
            [{"type": "text", "text": {"content": a.get("channel", "")}}],
            [{"type": "text", "text": {"content": a.get("leak_point", "")}}],
            [{"type": "text", "text": {"content": a.get("action", "")}}],
            [{"type": "text", "text": {"content": f"+{a.get('gain_pts', 0)} pts"}}],
        ]}})

    children = [
        # Metadata
        {"type": "paragraph", "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": f"Audit du {today}"}}],
            "color": "gray_background"
        }},
        {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Venue"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [
            {"type": "text", "text": {"content": f"Segment {venue_params.get('segment', '1')}"}}
        ]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [
            {"type": "text", "text": {"content": venue_params.get("address", "")}}
        ]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [
            {"type": "text", "text": {"content": "Rapport détaillé : "}},
            {"type": "text", "text": {"content": railway_url, "link": {"url": railway_url}}},
        ]}},
        {"type": "divider", "divider": {}},
        # Scores
        {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Scores"}}]}},
        {"type": "table", "table": {"table_width": 4, "has_column_header": True, "has_row_header": False, "children": score_table_rows}},
        {"type": "divider", "divider": {}},
        # Priority actions
        {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🚨 Points de fuite identifiés et actions prioritaires"}}]}},
        {"type": "table", "table": {"table_width": 5, "has_column_header": True, "has_row_header": False, "children": action_rows}},
        {"type": "divider", "divider": {}},
    ]

    # Channel details
    for ch_key in ["website", "gmb", "rwg", "instagram"]:
        ch_data = channels.get(ch_key, {})
        if ch_data:
            children.extend(_build_channel_blocks(ch_key, ch_data))

    # Notion API: max 100 children per call
    page = await notion.pages.create(
        parent={"database_id": NOTION_DB_ID},
        icon={"type": "emoji", "emoji": color_emoji},
        properties={
            "Venue": {"title": [{"type": "text", "text": {"content": venue_name}}]},
            "Date": {"date": {"start": date.today().isoformat()}},
            "Segment": {"select": {"name": f"Segment {venue_params.get('segment', '1')}"}},
            "Adresse": {"rich_text": [{"type": "text", "text": {"content": venue_params.get("address", "")}}]},
            "Note globale": {"number": global_score},
            "Note quanti": {"number": scores.get("quanti_score", 0)},
            "Note quali": {"number": scores.get("quali_score", 0)},
            "Score": {"select": {"name": _score_select(global_score)}},
            "URL Railway": {"url": railway_url},
            "Site Web - Quanti": {"select": {"name": _quanti_select(channels.get("website", {}).get("quanti_ok"))}},
            "GMB - Quanti": {"select": {"name": _quanti_select(channels.get("gmb", {}).get("quanti_ok"))}},
            "RwG - Quanti": {"select": {"name": "N/A" if not channels.get("rwg", {}).get("eligible") else _quanti_select(channels.get("rwg", {}).get("quanti_ok"))}},
            "Instagram - Quanti": {"select": {"name": _quanti_select(channels.get("instagram", {}).get("quanti_ok"))}},
            "Points de fuite": {"number": len(priority_actions)},
        },
        children=children[:100],
    )

    page_url = page.get("url", "")

    # Update the Railway URL column with the Notion page URL
    if railway_url and page_url:
        await notion.pages.update(
            page_id=page["id"],
            properties={"Lien Notion Audit": {"url": page_url}}
        )

    return page_url
