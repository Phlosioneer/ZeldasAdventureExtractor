
import copy
from typing import Literal

import PIL.Image

from .constants import DIRECTION_LOOKUP, SPELL_LOOKUP, TREASURE_LOOKUP, ActorType, AnimationType, LootDropType, ProjectileField
from .animation import Animation
from .basic_types import BoundingBox, Coords
from .scripts import ScriptSet
from .sprites import PointerArray
from .struct_stream import StructStream


class Actor:
    """
    The metadata for a single instance of an ActorDescription. This is what has
    an (x, y) position, health, etc.

    A copy of this structure lives in RAM during the game, and is used for all
    entity state. So a lot of fields don't make sense in a serialized format, like
    timers, pointers, etc.
    """

    # The index of the ActorDescription for this actor.
    descIndex: int
    # Starting coords for the actor.
    spawnCoords: Coords
    # Starting health for the actor.
    health: int
    # Unknown fields. These are most likely not just runtime stuff - I *think*
    # all of these are nonzero for some actor somewhere. I *think* I already
    # checked that. But I don't remember which actor descriptions, or what
    # values they have.
    unk_0x24: int
    unk_0x28: int
    unk_0x30: int
    unk_0x32: int
    unk_0x34: int
    unk_0x35: int
    # Facing direction. "TELEPORT" sounds like a weird direction, but it's the
    # same enum as room exits.
    direction: Literal["UP", "RIGHT", "DOWN", "LEFT", "TELEPORT"]
    # The "animation type" for the actor. This type governs how sprites are
    # updated each frame - whether they follow a set path, if they loop an
    # animation, or if they wander around, or several other options. This
    # could also be called "actor type", but that's too broad.
    animationType: AnimationType
    # The description for this actor.
    description: "ActorDescription | None"
    # The animation state for this actor.
    animation: Animation | None

    def __init__(self, stream: StructStream):
        assert len(stream) == 54, len(stream)
        
        # Pointers used at runtime
        pointers = stream.takeRaw(4 * 6)
        assert pointers == b'\0' * (4 * 6), pointers

        # The rest of the non-pointer fields
        direction, animationType, frame, self.descIndex = stream.take("HHbB")
        self.spawnCoords = Coords.fromStream(stream, xFirst=False)
        self.health, self.unk_0x24, iframeState = stream.take("HHH")
        self.unk_0x28, touchDuration, y, x, self.unk_0x30 = stream.take("HHHHB")
        unk_0x31, self.unk_0x32, self.unk_0x34, self.unk_0x35 = stream.take("BHBB")

        assert len(stream) == 0, stream

        self.direction: Literal["UP", "RIGHT", "DOWN", "LEFT", "TELEPORT"] \
            = DIRECTION_LOOKUP[direction]
        
        self.animationType = AnimationType(animationType)
        
        assert x == 0 and y == 0, "Nonzero current position: ({}, {})".format(x, y)
        assert touchDuration == 0, "Nonzero touch duration: {}".format(touchDuration)
        assert frame == 0, "Nonzero frame value: {}".format(frame)
        assert iframeState == 0, "Nonzero iframeState: {}".format(iframeState)
        assert unk_0x31 == 0, unk_0x31

        self.description: ActorDescription | None = None
        self.animation: Animation | None = None

    def serializeToDict(self) -> dict:
        ret = copy.copy(self.__dict__)
        del ret["description"]
        #ret["spawnCoords"] = asdict(self.spawnCoords)
        return ret

class ActorDescription:
    size: Coords
    groupCount: int
    maxHealth_maybe: int
    useCostOrDefense: int
    baseDamageOrPurchasePrice_maybe: int
    collisionSamplePoints: list[Coords]
    bonusDamage: int
    unk_0x2b: int
    unk_0x2c: int
    canUseProjectiles: ProjectileField
    type_maybe: ActorType
    lootDropped: LootDropType
    groupCount: int
    maxHealth_maybe: int
    useCostOrDefense: int
    unk_0x14: int
    unk_0x15: int
    weakToSpell: str
    interactsWithItem: str
    groups: list["SpriteGroup"] | None
    scripts: ScriptSet | None
    unusedSpritePointer: int | None
    unusedGroups: list["SpriteGroup"]
    _cachedHashOfGroups: int | None
    commonName: str | None

    def __init__(self, stream: StructStream):
        assert len(stream) == 46

        self.size = Coords.fromStream(stream, xFirst=False)
        self.groupCount, pointer1, pointer2 = stream.take("HII")
        
        self.maxHealth_maybe, self.useCostOrDefense = stream.take("HH")
        self.baseDamageOrPurchasePrice_maybe, padding = stream.take("HH")

        self.collisionSamplePoints: list[Coords] = []
        for _ in range(2):
            self.collisionSamplePoints.append(Coords.fromStream(stream))
        
        unusedSamplePoint = stream.take("I")
        metaType_maybe, lootDropped, weakToSpell = stream.take("HHH")
        interactsWithItem, self.bonusDamage = stream.take("BB")
        projectile, self.unk_0x2b, self.unk_0x2c = stream.take("BBH")
        
        assert len(stream) == 0, stream
        
        assert pointer1 == 0, pointer1
        assert pointer2 == 0, pointer2
        assert padding == 0, padding
        assert unusedSamplePoint == 0, unusedSamplePoint

        self.canUseProjectiles = ProjectileField(projectile)
        self.type_maybe = ActorType(metaType_maybe)
        self.lootDropped = LootDropType(lootDropped)

        self.groupCount: int
        self.maxHealth_maybe: int
        self.useCostOrDefense: int
        self.baseDamageOrPurchasePrice_maybe: int
        self.unk_0x14: int
        self.unk_0x15: int
        assert weakToSpell in SPELL_LOOKUP, "Unknown spell id: {}".format(weakToSpell)
        self.weakToSpell = SPELL_LOOKUP[weakToSpell]
        assert interactsWithItem in TREASURE_LOOKUP, "Unknown treasure id: {}".format(interactsWithItem)
        self.interactsWithItem = TREASURE_LOOKUP[interactsWithItem]

        self.groups: list[SpriteGroup] | None = None
        self.scripts: ScriptSet | None  = None
        self.unusedSpritePointer: int | None = None
        self.unusedGroups: list[SpriteGroup] = []
        self._cachedHashOfGroups: int | None = None
        self.commonName: str | None = None

    def _assignSprites(self, tree: PointerArray):
        assert len(self.groups) <= len(tree.elements)
        for group, subTree in zip(self.groups, tree.elements):
            group._assignSprites(subTree)
        self.unusedGroups = tree.elements[len(self.groups):]
        
        self.unusedSpritePointer = tree.unusedPointer

    def serializeToDict(self) -> dict:
        if len(self.groups) > 0:
            assert isinstance(self.groups[0], SpriteGroup)
        
        ret = copy.copy(self.__dict__)
        """
        ret["groups"] = [g.toPlainDict() for g in self.groups]
        ret["collisionPoints"] = [asdict(c) for c in self.collisionPoints]
        ret["size"] = asdict(self.size)
        """
        del ret["_cachedHashOfGroups"]
        del ret["scripts"]
        del ret["unusedGroups"]

        return ret
    
    def hashOfSpriteGroups(self) -> int:
        if self._cachedHashOfGroups == None:
            self._cachedHashOfGroups = hash(tuple([g.hashOfSprites() for g in self.groups]))
        return self._cachedHashOfGroups
    
    def makeMetadataImages(self, palette: bytes | None = None) -> list[PIL.Image.Image] | None:
        if palette == None:
            oldPalette = None
            for g in self.groups:
                for s in g.sprites:
                    # Apparently palettes can be null???
                    if s.palette != None:
                        oldPalette = s.palette.palette
                        break
                if oldPalette != None:
                    break
            if oldPalette == None:
                return None

            # Put green at index 8
            #oldPalette = self.groups[0].getMiddleSprite().palette.palette
            palette = oldPalette[:4*GREEN] + b'\0\xFF\0\xFF' + oldPalette[4*GREEN + 4:]

        box = BoundingBox()
        box.add(self.collisionSamplePoints)
        box.add(self.size)
        for g in self.groups:
            box.add(g.treeHeightSamples)
            box.add(g.damageSamplePoints_maybe)
            for s in g.sprites:
                box.add(s.size)
        metaImageOffset = Coords(-box.minX, -box.minY)

        ret = []
        for group in self.groups:
            metaImage = PIL.Image.new("P", (box.width(), box.height()), 0)
            metaImage.paste(group.sprites[0], (metaImageOffset.x, metaImageOffset.y))
            metaImage.putpalette(palette, "RGBA")

            putTargets(metaImage, metaImageOffset, self.collisionSamplePoints, GREEN)
            putTargets(metaImage, metaImageOffset, group.treeHeightSamples, BLUE)
            putTargets(metaImage, metaImageOffset, group.damageSamplePoints_maybe, RED)
            putRect(metaImage, metaImageOffset, self.size, BLACK)
            ret.append(metaImage)
        return ret

class SpriteGroup:
    def __init__(self, stream: StructStream):
        assert len(stream) >= 72

        self.animationFrameOrder = list(stream.take("16b"))
        frameCount, self.unk_0x12, self.frameDelay = stream.take("HHH")
        sampleCount = stream.take("H")
        self.treeHeightSamples = [Coords.fromStream(stream) for _ in range(3)]
        self.damageSamplePoints_maybe = [Coords.fromStream(stream) for _ in range(8)]
        pointer = stream.take("I")
        assert pointer == 0, pointer

        self.animationFrameOrder = self.animationFrameOrder[:frameCount]
        self.damageSamplePoints_maybe = self.damageSamplePoints_maybe[:sampleCount]
        assert len(stream) == 0, stream

        self.unk_0x12: int
        self.frameDelay: int
        self.sprites: list[PIL.Image.Image] | None = None
        self.unusedSprites: list[PIL.Image.Image] = []
        self.unusedSpritePointer: int | None = None
        self._cachedHash: int | None = None
    
    def _assignSprites(self, tree: PointerArray):
        if len(self.animationFrameOrder) > 0:
            minSpriteCount = max(self.animationFrameOrder) + 1
        else:
            minSpriteCount = 1
        assert minSpriteCount <= len(tree.elements)
        self.sprites = tree.elements[:minSpriteCount]
        self.unusedSprites = tree.elements[minSpriteCount:]
        
        self.unusedSpritePointer = tree.unusedPointer
    
    def serializeToDict(self) -> dict:
        ret = copy.copy(self.__dict__)
        del ret["sprites"]
        del ret["unusedSprites"]
        del ret["_cachedHash"]
        """
        ret["unk_0x18"] = [asdict(c) for c in self.unk_0x18]
        ret["boundingPolygon"] = [asdict(c) for c in self.boundingPolygon]
        """
        return ret
    
    def getMiddleSprite(self) -> PIL.Image.Image:
        """
        Spikes have blank first sprites, so it's better to pick a
        sprite from the middle of the animation.
        """
        return self.sprites[len(self.sprites) // 2]
    
    def hashOfSprites(self) -> int:
        if self._cachedHash == None:
            self._cachedHash = hash(tuple([hash(s.tobytes()) for s in self.sprites]))
        return self._cachedHash