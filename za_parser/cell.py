

import copy
from dataclasses import asdict, dataclass
from enum import Enum
import json
import os
from typing import TYPE_CHECKING, Self

import PIL.Image

from .cdi_spec.images import dyuvToRGB, rl7ToRGB
from .constants import ActorScriptType, ActorType, AnimationType, CellScriptType
from .actor import Actor, ActorDescription, SpriteGroup
from .animation import Animation, CycleDefinition
from .basic_types import Coords
from .notebook_compat import display
from .scripts import BossData, ScriptSet
from .resource_tree import ResourceFileSystemFolder, ResourceTree, ResourceTreeSet
from .sprites import PointerArray, convertClutToRgba, getClut, unpackSpriteTree
from .struct_stream import StructStream

if TYPE_CHECKING:
    from .game import Game

def cellSerializer(o):
    """
    Function to extend json.dump for more types.

    Classes can implement the magic method serializeToDict() to customize
    the fields that are serialized.
    """
    if isinstance(o, Enum):
        return str(o)

    try:
        return o.serializeToDict()
    except AttributeError:
        try:
            return o.__dict__
        except AttributeError:
            try:
                return asdict(o)
            except KeyboardInterrupt as e:
                raise e
            except:
                raise Exception("Unable to serialize object: " + repr(o))


@dataclass(eq=True, frozen=True)
class TreeHeightRegion:
    """
    A rectangular region with a specific height.

    Actors with a height sample point within this region will be considered
    below terrain colored with the same palette index. So if the tree is
    colored with palette number 2, a tree height region rectangle is placed
    around the tree with height 2.
    """

    # upper left coordinate
    minCoords: Coords
    # lower right coordinate
    maxCoords: Coords
    height: int

    def fromStream(stream: StructStream) -> Self:
        minCoords = Coords.fromStream(stream)
        maxCoords = Coords.fromStream(stream)
        height = stream.take("H")
        return TreeHeightRegion(minCoords, maxCoords, height)


class CellInfo:
    def __init__(self, data: bytes, isOverworld: bool):
        stream = StructStream(data, endianPrefix=">")
        tree = ResourceTree.parseFromStream(stream)
        
        self.infoUnk0, hasSprites, hasPaletteCycling = tree.children["info"].elements[0].peek("HHH")
        self.hasSprites = hasSprites != 0
        self.hasPaletteCycling = hasPaletteCycling != 0
        self.isOverworld = isOverworld
        
        self.infoUnk0: int

        self.cyclers = [CycleDefinition(s) for s in tree.children["cycle"].elements]

        musicData: list[StructStream] = tree.children["play;"].elements
        voiceData: list[StructStream] = tree.children["voice"].elements
        self.musicName: str | None
        self.voiceStartIndex: bytes | None = None
        self.voiceLineIds: list[int] | None = None
        if len(musicData) > 0:
            assert len(musicData) == 1, musicData
            self.musicName = musicData[0].takeNullTermString().decode('ascii')
        else:
            self.musicName = None

        if len(voiceData) > 0:
            assert len(voiceData) == 1, voiceData
            self.voiceStartIndex = voiceData[0].take("I")
        else:
            self.voiceStartIndex = None

        self.treeHeightBoxes = [TreeHeightRegion.fromStream(s) for s in tree.children["tree"].elements]
        self._cachedTreeHeightRegionImage: PIL.Image.Image | None = None
        self.unusedSpritePointer: int | None = None
    
    def makeTreeHeightImage(self, parentCell: "Cell") -> PIL.Image.Image:
        if self._cachedTreeHeightRegionImage == None:
            effectImage = PIL.Image.new("P", parentCell.background.size, 4)
            effectImage.paste(parentCell.collisionImage)
            effectImage.putpalette(parentCell.collisionImage.palette.palette, "RGBA")
            for effect in self.treeHeightBoxes:
                for x in range(effect.minCoords.x, effect.maxCoords.x + 1):
                    effectImage.putpixel((x, effect.minCoords.y), effect.height)
                    effectImage.putpixel((x, effect.maxCoords.y), effect.height)
                for y in range(effect.minCoords.y, effect.maxCoords.y + 1):
                    effectImage.putpixel((effect.minCoords.x, y), effect.height)
                    effectImage.putpixel((effect.maxCoords.x, y), effect.height)
            self._cachedTreeHeightRegionImage = effectImage
        return self._cachedTreeHeightRegionImage

    def serializeToDict(self) -> dict:
        ret = copy.copy(self.__dict__)
        del ret["_cachedTreeHeightRegionImage"]
        return ret


class Cell:
    def __init__(self, subFile: ResourceFileSystemFolder, name: str, isOverworld: bool):
        self.name = name

        self.info = CellInfo(subFile.getRecord(2, kind="data"), isOverworld)
        self._parseBackground(subFile)
        self._parseActors(subFile.getRecord(4, kind="data"))
        self._parseSprites(subFile)
        self._parseScripts(subFile)
        self._parseCollisionData(subFile)

    
    def _parseActors(self, data) -> tuple[list[Actor], list[ActorDescription]]:
        tree = ResourceTree.parseFromStream(StructStream(data, endianPrefix=">"))
        self.actors = [Actor(s) for s in tree.children["sp_cast"].elements]
        self.bossData: BossData | None = None
        
        self._vectorData: StructStream | None = None
        self._tableData: StructStream | None = None
        self._weaponData: StructStream | None = None

        self.descriptions: list[ActorDescription] = []
        if "sp_desc" in tree.children:
            self.descriptions = [ActorDescription(s) for s in tree.children["sp_desc"].elements]
            groups = [SpriteGroup(s) for s in tree.children["sp_groups"].elements]

            groupIndex = 0
            for actor in self.actors:
                actor.description = self.descriptions[actor.descIndex]
            for desc in self.descriptions:
                desc.groups = groups[groupIndex:groupIndex + desc.groupCount]
                groupIndex += desc.groupCount
        
            if "sp_vector" in tree.children and len(tree.children["sp_vector"].elements) > 0 \
                    and len(tree.children["sp_vector"].elements[0]) > 0:
                table = tree.children["sp_table"].elements[0]
                animations = [Animation(v, table) for v in tree.children["sp_vector"].elements]
                for animation in animations:
                    if animation.error:
                        print("\tAbove errors happened for cell", self.name)
                        break
                i = 0
                for actor in self.actors:
                    if actor.animationType in [AnimationType.UNKNOWN_TYPE_1, AnimationType.FLOATING_RAFT, AnimationType.MOVING_RAFT]:
                        actor.animation = animations[i]
                        i += 1
                assert i == len(tree.children["sp_vector"].elements), (i, tree.children["sp_vector"].elements, self.showActors())

            if "wp_cmds" in tree.children:
                self._weaponData = tree.children["wp_cmds"]
            
            if "kp_init" in tree.children:
                boss_actors = [d for d in self.descriptions if d.type_maybe == ActorType.BOSS]
                assert len(boss_actors) == 1, boss_actors
                boss_actor = boss_actors[0]
                boss_projectile = None

                self.bossData = BossData(tree, boss_actor, boss_projectile)
        
    def _parseSprites(self, subFile: ResourceFileSystemFolder):
        self.rawPalette = getClut(subFile.getRecord(7, kind="data"))
        self.palette = convertClutToRgba(self.rawPalette, indices=[0, 4])

        sprites = subFile.getRecord(5, kind="data")
        hasNonzeroByte = False
        for b in sprites:
            if b != 0:
                hasNonzeroByte = True
                break
        
        self.unusedSpriteGroups: list[PointerArray] = []
        if hasNonzeroByte and not self.info.hasSprites:
            print("hasSprites false when sprite is present. Cell:", self.name)
        if hasNonzeroByte:
            tree = unpackSpriteTree(sprites, self.palette, paletteMode="RGBA")
            self.info.unusedSpritePointer = tree.unusedPointer
            
            assert  len(self.descriptions) <= len(tree.elements)
            for desc, subTree in zip(self.descriptions, tree.elements):
                desc._assignSprites(subTree)
            
            self.unusedSpriteGroups = tree.elements[len(self.descriptions):]

    def _parseScripts(self, subFile: ResourceFileSystemFolder):
        scriptFile = subFile.getRecord(6, kind="data")
        scriptFileTree = ResourceTree.parseFromStream(StructStream(scriptFile, endianPrefix=">"))
        for desc, tree in zip(self.descriptions, scriptFileTree.children.values()):
            desc.scripts = ScriptSet(tree, ActorScriptType)

        cellScriptTree = scriptFileTree.children[len(self.descriptions)]
        self.scripts = ScriptSet(cellScriptTree, CellScriptType)

        cellVarArray = scriptFileTree.children[len(self.descriptions) + 1]
        if self.name != "gl6":
            self.vars = [s.take("H") for s in cellVarArray.children[0].elements]
            lastUsedIndex = len(self.descriptions) + 1
        else:
            self.vars = []
            lastUsedIndex = len(self.descriptions)
        
        self.extraScriptData: list[list[list[bytes]]] = []
        if self.name != "gl6":
            for i in range(lastUsedIndex + 1, len(scriptFileTree.children)):
                sublist: list[list[bytes]] = []
                set: ResourceTreeSet
                for set in scriptFileTree.children[i].children.values():
                    sublist.append([s.takeAll() for s in set.elements])
                self.extraScriptData.append(sublist)

    def _parseBackground(self, subFile: ResourceFileSystemFolder):
        colorStream = StructStream(subFile.getRecord(0, kind="data"), endianPrefix=">")
        self.backgroundInitialColors = [colorStream.take("3B") for _ in range(240)]
        self.background = dyuvToRGB(subFile.getRecord(0, kind="video"), 384, 240, self.backgroundInitialColors)
    
    def _parseCollisionData(self, subFile: ResourceFileSystemFolder):
        collisionMap = subFile.getRecord(1, kind="video")
        # The 4 index comes from code.
        self.collisionImage = rl7ToRGB(collisionMap, self.rawPalette, emptySpaceColorIndex=4)

    def showAll(self):
        self.showInfo()
        self.showActors()
        self.showSprites()
        self.showScripts()

    def showInfo(self):
        display(self.info.__dict__)
        #for i, cycler in enumerate(self.info.cyclers):
        #    print("Cycler", i)
        #    display(cycler.__dict__)
        

    def showActors(self):
        for i, actor in enumerate(self.actors):
            print(Actor, i)
            display(actor.__dict__)
            if actor.animation != None:
                display(actor.animation.__dict__)
        for i, desc in enumerate(self.descriptions):
            print("Description", i)
            display(desc.__dict__)
    
    def showSprites(self):
        display(self.background)
        display(self.collisionImage)
        display(self.info.makeTreeHeightImage(self))
        for i, description in enumerate(self.descriptions):
            for j, group in enumerate(description.groups):
                for k, sprite in enumerate(group.sprites):
                    print("ActorDescription", i, "Group", j, "Sprite", k)
                    display(sprite)
                for k, sprite in enumerate(group.unusedSprites):
                    print("ActorDescription", i, "Group", j, "Unused Sprite", k + len(group.sprites))
                    display(sprite)
            for j, group in enumerate(description.unusedGroups):
                for k, sprite in enumerate(group.elements):
                    print("ActorDescription", i, "Unused Group", j + len(description.groups), "Sprite", k)
                    display(sprite)
        for i, tree in enumerate(self.unusedSpriteGroups):
            for j, group in enumerate(tree.elements):
                for k, sprite in enumerate(group.elements):
                    print("Unused ActorDescription", i, "Group", j, "Sprite", k)
                    display(sprite)

    def showScripts(self):
        print(self._prettyPrintScripts())
    
    def unusualDataFlags(self):
        ret = []
        if len(self.extraScriptData) > 0:
            ret.append("Extra script data")
        if len(self.unusedSprites) > 0:
            ret.append("Unused srpites")
        for i, desc in enumerate(self.descriptions):
            if desc.extraUnusedGroups:
                ret.append("Unused group for description index {}".format(i))
        if len(self.vars) > 1:
            ret.append("Has more than one script var")
        return ret

    def export(self, root: str, parentGame: "Game"):
        if len(root) > 0 and root[-1] != "/":
            root += "/"
        
        os.makedirs(root + self.name, exist_ok=True)

        folder = root + self.name + "/"
        self._exportData(folder)
        self._exportImages(folder)
        if self.info.voiceLineIds != None:
            self._exportVoiceLines(folder, parentGame)
        self._exportScripts(folder)

    def _exportData(self, folder: str):
        
        castJson = {
            "actors": self.actors,
            "descriptions": self.descriptions,
        }
        with open(folder + "cast.json", "w") as f:
            json.dump(castJson, f, default=cellSerializer, indent=2)
        
        convertedPalette = ["#" + self.rawPalette[i:i+3].hex() for i in range(0, len(self.palette), 3)]
        cellJson = {
            "palette": convertedPalette,
            "DYUVInitialValues": self.backgroundInitialColors,
            "paletteCycles": None
        }
        if self.info.hasPaletteCycling:
            cellJson["paletteCycles"] = self.info.cyclers
        with open(folder + "cell.json", "w") as f:
            json.dump(cellJson, f, default=cellSerializer, indent=2)

    def _exportScripts(self, folder: str):
        with open(folder + "scripts.py", "w") as f:
            f.write(self._prettyPrintScripts())

    def _exportImages(self, folder: str):
        self.background.save(folder + "background.png", "png")
        self.collisionImage.save(folder + "metadataImage.png", "png")
        self.info.makeTreeHeightImage(self)\
            .save(folder + "spritetreeHeightBoxes.png", "png")

        for i, description in enumerate(self.descriptions):
            for j, group in enumerate(description.groups):
                path = "{}sprites/desc{}/group{}".format(folder, i, j)
                os.makedirs(path, exist_ok=True)
                for k, sprite in enumerate(group.sprites):
                    sprite.save("{}/sprite{}.png".format(path, k), "png")

            metadataImages = description.makeMetadataImages()
            if metadataImages == None:
                print("Failed to make metadata images for description {} on cell {}: No palette data found."\
                      .format(i, self.name))
            else:
                for j, image in enumerate(metadataImages):
                    path = "{}sprites/desc{}/group{}".format(folder, i, j)
                    #os.makedirs(path, exist_ok=True)
                    image.save("{}/metadata.png".format(path), "png")
    
    def _exportVoiceLines(self, folder: str, parentGame: "Game"):
        os.makedirs(folder + "voice", exist_ok=True)
        for lineId in self.info.voiceLineIds:
            localId = lineId - self.info.voiceStartIndex
            filename = "{}voice/line{}".format(folder, localId)
            parentGame._exportVoiceLine(lineId, filename)


    def _prettyPrintScripts(self) -> str:
        """
        Format this cell's scripts in a python-like file. It's very close
        to python, and benefits from syntax highlighting, but it's not actually
        executable.
        """
        ret = "# This is not real python, but approxiamates it.\n\n"
        for i, desc in enumerate(self.descriptions):
            if desc.scripts.isEmpty():
                continue

            if desc.commonName:
                ret += "# Actor description {}\n".format(i)
                className = desc.commonName.replace(".", "_")
            else:
                className = "ActorDescription{}".format(i)
            
            castMembers = [j for j, actor in enumerate(self.actors) if actor.description == desc]
            ret += "# Used for actors: {}\n".format(castMembers)

            ret += desc.scripts.prettyPrint(className)
        
        ret += self.scripts.prettyPrint("Cell")

        if len(self.vars) > 0:
            ret += "\n# Local variables\n"
            var: int
            for i, var in enumerate(self.vars):
                ret += "local{} = {} # {}, {}\n".format(i, var, hex(var), repr(var.to_bytes(2, "big")))
        else:
            ret += "\n# No local variables\n"

        if len(self.extraScriptData) > 0:
            ret += "\n# Extra script data\n"
            ret += "extraData = [\n"
            for sublist in self.extraScriptData:
                ret += "\t{},\n".format(sublist)
            ret += "]\n"
        
        if self.bossData:
            ret += "\n# Boss AI\n"
            ret += self.bossData.toPseudocode()
        
        return ret

#################
# Stuff used for actor metadata images
RED = 6
BLUE = 7
GREEN = 8
BLACK = 9

def makeTargetImage(c: int):
    return PIL.Image.frombytes("P", (5, 5), bytes([
        0, c, c, c, 0,
        c, 0, 0, 0, c,
        c, 0, c, 0, c,
        c, 0, 0, 0, c,
        0, c, c, c, 0
    ]))

targetMask = makeTargetImage(1)
targetMask.putpalette(b'\0\0\0\xFF\xFF\xFF')
targetMask = targetMask.convert("1")
targets = {}
def putTargets(img: PIL.Image.Image, offset: Coords, points: list[Coords], color: int):
    if color not in targets:
        targets[color] = makeTargetImage(color)
    for p in points:
        img.paste(targets[color], (offset.x + p.x - 2, offset.y + p.y - 2), targetMask)

rects = {}
def putRect(img: PIL.Image.Image, offset: Coords, size: Coords, color: int):
    if (size.x, size.y, color) not in rects:
        rectImage = PIL.Image.new("P", (size.x, size.y), 0)
        rectMask = PIL.Image.new("1", (size.x, size.y), 0)
        WHITE = 1
        for x in range(size.x):
            rectImage.putpixel((x, 0), color)
            rectImage.putpixel((x, size.y - 1), color)

            rectMask.putpixel((x, 0), WHITE)
            rectMask.putpixel((x, size.y - 1), WHITE)
        for y in range(size.y):
            rectImage.putpixel((0, y), color)
            rectImage.putpixel((size.x - 1, y), color)

            rectMask.putpixel((0, y), WHITE)
            rectMask.putpixel((size.x - 1, y), WHITE)
        rects[(size.x, size.y, color)] = (rectImage, rectMask)
    else:
        rectImage, rectMask = rects[(size.x, size.y, color)]
    
    img.paste(rectImage, (offset.x, offset.y), rectMask)