
from enum import Enum


class UpperCamelCaseMixin:
    """
    This is a mixin for Enums that changes `__str__()` to convert
    screaming snake case `ANIMATION_ACTIONS_ONLY` into upper
    camel case `AnimationActionsOnly`.

    Use it by adding it before the Enum subclass:
    ```py
    class AnimationType(UpperCamelCaseMixin, Enum):
        ANIMATION_ACTIONS_ONLY = 3
    ```
    """

    def __str__(self) -> str:
        name: str = self.name
        isStartOfWord = True
        transformedName = ""
        for c in name:
            if c == "_":
                isStartOfWord = True
                # Skip it
            elif isStartOfWord:
                transformedName += c.upper()
                isStartOfWord = False
            else:
                transformedName += c.lower()
        return transformedName


class LowerCamelCaseMixin(UpperCamelCaseMixin):
    """
    This is a mixin for Enums that changes `__str__()` to convert
    screaming snake case `ANIMATION_ACTIONS_ONLY` into upper
    camel case `AnimationActionsOnly`.

    Use it by adding it before the Enum subclass:
    ```py
    class AnimationType(UpperCamelCaseMixin, Enum):
        ANIMATION_ACTIONS_ONLY = 3
    ```
    """

    def __str__(self) -> str:
        ret = super().__str__()
        return ret[0].lower() + ret[1:]

SPELL_LOOKUP = {
    0: "None",
    1: "Wand",
    2: "BowAndArrow",
    3: "Broadsword",
    4: "Hourglass",
    5: "Calm",
    6: "Feather",
    7: "RingsOfFire",
    8: "Firestorm",
    9: "GoldNecklace",
    10: "Hammer",
    11: "JadeAmulet",
    12: "Joust",
    13: "JadeRing",
    14: "Dagger",
    15: "LeatherBook",
    16: "EnergyOrb",
    17: "Noise",
    18: "OpalAmulet",
    19: "Pyros",
    20: "RoarStick",
    21: "ShortAxe",
    22: "Trident",
    23: "TurquoiseRing",
    24: "Boomerang",
    25: "UnusedSpellId25",

    50: "DeveloperMistake_VialOfWinds",
    42: "DeveloperMistake_Raft",
    99: "ZeldaWeakness_99_maybe"
}

TREASURE_LOOKUP = {
    0: "NoneOrVialOfAcid",
    1: "AlligatorShoes",
    2: "BrownJar",
    3: "BlackOrb",
    4: "Bone",
    5: "Bouquet",
    6: "Brush",
    7: "Ticket_BlueGreenKnights",
    8: "Candle",
    9: "RawSteak",
    10: "Coal",
    11: "Compass1",
    12: "Compass2",
    13: "Compass3",
    14: "Compass4",
    15: "Compass5",
    16: "Compass6",
    17: "Compass7",
    18: "Diamond",
    19: "EmptyWaterBottle",
    20: "Flute",
    21: "FullWaterBottle",
    22: "Plank",
    23: "Knife",
    24: "GoldTrumpet",
    25: "Harp",
    26: "Ticket_RedKnight",
    27: "LifePotion",
    28: "Map1",
    29: "Map2",
    30: "Map3",
    31: "Map4",
    32: "Map5",
    33: "Map6",
    34: "Map7",
    35: "Rug",
    36: "MagicShield",
    37: "FishingNet",
    38: "Ladder",
    39: "WhiteOrb1",
    40: "WhiteOrb2",
    41: "Saltcellar",
    42: "Raft",
    43: "RedBoots",
    44: "Repellent",
    45: "RedBow",
    46: "RupeeItem",
    47: "Scroll",
    48: "WoodenSpoon",
    49: "SilverTrumpet",
    50: "VialOfWinds",
    51: "GoldenBoots"
}

DIRECTION_LOOKUP = {
    0: "UP",
    1: "RIGHT",
    2: "DOWN",
    3: "LEFT",
    4: "TELEPORT"
}


class AnimationType(UpperCamelCaseMixin, Enum):
    IMMOBILE = 0
    UNKNOWN_TYPE_1 = 1
    ENEMY = 2
    ANIMATION_ACTIONS_ONLY = 3
    PUSHABLE_BLOCK = 4
    BOSS = 5
    FLOATING_RAFT = 6
    MOVING_RAFT = 7
    DIAGONAL_BOUNCING_SPRITE = 8
    ORTHOGONAL_BOUNCING_SPRITE = 9
    MAGIC_SHIELDABLE_HAZARD = 50


class ActorType(UpperCamelCaseMixin, Enum):
    NORMAL = 0
    ENEMY_OR_SWITCH = 1
    LOOT = 2
    # Type 3 appears to be unused?
    UNKNOWN_TYPE_3 = 3
    HAZARD = 4
    BOSS = 5
    UNKNOWN_TYPE_6 = 6


class ActorScriptType(LowerCamelCaseMixin, Enum):
    ON_DEATH_OR_RAFT_RIDE_FINISHED = 0
    ON_TOUCH_OR_PUSH_BLOCK_STOPPED_MOVING = 1
    ON_PURCHASE_OR_ANIMATION_COMPLETE = 2
    ON_HIT_OR_INTERACT_INTERCEPT = 3
    ON_ITEM_INTERACT_OR_SOUND_FILE_DONE = 4
    ON_LOAD = 5


class CellScriptType(LowerCamelCaseMixin, Enum):
    ON_ENTRY = 0
    ON_LEAVE = 1
    ON_TOUCH_TRIGGER = 2
    UNKNOWN_TYPE_3 = 3
    UNKNOWN_TYPE_4 = 4
    UNKNOWN_TYPE_5 = 5


class LootDropType(UpperCamelCaseMixin, Enum):
    NOTHING = 0
    BLUE_RUPEE = 1
    YELLOW_RUPEE = 2
    HEART = 3
    RANDOM = 4


# See `curiosities/Actor Desc Projectile Field.md` for more info.
class ProjectileField(Enum):
    DENY = 0
    ALLOW = 1
    ALLOW_48 = 48
    ALLOW_49 = 49
    ALLOW_52 = 52

    def __str__(self):
        if self == ProjectileField.DENY:
            return "Deny"
        elif self == ProjectileField.ALLOW:
            return "Allow(1)"
        elif self == ProjectileField.ALLOW_48:
            return "Allow(48)"
        elif self == ProjectileField.ALLOW_49:
            return "Allow(49)"
        elif self == ProjectileField.ALLOW_52:
            return "Allow(52)"


class BossCommandType(LowerCamelCaseMixin, Enum):
    LOOP = 0
    ADVANCE_TO_NEXT_ACTOR = 1
    SET_START_POSITION = 2
    SET_LOOP_START_INDEX = 3
    # 4 has two possible names depending on paramHigh
    SPECIAL_HANDLING = 4
    MOVE_TO_GOAL = 5
    USE_ATTACK = 6
    SET_ANIMATION_GROUP = 7
    SET_IS_INVULNERABLE = 8
    PLAY_SOUND = 9

    RUN_ANIMATION_FOR_DURATION = 40
    RUN_ENEMY_AI_FOR_STEPS = 41
    
    def __str__(self) -> str:
        if self == BossCommandType.RUN_ENEMY_AI_FOR_STEPS:
            # Special camel case exception for "AI" acronym
            return "runEnemyAIForSteps"
        else:
            return super().__str__()


# Pairs are in (paramLow, paramHigh, shouldDouble) order.
BOSS_COMMAND_PARAM_NAMES: dict[tuple[str | None, str | None, bool]] = {
    BossCommandType.SET_START_POSITION: ("y", "x", True),
    BossCommandType.MOVE_TO_GOAL: ("y", "x", True),
    BossCommandType.SET_ANIMATION_GROUP: ("group", None, False),
    BossCommandType.SET_IS_INVULNERABLE: ("invulnerable", None, False),
    BossCommandType.PLAY_SOUND: ("index", None, False),
    BossCommandType.RUN_ANIMATION_FOR_DURATION: ("frames", None, False),
    BossCommandType.RUN_ENEMY_AI_FOR_STEPS: ("steps", None, False),
}