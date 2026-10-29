"""Public weapon metadata with a small, attributed fallback for Warden.

Fallback identifiers and images: https://valorant.gs/weapons/warden/
Skin pages: /skins/standard-warden/, /skins/galleria-warden/, /skins/datalink-warden/
The extracted dataset documents that its UUIDs are the game's own identifiers.
Unknown skin IDs remain unknown; they are never silently called Standard.
"""
from copy import deepcopy
from functools import lru_cache
from uuid import UUID
import requests
from src.constants import WEAPONS, sockets

VANDAL_ID = "9c82e19d-4575-0200-1a81-3eacf00cf872"
VANDAL_ICON = "https://media.valorant-api.com/weapons/" + VANDAL_ID + "/displayicon.png"

WARDEN_ID = "8db0a1bf-4a50-832a-4566-faaaa6d250ca"
WARDEN_SOURCE = "https://valorant.gs/weapons/warden/"
WARDEN_SKINS = (
    ("61d99a36-4033-0fa9-2c94-71aaf901e120", "Standard Warden",
     "https://cdn.source.gs/valorant/img/warden-render-669dd4-768.webp"),
    ("7a6c65d8-4439-cf7b-1138-e2883f53bff8", "Galleria Warden",
     "https://cdn.source.gs/valorant/img/galleria-warden-render-34fcc1-768.webp"),
    ("3a592896-4f22-88af-903e-97ba6801ef87", "Datalink Warden",
     "https://cdn.source.gs/valorant/img/datalink-warden-render-9f98b7-768.webp"),
)


def normalize_id(value):
    if not value:
        return ""
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError):
        return str(value).lower()


@lru_cache(maxsize=8)
def public_catalog(table):
    """Fetch once per process. No account credentials go to this public endpoint."""
    try:
        response = requests.get("https://valorant-api.com/v1/" + table, timeout=12)
        response.raise_for_status()
        data = response.json().get("data", [])
        return data if isinstance(data, list) else []
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        return []


def merge_weapons(weapons):
    """Keep current API metadata, supplement missing Warden/known skin records."""
    result = deepcopy([w for w in weapons if isinstance(w, dict)])
    warden = next((w for w in result if normalize_id(w.get("uuid")) == WARDEN_ID), None)
    if warden is None:
        warden = {"uuid": WARDEN_ID, "displayName": "Warden", "skins": []}
        result.append(warden)
    if not warden.get("displayName"):
        warden["displayName"] = "Warden"
    if not warden.get("displayIcon"):
        warden["displayIcon"] = WARDEN_SKINS[0][2]
    if not isinstance(warden.get("skins"), list):
        warden["skins"] = []
    for skin_id, name, image in WARDEN_SKINS:
        skin = next((s for s in warden["skins"] if isinstance(s, dict)
                     and normalize_id(s.get("uuid")) == skin_id), None)
        if skin is None:
            warden["skins"].append({"uuid": skin_id, "displayName": name,
                "displayIcon": image, "levels": [], "chromas": [], "metadataSource": WARDEN_SOURCE})
        else:
            if not skin.get("displayName"):
                skin["displayName"] = name
            if not skin.get("displayIcon"):
                skin["displayIcon"] = image
    return result


def weapon_names():
    names = list(WEAPONS)
    for weapon in merge_weapons(public_catalog("weapons")):
        name = weapon.get("displayName")
        if name and name not in names:
            names.append(name)
    return names


def resolve_weapon(weapon_id, item, weapons):
    """Resolve socket IDs into viewer data, retaining IDs when metadata is absent."""
    weapon_id = normalize_id(weapon_id)
    item = item if isinstance(item, dict) else {}
    socket_data = item.get("Sockets") or {}
    socket_data = {normalize_id(k): v for k, v in socket_data.items()}
    record = {"weaponID": weapon_id}
    for field, socket_id in sockets.items():
        socket = socket_data.get(normalize_id(socket_id)) or {}
        selection = socket.get("Item") or {}
        record[field] = normalize_id(selection.get("ID"))
    weapon = next((w for w in weapons if normalize_id(w.get("uuid")) == weapon_id), None)
    record["weapon"] = (weapon or {}).get("displayName") or "Unknown weapon"
    record["weaponDisplayIcon"] = (weapon or {}).get("displayIcon") or (VANDAL_ICON if weapon_id == VANDAL_ID else None)
    if not record["weaponDisplayIcon"] and weapon:
        try:
            canonical_id = str(UUID(weapon_id))
            record["weaponDisplayIcon"] = "https://media.valorant-api.com/weapons/" + canonical_id + "/displayicon.png"
        except (ValueError, TypeError, AttributeError):
            pass
    skin = next((s for s in (weapon or {}).get("skins", [])
                 if isinstance(s, dict) and normalize_id(s.get("uuid")) == record["skin"]), None)
    if not skin:
        record["skinDisplayName"] = "Unknown " + record["weapon"] + " skin"
        record["metadataStatus"] = "unknown_skin"
        record["skinDisplayIcon"] = None
        return record
    record["skinDisplayName"] = skin.get("displayName") or "Unnamed skin"
    record["metadataStatus"] = "known_skin"
    if skin.get("metadataSource"):
        record["metadataSource"] = skin["metadataSource"]
    chroma = next((c for c in skin.get("chromas", []) if isinstance(c, dict)
                   and normalize_id(c.get("uuid")) == record["skin_chroma"]), {})
    levels = [v for v in skin.get("levels", []) if isinstance(v, dict)]
    level = next((v for v in levels if normalize_id(v.get("uuid")) == record["skin_level"]), {})
    record["skinDisplayIcon"] = (chroma.get("displayIcon") or chroma.get("fullRender")
                                or skin.get("displayIcon") or level.get("displayIcon")
                                or ((levels[0].get("displayIcon")) if levels else None))
    # Standard skins can have a valid URL whose artwork is an X placeholder.
    # Use the base weapon artwork rather than a default-skin/chroma placeholder.
    # The default knife is named "Melee", not "Standard Melee". Use the
    # catalog's default-skin ID as well, so renamed/localized defaults work.
    is_default = bool(record["skin"]) and record["skin"] == normalize_id((weapon or {}).get("defaultSkinUuid"))
    if (is_default or record["skinDisplayName"].casefold().startswith("standard ")) and record["weaponDisplayIcon"]:
        record["skinDisplayIcon"] = record["weaponDisplayIcon"]
    if chroma.get("displayName"):
        record["variantDisplayName"] = chroma["displayName"]
    return record
