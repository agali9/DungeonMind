"""Seed the database with the demo campaign.

Run: `flask seed` (wired up in app/__init__.py). Idempotent — safe to re-run.
"""

from __future__ import annotations

from .extensions import db
from .models import Campaign, CampaignMembership, Location, Shop, ShopItem, User


CAMPAIGN_NAME = "The Embervale Chronicles"
WORLD_BRIEF = (
    "The valley of Embervale, long shadowed by Mount Cindermaw, was once ringed by seven "
    "villages. Six have fallen silent in the last year. Only Hollow's End remains — a weary "
    "hamlet held together by the Silverbark Tavern, the blacksmith Ira Thorne, and the "
    "hedge-witch Maerla. Rumours speak of a ruin beneath the northern crags where a lantern "
    "burns green at night, and caravans from the eastern road no longer arrive."
)

STARTING_SCENE = (
    "You stand on the muddy threshold of the Silverbark Tavern. Rain hisses on the thatch. "
    "Through the open door, firelight, the smell of onion stew, and the quiet voice of someone "
    "who has been waiting for you."
)

# Coordinates are in a 1000x800 world space.
LOCATIONS = [
    # key, display_name, description, x, y, icon
    ("tavern", "Silverbark Tavern", "The last warm hearth in Hollow's End. A gathering place for weary travelers.", 500, 560, "🍺"),
    ("smithy", "Thorne's Forge", "Ira Thorne's smithy. Hammer-ring at all hours. Sells weapons and armor.", 420, 600, "⚒️"),
    ("apothecary", "Maerla's Cottage", "A crooked cottage hung with dried herbs. Maerla the hedge-witch lives here.", 560, 620, "🌿"),
    ("village_square", "Hollow's End", "The last surviving village. A moss-eaten well and three empty market stalls.", 300, 560, "🏘️"),
    ("forest", "Whisperwood", "Pines so dense the sun barely reaches the floor. Strange lights at night.", 180, 280, "🌲"),
    ("ruins", "Sunken Ruins", "Crumbled towers half-buried in the earth. Something still stirs within.", 460, 300, "🏛️"),
    ("cave", "Gloam Cavern", "A warm cave entrance glowing faintly orange. Smells of sulfur and ash.", 580, 420, "🕳️"),
    ("road", "Eastern Road", "Cart-tracks leading beyond the valley. No hoofprints recent.", 860, 540, "🛤️"),
    ("witchciell", "Witchciell", "A violet-lit spire where old oaths are kept. Dangerous. Level 5+ recommended.", 720, 120, "🏰"),
    ("ironkeep", "Ironkeep", "A grim fortress of black stone. Once a garrison, now something darker holds it.", 460, 680, "🏯"),
    ("mossmarket", "Mossmarket", "A ramshackle trading post. Merchants of dubious reputation.", 200, 720, "🛒"),
]

# shop_key, shop_name, shopkeeper, at_location_key, items:
#   (name, description, price, stock, kind, effect)
SHOPS = [
    (
        "thorne_smithy", "Thorne's Forge", "Ira Thorne", "smithy",
        [
            ("Short Sword", "Well-balanced. Steel of decent make.", 15, 3, "weapon", {"damage": "1d6", "kind": "slashing"}),
            ("Hand Axe", "Rugged, for wood or worse.", 8, 4, "weapon", {"damage": "1d6", "kind": "slashing", "throwable": True}),
            ("Chain Shirt", "Heavy, but it turns blades.", 50, 1, "armor", {"ac_bonus": 3}),
            ("Iron Torch", "Burns eight hours in still air.", 2, 10, "misc", {}),
            ("Grappling Hook", "Ira carved the tines herself.", 5, 5, "misc", {}),
        ],
    ),
    (
        "maerla_apothecary", "Maerla's Cottage", "Maerla the Hedge-Witch", "apothecary",
        [
            ("Healing Draught", "Bitter, root-red. Restores 2d4+2 HP.", 18, 4, "potion", {"heal": "2d4+2"}),
            ("Witch's Salve", "Smells of pine tar. Heals 1d4 HP per round for 3 rounds.", 28, 2, "potion", {"heal_over_time": "1d4x3"}),
            ("Rope of Knotting", "Ties itself on command.", 40, 1, "misc", {"magic": True}),
            ("Dried Wyrm-Tongue", "Useful, if you know what it's for.", 12, 3, "misc", {}),
        ],
    ),
]


def seed_database() -> Campaign:
    """Idempotent seed. Returns the campaign (existing or newly created)."""
    existing = Campaign.query.filter_by(name=CAMPAIGN_NAME).first()
    if existing is None:
        camp = Campaign(
            name=CAMPAIGN_NAME,
            world_brief=WORLD_BRIEF,
            current_scene=STARTING_SCENE,
            turn_index=0,
            mode="exploration",
            is_demo=True,
            owner_id=None,
        )
        db.session.add(camp)
        db.session.flush()
    else:
        camp = existing
        if not camp.is_demo:
            camp.is_demo = True
        if not camp.world_brief:
            camp.world_brief = WORLD_BRIEF
        if not camp.current_scene:
            camp.current_scene = STARTING_SCENE
        db.session.flush()

    loc_by_key: dict[str, Location] = {}
    for key, display, desc, x, y, icon in LOCATIONS:
        existing_loc = Location.query.filter_by(campaign_id=camp.id, key=key).first()
        if existing_loc is None:
            loc = Location(
                campaign_id=camp.id, key=key, display_name=display,
                description=desc, x=float(x), y=float(y), icon=icon,
                discovered=True,
            )
            db.session.add(loc)
            loc_by_key[key] = loc
        else:
            loc_by_key[key] = existing_loc
    db.session.flush()

    for shop_key, shop_name, shopkeeper, at_loc, items in SHOPS:
        existing_shop = Shop.query.filter_by(campaign_id=camp.id, key=shop_key).first()
        if existing_shop is None:
            shop = Shop(
                campaign_id=camp.id,
                key=shop_key,
                name=shop_name,
                shopkeeper=shopkeeper,
                location_id=loc_by_key[at_loc].id,
            )
            db.session.add(shop)
            db.session.flush()
        else:
            shop = existing_shop

        existing_items = {item.name for item in shop.items}
        for name, desc, price, stock, kind, effect in items:
            if name in existing_items:
                continue
            db.session.add(ShopItem(
                shop_id=shop.id, name=name, description=desc,
                price=price, stock=stock, kind=kind, effect=effect,
            ))

    db.session.commit()
    return camp


def clone_template_campaign(owner: User, name: str) -> Campaign:
    template = seed_database()
    cloned = Campaign(
        name=name.strip()[:120] or "Untitled Campaign",
        world_brief=template.world_brief,
        current_scene=STARTING_SCENE,
        turn_index=0,
        mode="exploration",
        owner_id=owner.id,
        is_demo=False,
    )
    db.session.add(cloned)
    db.session.flush()

    location_map: dict[int, Location] = {}
    for loc in template.locations:
        copied = Location(
            campaign_id=cloned.id,
            key=loc.key,
            display_name=loc.display_name,
            description=loc.description,
            icon=loc.icon,
            x=loc.x,
            y=loc.y,
            discovered=loc.discovered,
        )
        db.session.add(copied)
        db.session.flush()
        location_map[loc.id] = copied

    for shop in template.shops:
        copied_shop = Shop(
            campaign_id=cloned.id,
            key=shop.key,
            name=shop.name,
            shopkeeper=shop.shopkeeper,
            location_id=location_map.get(shop.location_id).id if shop.location_id in location_map else None,
        )
        db.session.add(copied_shop)
        db.session.flush()
        for item in shop.items:
            db.session.add(ShopItem(
                shop_id=copied_shop.id,
                name=item.name,
                description=item.description,
                price=item.price,
                stock=item.stock,
                kind=item.kind,
                effect=dict(item.effect or {}),
            ))

    db.session.add(CampaignMembership(user_id=owner.id, campaign_id=cloned.id, role="owner"))
    db.session.commit()
    return cloned
