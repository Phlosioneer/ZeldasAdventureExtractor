
from za_filesystem import ResourceTree
from za_constants import SPELL_LOOKUP, TREASURE_LOOKUP, DIRECTION_LOOKUP

from typing import Dict, Union, Callable, List, Tuple, Optional




OPCODE_LOOKUP: Dict[int, Union[
    # Formatted string. Expects `s.format(index, parameter, friendlyIndex)`
    # where friendlyIndex is a nice name for the offset into `save`.
    str,

    # String-generating function. Expects `f(index, parameter, friendlyIndex)`
    Callable[[int, int, int], str],

    # List of options, evaluated in order until the callable returns True
    # or the callable is None. Expects `f(index, parameter)`
    List[Tuple[Optional[Callable[[int, int], bool]], Union[
        # Formatted string, as above
        str,

        # String-generating function, as above
        Callable[[int, int, int], str]
    ]]]
]] = {
    0: "nop",
    1: lambda i, p, f: "save[{}] = {} # {}, {}".format(f, p, hex(p), p.to_bytes(2, "big")),
    2: "save[{2}] += {1}",
    3: "save[{2}] -= {1}",
    4: "loseOneHeart()",
    5: [
        (lambda i, p: i > 0, "player.maxHealth += ONE_HEART, healToFull()"),
        (lambda i, p: p == 0, "setUnusedGlobal(player.maxHealth), healToFull()"),
        (None, "setUnusedGlobal({1} * ONE_HEART), healToFull()")
    ],
    6: "spawnAndAnimate(actor=self)",
    7: "showSparklesAndDespawn(actor=self)",
    8: "teleportPlayerTo(cellName=(char*) &save[{2}])",
    9: "player.x = {1}",
    10: "player.y = {1}",
    11: [
        (lambda i, p: i == 0, "returnValue = {1}"),
        (None, "returnValue = {1}, playSoundEffect(source=self, soundId=2)")
    ],
    12: [
        # Note: Unlike other boolean checks, self one specifically checks
        #       for 1. Other truthy values (2, 3, etc) won't work.
        (lambda i, p: i == 1, "op12_0x2cd0(actor=cast[{1}])"),
        (None, "spawnAndAnimate(actor=cast[{1}])")
    ],
    13: [
        (lambda i, p: i == 0, "playVoiceLine(source=self, soundId={1})"),
        (None, lambda i, p, f: "playVoiceLine(source=cast[{}], soundId={})".format(i - 10, p))
    ],
    14: [
        (lambda i, p: p < 4, lambda i, p, f: "setSpriteGroup({}) # Usually the sprite for {}".format(p, DIRECTION_LOOKUP[p])),
        (None, "setSpriteGroup({1})")
    ],
    15: "op15(self, {1})",
    16: lambda i, p, f: "allowPlayerInputs = {}".format(p > 0),
    17: "registerAsTreasureListener(actor=self)",
    18: "tryPurchaseItem(merchant=self)",
    19: [
        (lambda i, p: i == 0, "rupees -= {1}"),
        (None, "rupees += {1}")
    ],
    20: "darkenRoom_maybe()",
    21: "despawn(actor=cast[{1}])",
    22: lambda i, p, f: "exitShrineAndPlayMovie(shrine={})".format(p),
    23: lambda i, p, f: "player.visible_maybe = {}".format(p > 0),
    24: "enableIcePhysics()",
    25: [
        (lambda i, p: i < 26, lambda i, p, f: "setLocationOnMap({}{})".format(chr(i + ord("a")), p)),
        (None, lambda i, p, f: "setLocationOnMap(a{}{})".format(chr(i + ord("a") - 26), p))
    ],
    26: "playSoundEffect(source=(INVALID), soundId=3)",
    27: [
        (lambda i, p: i != 0, "show(actor=cast[{1}])"),
        (None, "hide(actor=cast[{1}])")
    ],
    28: "tryRemoveCellFromUnkList(cellId={1})"
}

SAVE_FIELD_LOOKUP = {

    # Shrine boss death flags, checked before playing taunt lines, and
    # some other situations.
    86: "LLORT_DEFEATED",
    87: "PASQUINADE_DEFEATED",
    88: "AVIANA_DEFEATED",
    89: "MALMORD_DEFEATED",
    90: "AGWANDA_DEFEATED",
    91: "URSORE_DEFEATED",
    92: "WARBANE_DEFEATED",

    # Miniboss deaths. This table implies that the Hag is a miniboss!
    95: "HAG_DEFEATED",
    96: "BLUE_KNIGHT_DEFEATED",
    97: "GREEN_KNIGHT_DEFEATED",
    98: "RED_KNIGHT_DEFEATED",
    99: "VAPORA_DEFEATED",

    # Used by cell f23 for a one-time voice line.
    100: "TODO_LOOKUP_VOICE_LINE_F23",

    # Used by cell f26 for a one-time voice line.
    101: "MERCHANT_VOICE_F26",

    # Used by cell j24 for a one-time voice line.
    103: "GLEBB_SPOKE_FIRST_LINE",

    # Used by s214 to track the black orb placement,and by s213 when
    # spawning the black orb item.
    106: "HAS_BLACK_ORB_BEEN_USED",

    # Used by s102 to track the ladder placement, and by f28 when spawning
    # the ladder item.
    107: "HAS_LADDER_BEEN_USED",

    # Used by n11.
    110: "HAS_ENTERED_WHITE_STEED_LODGE",

    # The Moblin Inn uses its own variable, rather than the common INDOOR_ID.
    111: "INSIDE_MOBLIN_INN",

    # Used by cell S18.
    114: "HEART_CONTAINER_S18",

    # Used by cell O11a.
    115: "HEART_CONTAINER_O11a",

    # Used by cell M25a.
    116: "HEART_CONTAINER_M25a",

    # Used by cell F10.
    117: "HEART_CONTAINER_F10",

    # Used by R9.
    122: "LONLYN_GAVE_RUPEES",

    # Set to 1 (or sometimes 2) when Zelda goes inside of something. It's
    # used to position her correctly when teleporting back outside.
    128: "INDOOR_ID",

    # When set to 1, the underworld version of the respawn cell will
    # be used instead of the overworld version. Used for boss cells,
    # which only have underworld versions.
    129: "RESPAWN_TO_UNDERWORLD_VERSION",

    # Used by cell k13 for a one-time voice line.
    131: "LOUNGER_LINE_K13",

    # This is set to 1 during an onItemInteractOrSoundFileDone trigger
    # if the source of the trigger was an item interaction, rather than
    # a sound file finishing.
    132: "IS_INTERACT_TRIGGER",

    # This is set to 1 when respawning, or after using the harp or
    # compass to teleport. It is the script's responsibility to clear
    # this flag!!
    133: "ENTERED_BY_RESPAWN_HARP_OR_COMPASS",

    134: "RUPEE_COUNT",

    ############
    # Everything between 136 and 170 gets cleared whenever the respawn
    # cell changes!

    # Seems to be TRUE if zelda teleported into a cell?
    138: "TELEPORTED_maybe",

    # Keeps track of the raft direction. See the script comment file
    # section "Raft Mechanics" for more info.
    139: "RAFT_JOURNEY_STATE",
    
    156: "CELL_ENTRY_DIRECTION",
    157: "KEY_COUNT",
    158: "RESPAWN_ENUM",
    160: "RESPAWN_CELL_ID_maybe",

}

CONDITION_LOOKUP = {
    0: "always",
    1: "save[{}] > {}",
    2: "save[{}] < {}",
    3: "save[{}] == {}",
    4: "save[{}] != {}",
    5: "always (corrupted)",
    6: "always (corrupted)"
}


class Script:
    def __init__(self, conditionArray, onTrueArray, onFalseArray):
        self.conditions = [ScriptCondition(s.take("I")) for s in conditionArray.elements]
        self.onTrue = [ScriptAction(s.take("I")) for s in onTrueArray.elements]
        self.onFalse = [ScriptAction(s.take("I")) for s in onFalseArray.elements]
    
    def isEmpty(self) -> bool:
        return len(self.conditions) == 1 and self.conditions[0].pretty == "always" \
            and len(self.onTrue) == 1 and self.onTrue[0].pretty == "nop" \
            and len(self.onFalse) == 1 and self.onFalse[0].pretty == "nop"
    
    def isConditional(self) -> bool:
        return not (len(self.conditions) == 1 and self.conditions[0].pretty == "always" \
            and len(self.onFalse) == 1 and self.onFalse[0].pretty == "nop")

    def hasElse(self) -> bool:
        return not (len(self.onFalse) == 1 and self.onFalse[0].pretty == "nop")

    def __repr__(self) -> str:
        return "<If {} then {} else {}>".format(self.conditions, self.onTrue, self.onFalse)

def friendlySaveIndex(index: int) -> str:
    if index == 0:
        return "blankItem"
    elif index < 26:
        return SPELL_LOOKUP[index]
    elif index == 26:
        # The treasure lookup table has "NoneOrVialOfAcid" here
        return "VialOfAcid"
    elif index - 26 < 52:
        return TREASURE_LOOKUP[index - 26]
    elif index - 26 - 52 < 8:
        return "SIGN_S{}".format(index - 26 - 52 + 1)
    elif index in SAVE_FIELD_LOOKUP:
        return SAVE_FIELD_LOOKUP[index]
    elif index >= 324//2 and index < 330//2:
        return "CELL_SELF + {}".format(index - 324//2)
    elif index >= 330//2 and index < 336//2:
        return "CELL_UP + {}".format(index - 330//2)
    elif index >= 336//2 and index < 342//2:
        return "CELL_RIGHT + {}".format(index - 336//2)
    elif index >= 342//2 and index < 348//2:
        return "CELL_DOWN + {}".format(index - 342//2)
    elif index >= 348//2 and index < 354//2:
        return "CELL_LEFT + {}".format(index - 348//2)
    elif index >= 356//2:
        return "LOCALS + {}".format(index - 356//2)
    
    return str(index)
    
class ScriptAction:
    def __init__(self, code):
        self.opcode = (code & 0xFC00_0000) >> 26
        self.index = (code & 0x03FF_0000) >> 16
        self.parameter = (code & 0xFFFF)

        friendlyIndex = friendlySaveIndex(self.index)

        # "spec" short for specification. It's a bad name but can't think
        # of a better one.
        if self.opcode in OPCODE_LOOKUP:
            self.spec = OPCODE_LOOKUP[self.opcode]
        else:
            self.spec = "op" + str(self.opcode) + "(i={}, p={})"
        
        spec = self.spec
        if isinstance(spec, list):
            foundPredicate = False
            for predicate, subSpec in spec:
                if predicate == None or predicate(self.index, self.parameter):
                    spec = subSpec
                    foundPredicate = True
                    break
            if not foundPredicate:
                raise Exception("op={} index={} param={}".format(self.opcode, self.index, self.parameter))
        
        if isinstance(spec, str):
            self.pretty = spec.format(self.index, self.parameter, friendlyIndex)
        else:
            self.pretty = spec(self.index, self.parameter, friendlyIndex)

    
    def __repr__(self) -> str:
        return "ScriptAction({})".format(self.pretty)

class ScriptCondition:
    def __init__(self, code):
        self.opcode = (code & 0xFC00_0000) >> 26
        self.index = (code & 0x03FF_0000) >> 16
        self.parameter = (code & 0xFFFF)
        friendlyIndex = friendlySaveIndex(self.index)
        if self.opcode in CONDITION_LOOKUP:
            self.pretty = CONDITION_LOOKUP[self.opcode].format(friendlyIndex, self.parameter)
        else:
            self.pretty = "never"

    def __repr__(self) -> str:
        return "ScriptCondition({})".format(self.pretty)

class ScriptSet:
    def __init__(self, tree: ResourceTree, typeNameLookup: Dict[Union[int, str], str]):
        self.scripts: Dict[str, List[Script]] = {}
        for i, subTree in enumerate(tree.children.values()):
            if i in typeNameLookup:
                kind = typeNameLookup[i]
            else:
                kind = typeNameLookup["default"].format(i)

            triggerScripts = self._parseScriptPseudoArray(subTree)
            if len(triggerScripts) > 0:
                self.scripts[kind] = triggerScripts

    def _parseScriptPseudoArray(self, root: ResourceTree) -> List[ScriptAction]:
        scripts = []
        assert len(root.children) % 3 == 0
        count = len(root.children) // 3
        for i in range(count):
            scriptTrees = [
                root.children[i * 3], 
                root.children[i * 3 + 1],
                root.children[i * 3 + 2]
            ]
            script = Script(scriptTrees[0], scriptTrees[1], scriptTrees[2])
            if not script.isEmpty():
                scripts.append(script)
        return scripts
    
    def isEmpty(self) -> bool:
        return len(self.scripts) == 0
    
    def prettyPrint(self, className: Optional[str] = None, indent: int = 0) -> str:
        ret = ""
        if className != None:
            ret = "{}class {}:\n".format("\t" * indent, className)
            indent += 1
        
        for name, body in self.scripts.items():
            ret += "{}def {}(self):\n".format("\t" * indent, name)
            for block in body:
                if block.isConditional():
                    ret += "{}if {}".format("\t" * (indent + 1), block.conditions[0].pretty)
                    for condition in block.conditions[1:]:
                        ret += " and {}".format(condition.pretty)
                    ret += ":\n"
                    ret += ScriptSet._writeStatements(block.onTrue, indent + 2)
                    
                    if block.hasElse():
                        ret += "{}else:\n".format("\t" * (indent + 1))
                        ret += ScriptSet._writeStatements(block.onFalse, indent + 2)
                else:
                    ret += ScriptSet._writeStatements(block.onTrue, indent + 1)
                ret += "{}\n".format("\t" * (indent + 1))
        return ret
    
    def _writeStatements(statements: List[ScriptAction], indent: int) -> str:
        ret = ""
        for statement in statements:
            ret += "{}{}\n".format("\t" * indent, statement.pretty)
        return ret
