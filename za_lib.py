
import json
import os
import copy
from typing import List, Tuple, Dict, Optional, Literal, Self, Iterator, TYPE_CHECKING
from dataclasses import dataclass, asdict

from tqdm import tqdm_notebook as tqdm
import PIL.Image

from struct_stream import StructStream
import cdi_filesystem
from cdi_images import dyuvToRGB, rl7ToRGB
from cdi_audio import saveSoundFile
from za_filesystem import ResourceTree, ResourceFileSystem, \
    ResourceFileSystemFolder, ResourceTreeSet
from za_images import decompressSprite, unpackPointerArray, unpackSpriteTree,\
    getClut, convertClutToRgba, PointerArray
from za_constants import SPELL_LOOKUP, TREASURE_LOOKUP, DIRECTION_LOOKUP
from za_scripts import ScriptSet

# Compat for running scripts in both jupyter and console
try:
    display
except NameError:
    def display(data):
        print(data)

ANIMATION_TYPE_MAYBE_LOOKUP = {
    "default": "UnknownType{}",
    0: "Immobile",
    3: "AnimationActionsOnly",
    4: "PushableBlock",
    5: "Boss", # Not found in files, only applied at runtime.
    6: "FloatingRaft",
    7: "MovingRaft",
    8: "DiagonalBouncingSprite",
    9: "OrthoganalBouncingSprite",
    50: "MagicShieldableHazzard",
}

ACTOR_TYPE_MAYBE_LOOKUP = {
    "default": "UnknownType{}",
    0: "Normal",
    1: "EnemyOrSwitch",
    2: "Loot",
    4: "Hazzard",
    5: "Boss"
}

ACTOR_SCRIPT_TYPE_LOOKUP = {
    "default": "actorType{}",
    0: "onDeathOrRaftRideFinished",
    1: "onTouchOrPushBlockStoppedMoving",
    2: "onPurchaseOrAnimationComplete",
    3: "onHitOrIteractIntercept",
    4: "onItemInteractOrSoundFileDone",
    5: "onLoad_maybe"
}

CELL_SCRIPT_TYPE_LOOKUP = {
    "default": "cellType{}",
    0: "onEntry",
    1: "onLeave",
    2: "onTouchTrigger"
}

LOOT_DROP_TYPE_LOOKUP = {
    0: "Nothing",
    1: "BlueRupee",
    2: "YellowRupee",
    3: "Heart",
    4: "Random"
}

# See `curiosities/Actor Desc Projectile Field.md` for more info.
PROJECTILE_FIELD_LOOKUP = {
    0: "Deny",
    1: "Allow(1)",
    48: "Allow(48)",
    49: "Allow(49)",
    52: "Allow(52)"
}

@dataclass(eq=True, frozen=True)
class Coords:
    """
    Any coordinate position, in pixels, with (0, 0) at the top left.
    """
    x: int
    y: int

    def fromStream(stream: StructStream, xFirst: bool = True) -> Self:
        """Coords are usually stored y first, but sometimes x first."""
        if xFirst:
            x, y = stream.take("hh")
        else:
            y, x = stream.take("hh")
        
        return Coords(x, y)
    
    def __repr__(self):
        return "({}, {})".format(self.x, self.y)

# eq + frozen allows this to be a dictionary key
@dataclass(eq=True, frozen=True)
class ActorDescLocation:
    """
    Describes an actor description's location in a way that can be saved
    to a json file.
    
    Used for the spriteNames.json file.
    """

    # True if the cell is in the `over.rtf` file, false if it's in `under.rtf`
    isOverworld: bool
    cell: str
    # The index of this description in the cell's actor description array.
    index: int

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

@dataclass
class BoundingBox:
    minX: Optional[int] = None
    maxX: Optional[int] = None
    minY: Optional[int] = None
    maxY: Optional[int] = None
    
    def updateMaxAndMin(self, coords):
        if isinstance(coords, list):
            for p in coords:
                self.updateMaxAndMin(p)
            return
        elif isinstance(coords, Coords):
            x = coords.x
            y = coords.y
        elif isinstance(coords, tuple):
            x = coords[0]
            y = coords[1]
    
        if self.minX == None:
            self.minX = x
            self.maxX = x
            self.minY = y
            self.maxY = y
        else:
            self.maxX = max(self.maxX, x + 3)
            self.minX = min(self.minX, x - 2)
            self.maxY = max(self.maxY, y + 3)
            self.minY = min(self.minY, y - 2)

    def width(self):
        return self.maxX - self.minX
    
    def height(self):
        return self.maxY - self.minY
    
def _cellSerializer(o):
    """
    Function to extend json.dump for more types.

    Classes can implement the magic method serializeToDict() to customize
    the fields that are serialized.
    """
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


class Game:
    ##############
    # Cells

    # Cells from `over.rtf`
    overworldCells: Dict[str, "Cell"]
    # Cells from `under.rtf`
    underworldCells: Dict[str, "Cell"]
    # Overworld cells that had errors while parsing
    errorOverworldCells: List[str]
    # Underworld cells that had errors while parsing
    errorUnderworldCells: List[str]

    ##############
    # Common Data
    #
    # This data is stored separately from all other cells, because it's used on every
    # screen. All of this data is parsed during __init__().

    # The actor entry for Zelda.
    zeldaActor: "Actor"
    # The actor description for loot (hearts, rupees (no I will not call them rubies))
    lootActorDesc: "ActorDescription"
    # Heart sprites, used for the health bar. I think this is also used for the heart
    # loot?
    heartSprites: List[PIL.Image.Image]
    rupeeCounterSprite: PIL.Image.Image
    # Weapon animation definitions (scripts, actors, sprites, etc) organized by weapon
    # name.
    weapons: Dict[str, "Attack"]

    ##############
    # Aggregate Data
    #
    # Various fields that organize info from all the cells in the game for easier lookup.

    # A list of all actor descriptions across all cells, organized by name. Actors are
    # considered "the same" if they have identical sprites. Uses names that I came up with,
    # or that were provide by fans; name list can be edited in `spriteNames.json` file.
    spriteNames: Dict[str, List[List[ActorDescLocation]]]

    # The reverse of the spriteNames list, for convenience.
    spriteNameReverseLookup: Dict[ActorDescLocation, str]

    ##############
    # Internal data

    # The CDI disk's filesystem
    _gameData: cdi_filesystem.CdiFileSystem
    
    # `zelda.rtf`
    _mainFile: ResourceFileSystem
    # `zelda_rl.rtf`
    _zeldaRlFiles: ResourceFileSystem
    # `over.rtf`
    _overFiles: ResourceFileSystem
    # `under.rtf`
    _underFiles: ResourceFileSystem
    # `zelda_audio.rtf`
    _audioFiles: ResourceFileSystem
    # `zelda_voice.rtf`
    _voiceFiles: ResourceFileSystem


    def __init__(self, dataFileName: str):
        self.errorOverworldCells = []
        self.errorUnderworldCells = []
        self.overworldCells = {}
        self.underworldCells = {}

        self._gameData = cdi_filesystem.loadCdiImageFile(dataFileName)
        mainMapStream = StructStream(self._gameData.files["zelda.mapres"].getBytes(), endianPrefix=">")
        self._mainFile = ResourceFileSystem(mainMapStream, self._gameData.files["zelda.rtf"])
        self._zeldaRlFiles = self._parseSubFile("rmap", "zelda_rl.rtf")
        self._overFiles = self._parseSubFile("omap", "over.rtf")
        self._underFiles = self._parseSubFile("umap", "under.rtf")
        self._audioFiles = self._parseSubFile("amap", "zelda_audio.rtf")
        self._voiceFiles = self._parseSubFile("vmap", "zelda_voice.rtf")

        self._parseCommonData()
        self._parseZeldaWeapons()
        self._parseSpriteNames()
        
    def _parseCommonData(self):
        """
        Parse zelda, sparkle & smoke effects, loot, weapons, and HUD sprites.
        """
        
        # The special "zinit" file is stored next to other cells, but is not a cell. zinit is
        # probably short for "zelda init".
        #
        # Data record 0 has the metadata as a Resource Tree.
        # Data record 1 has zelda's sprites in a Sprite Tree.
        # Video record 0 has loot and HUD sprites.
        zinit = self._mainFile.subFiles["zinit"]
        commonData = zinit.getRecord(0, kind="data")
        commonResources = ResourceTree.parseFromStream(StructStream(commonData, endianPrefix=">"))

        # The zinit metadata sections are:
        #   zsp_cast: Same format as sp_cast for cells. Only one entry, for Zelda.
        #   zsp_desc: Same format as sp_desc for cells. Only one entry, for Zelda.
        #   zsp_groups: Same format as sp_groups for cells. All entries are for zelda.
        #   csp_desc: Same format as sp_desc for cells. I think there's only one entry? That might be
        #       wrong, though. First entry is for loot drops.
        #   csp_groups: Same format as sp_groups for cells. I think there's only one entry, for loot.
        #   zelda: CLUT table for zelda's sprites. Stored as an "array" of 1 element.
        #   display: CLUT table for hud and loot sprites. Stored as an "array" of 1 element.
        #
        # The "z" prefix is for zelda, and the "c" prefix probably stands for "common".

        self.zeldaActor = Actor(commonResources.children["zsp_cast"].elements[0])
        self.zeldaActor.description = ActorDescription(commonResources.children["zsp_desc"].elements[0])
        self.zeldaActor.description.groups = \
            [SpriteGroup(s.copy()) for s in commonResources.children["zsp_groups"].elements]
        # TODO: Confirm if there is only one csp_desc entry.
        self.lootActorDesc = ActorDescription(commonResources.children["csp_desc"].elements[0])
        self.lootActorDesc.groups = [
            SpriteGroup(commonResources.children["csp_groups"].elements[0])
        ]

        # Decode the CLUT tables. There's one for Zelda and one for everything else.
        zeldaSpriteData = zinit.getRecord(1, kind="data")
        zeldaPalette = getClut(commonResources.children["zelda"].elements[0].takeAll())
        zeldaPalette = convertClutToRgba(zeldaPalette, indices=[0])
        hudPalette = getClut(commonResources.children["display"].elements[0].takeAll())
        hudPalette = convertClutToRgba(hudPalette, indices=[0])

        # The clut values are positioned manually by code, so these sizes/indices are magic.
        # Zelda's palette begins at 0x18 and ends at 0x48
        preColors = [b'\0\0\0\0'] * 0x18
        preColors[BLACK] = b'\0\0\0\xFF'
        preColors[GREEN] = b'\0\xFF\0\xFF'
        preColors[RED] = b'\xFF\0\0\xFF'
        preColors[BLUE] = b'\0\0\xFF\xFF'
        zeldaPalette = b''.join(preColors) + zeldaPalette
        # The HUD palette begins at 0x8 and ends at 0x18
        hudPalette = (b'\0\0\0\0' * 0x8) + hudPalette

        # Unpack zelda's sprites. The sprite tree only has one top-level item, since it's just zelda.
        tree = unpackSpriteTree(zeldaSpriteData, zeldaPalette, "RGBA")
        self.zeldaActor.description._assignSprites(tree.elements[0])
        
        # Loot and HUD sprites are mixed together. The video record starts with a pointer array with
        # the sprite indices, then the sprite data follows.
        hudSpriteStream = StructStream(zinit.getRecord(0, kind="video"), endianPrefix=">")
        hudSprites = [decompressSprite(s, hudPalette, "RGBA") for s in unpackPointerArray(hudSpriteStream).elements]
        self.heartSprites = hudSprites[:3]
        self.rupeeCounterSprite = hudSprites[4]
        self.lootActorDesc.groups[0].sprites = hudSprites
    
    def _parseZeldaWeapons(self):
        """Parse each of the attacks for zelda's weapons. The attack and weapon format is not well understood."""
        
        # The special "invent" file is stored next to other cells, but is not a cell.
        # Data record 0: ???
        # Data record 1: Inventory metadata as a Resource Tree.
        # TODO: What is in record 0? Are there other records not analyzed yet?
        inventoryDataRaw = self._mainFile.subFiles["invent"].getRecord(1, "data")
        inventoryData = ResourceTree.parseFromStream(StructStream(inventoryDataRaw, endianPrefix=">"))

        # The invent metadata sections are:
        #   labels: An array of null-terminated strings. These are the names of the sub-files for each weapon,
        #           in _mainFile. The array order is the same as in zelda's inventory, shifted by +1. So the
        #           weapon with id 3 has a definition file, and that filename is at index 2 in this array.
        #           The game only loads the currently equipped weapon's file in memory.
        #
        weaponFiles = [s.takeNullTermString().decode('ascii') for s in inventoryData.children["labels"].elements]
        
        # Parse each weapon file.
        self.weapons: Dict[str, Attack] = {}
        bar = tqdm(total=len(weaponFiles))
        for i, filename in enumerate(weaponFiles):
            bar.desc = SPELL_LOOKUP[i]
            commonName = SPELL_LOOKUP[i]
            self.weapons[commonName] = self._parseZeldaWeapon(filename, i + 1)
            bar.update(1)
        bar.close()

    def _parseZeldaWeapon(self, filename: str, id: int) -> "Attack":
        """Parse one weapon from its definition file. `id` is the weapon item's id."""

        # Some weapons share definition files. Each file has the id of one of the weapons (the lowest one, 
        # I think?), so if the id doesn't match we can infer that this file is being shared.
        if str(id) not in filename:
            sharedWithWeapon = SPELL_LOOKUP[int(filename[2:])]
        else:
            sharedWithWeapon = None

        # The special weapon file is stored next to other cells, but is not a cell.
        # Data record 0: Weapon metadata as a Resource Tree
        # Data record 1: Projectile sprites as a Sprite Tree
        file = self._mainFile.subFiles[filename]

        # The weapon metadata is organized very similar to a cell.
        #   sp_desc: Same format as sp_desc for cells. Descriptions are for the projectile fired by the
        #            weapon. There is always exactly one entry.
        #   sp_groups: Same format as sp_groups for cells.
        #   clut: An "array" with one element, which contains the packed CLUT data for the weapon's sprites.
        #   wp_cmds: The script for this weapon, encoded as an array of 4-byte integers. See the `Attack`
        #            class for more info.
        weaponDataStream = StructStream(file.getRecord(0, kind="data"), endianPrefix=">")
        weaponData = ResourceTree.parseFromStream(weaponDataStream)
        palette = getClut(weaponData.children["clut"].elements[0].takeAll())
        palette = convertClutToRgba(palette, indices=[0])

        # The weapon clut begins at 0x48 and ends at 0x58
        palette = (b'\0\0\0\0' * 0x48) + palette

        assert len(weaponData.children["sp_desc"].elements) == 1
        desc = ActorDescription(weaponData.children["sp_desc"].elements[0])
        desc.groups = [SpriteGroup(s) for s in weaponData.children["sp_groups"].elements]

        spriteData = file.getRecord(1, kind="data")
        spriteTree = unpackSpriteTree(spriteData, palette, "RGBA")
        assert len(spriteTree.elements) == 1
        # Still not sure what `unusedPointer` is for, but it's always zero for weapon sprites.
        assert spriteTree.unusedPointer == 0
        desc._assignSprites(spriteTree.elements[0])

        commands = [s.take("I") for s in weaponData.children["wp_cmds"].elements]
        return Attack(desc, id, commands, sharedWithWeapon)

    def _parseSubFile(self, mapSubfileName, realFileName) -> ResourceFileSystem:
        """Helper function to apply resource maps to real files."""
        map = self._mainFile.subFiles[mapSubfileName].getBytes()
        stream = StructStream(map, endianPrefix=">")
        return ResourceFileSystem(stream, self._gameData.files[realFileName])
    
    def _parseSpriteNames(self):
        """
        Parse the sprite names file. See `spriteNames_format.md` for more info.

        TODO: Cleanup the json file's unused fields.
        """
        with open("spriteNames.json", "r") as f:
            rawData: dict = json.load(f)

        # Reset the current maps.
        self.spriteNames: Dict[str, List[List[ActorDescLocation]]] = {}
        self.spriteNameReverseLookup: Dict[ActorDescLocation, str] = {}
        
        variants: List[dict]
        for name, variants in rawData.items():
            parsedVariants: List[List[ActorDescLocation]] = []
            variant: dict
            for variant in variants:
                locations: List[dict] = variant["locations"]
                parsedLocations: List[ActorDescLocation] = []
                for location in locations:
                    parsedLoc = ActorDescLocation(
                        location["isOverworld"],
                        location["cell"],
                        location["descIndex"]
                    )

                    # Ensure no locations are duplicated.
                    assert parsedLoc not in self.spriteNameReverseLookup, parsedLoc
                    
                    # Add to both lookup tables.
                    self.spriteNameReverseLookup[parsedLoc] = name
                    parsedLocations.append(parsedLoc)
                parsedVariants.append(parsedLocations)
            self.spriteNames[name] = parsedVariants

    def cellNames(self, duplicates: bool = False) -> Iterator[Tuple[str, bool]]:
        """
        Returns an iterator over all cell names, and which world they're in. Very
        cheap operation. `True` means Overworld, `False` means underworld.

        If a cell is in both the Overworld and Underworld, the `duplicates`
        parameter controls whether it's output once or twice.
        """
        for name in self._overFiles.subFiles:
            yield (name, True)
        for name in self._underFiles.subFiles:
            if duplicates or name not in self._overFiles.subFiles:
                yield (name, False)
    
    def cellDuplicateNames(self) -> Iterator[str]:
        """
        Returns an iterator over all cell names that appear in both the overworld
        and the underworld. Very cheap operation.
        """
        for name in self._underFiles.subFiles:
            if name in self._overFiles.subFiles:
                yield name

    def cells(self, duplicates: bool = True, useTqdm: bool = True) -> Iterator["Cell"]:
        """
        Returns an iterator over parsed cells, with an optional loading bar.
        Cells are parsed lazily, right before they're returned by the iterator,
        if they aren't already in the cell cache.

        If `duplicates=False` and a cell is in both the Overworld and
        Underworld, only the Overworld version is returned.
        """
        
        if useTqdm:
            bar = tqdm(total = self.totalCellCount())
        
        try:
            for name in self._overFiles.subFiles:
                if useTqdm:
                    bar.desc = name
                yield self.getCell(name, True)
                if useTqdm:
                    bar.update(1)
            for name in self._underFiles.subFiles:
                if useTqdm:
                    bar.desc = name
                if duplicates or name not in self._overFiles.subFiles:
                    yield self.getCell(name, False)
                if useTqdm:
                    bar.update(1)
        finally:
            if useTqdm:
                bar.close()
    
    def totalCellCount(self) -> int:
        """Get the total number of cells in the game."""
        return len(self._overFiles.subFiles) + len(self._underFiles.subFiles)

    def exportJustScripts(self, path):
        """
        Exports all the cell scripts into a separate directory. Useful for
        e.g. looking up every script for a particular shrine.

        The `path` argument MAY end in `/` but this is not required.
        """

        # Correct the path if needed
        if path[-1] != "/":
            path += "/"
        bar = tqdm(total=len(self._overFiles.subFiles) + len(self._underFiles.subFiles))
        
        def exportWorld(folder: str, names: List[str], isOverworld: bool):
            """
            Sub-function to export a single world. Assumes that `folder` DOES NOT
            end in `/`.
            """
            # Make intermediate directories, if needed.
            os.makedirs(folder, exist_ok=True)

            # Go through every cell.
            for name in names:
                bar.desc = name

                # Get the cell from the cache (parsing it if needed).
                cell = self.getCell(name, isOverworld)

                # Save the scripts. The prettyPrint function mimics Python syntax,
                # but it's not actually python code. But it makes understanding
                # easier and enables nice syntax highlighting.
                with open("{}/{}.py".format(folder, name), "w") as f:
                    f.write(cell._prettyPrintScripts())
                
                # Advance the progress bar.
                bar.update(1)
        
        # Apply that sub-function to both overworld and underworld.
        try:
            exportWorld(path + "overworld", self._overFiles.subFiles.keys(), True)
            exportWorld(path + "underworld", self._underFiles.subFiles.keys(), False)
        finally:
            bar.close()

    def getCell(self, name: str, isOverworld: Optional[bool] = None, silenceWarning: bool = False) -> "Cell":
        """
        Returns a parsed cell from the cell cache, or parses it from the
        rtf file if needed.

        If `isOverworld` is not provided, both worlds are checked. If it
        is in both worlds, the Overworld is used and a warning is printed.
        These warnings can be silenced using `silenceWarning=True`.

        Raises an `Exception` if the cell does not exist.
        """
        
        if isOverworld == None:
            # Figure out if the cell is in the overworld or underworld.
            if name in self._overFiles.subFiles:
                isOverworld = True
            
            if name in self._underFiles.subFiles:
                if isOverworld != None:
                    if not silenceWarning:
                        print("Warning: cell", name, "exists in both overworld and underworld. Using overworld version.")
                else:
                    isOverworld = False
            
            if isOverworld == None:
                raise Exception("Cell {} does not exist in either overworld or underworld".format(name))
        
        if isOverworld:
            file = self._overFiles
            parsed = self.overworldCells
            worldName = "overworld"
        else:
            file = self._underFiles
            parsed = self.underworldCells
            worldName = "underworld"
        
        if name not in file.subFiles:
            raise Exception("Cell {} does not exist in {}".format(name, worldName))
        
        # Is the cell in the cache?
        if name not in parsed:
            # Parse and cache it.
            parsed[name] = self._parseCell(file.subFiles[name], name, isOverworld)

        return parsed[name]

    def parseAllCells(self, refresh = False):
        """
        Force all cells to be parsed. Provides a tqdm bar.
        
        If `refresh=True`, all previously parsed cells are deleted from the cell
        cashe first.
        """

        # Clear cache?
        if refresh:
            self.overworldCells = {}
            self.underworldCells = {}

        # Force all cells to be parsed by iterating over them, but don't do anything
        # with the results.
        #
        # TODO: Test this code. It should behave identically to the original code,
        # but the original code is preserved below in case it fails. Whoever runs
        # this function next can comment out the new code if needed.
        for _ in self.cells():
            pass
        return
        
        bar = tqdm(total=len(self._overFiles.subFiles) + len(self._underFiles.subFiles))
        errorOverworldCells = []
        for name, file in self._overFiles.subFiles.items():
            bar.set_description("overworld: " + name)
            
            try:
                if name not in self.overworldCells:
                    self.overworldCells[name] = self._parseCell(file, name, True)
            except KeyboardInterrupt as e:
                raise e
            except:
                print("Error while parsing overworld", name)
                errorOverworldCells.append(name)
            
            bar.update(1)
            
        errorUnderworldCells = []
        
        for name, file in self._underFiles.subFiles.items():
            bar.set_description("underworld: " + name)
            
            try:
                if name not in self.underworldCells:
                    self.underworldCells[name] = self._parseCell(file, name, False)
            except KeyboardInterrupt as e:
                raise e
            except:
                print("Error while parsing underworld", name)
                errorUnderworldCells.append(name)
            
            bar.update(1)

        bar.close()
    
    def _parseCell(self, file: ResourceFileSystemFolder, name: str, isOverworld: bool) -> "Cell":
        """
        Do the work of actually parsing a cell. This function DOES NOT add
        the parsed cell to any lists/caches!

        The reason for a separate function is to implement the sprite name
        lookups.
        """
        
        # Parse the cell normally.
        ret = Cell(file, name, isOverworld)

        # Correlate the cell's Actor Descriptions with entries in the sprite
        # name table.
        for i, desc in enumerate(ret.descriptions):
            location = ActorDescLocation(isOverworld, name, i)

            # Every actor description needs to be accounted for in spriteNames.json
            assert location in self.spriteNameReverseLookup, location

            desc.commonName = self.spriteNameReverseLookup[location]
        return ret            
    
    def getSpritesByName(self, name: str, variant: int = 0) -> "SpriteGroup":
        """
        Get the sprite group for a given NPC name. Uses the first location in
        the locations list to fetch the sprite group.

        The variant defaults to 0 (the first variant).
        """
        location = self._getActorVariantLocationsByName(name, variant)[0]
        desc = self._getActorByLocation(location)
        return desc.groups
    
    def getActorsByName(self, name: str, variant: int = 0) -> List["ActorDescription"]:
        """
        Get all actor descriptions for a given NPC name, across all cells in
        the game.

        The variant defaults to 0 (the first variant).
        """
        locations = self._getActorVariantLocationsByName(name, variant)
        return [self._getActorByLocation(l) for l in locations]

    def _getActorByLocation(self, location: ActorDescLocation) -> "ActorDescription":
        """
        Find the actor description that corresponds to a particular location entry
        in spriteNames.json.
        """
        cell = self.getCell(location.cell, location.isOverworld)
        return cell.descriptions[location.index]
    
    def getAllActorVariantsByName(self, name: str) -> List[List["ActorDescription"]]:
        """
        List all the actor descriptions for all the variants of an NPC name.
        """

        # Sanity check: `name` is an NPC name
        assert name in self.spriteNames, name

        # Iterate through the variants, and collect the descriptions for them.
        variants = self.spriteNames[name]
        ret = []
        for variant in variants:
            ret.append([self._getActorByLocation(l) for l in variant])
        return ret

    def _getActorVariantLocationsByName(self, name: str, variant: int) -> List["ActorDescription"]:
        """
        Resolves a (name, variantIndex) pair, with proper sanity checks.

        Equivalent to `self.spriteNames[name][variant]`
        """
        assert name in self.spriteNames, name
        variants = self.spriteNames[name]
        assert variant < len(variants), "{} < {}".format(variant, len(variants))
        return variants[variant]
    
    def assignVoiceLines(self):
        """
        Determine which voice lines belong to which cells. This is a rather slow
        process.

        Each cell contains the start index for their voice lines, and the cell's
        scripts contain the index-offsets for individual voice lines. But the cell
        doesn't know where its voice lines "end". You could figure that out by
        finding the `max` of the used voice lines, but that would cause unused
        voice lines to be left out.

        So the solution is to sort the cells by their start index, and then use
        the next cell's start index as their own end index. This guarantees each
        voice line is included in a cell's data, even if it's unused.

        The method assumes that scripts don't "share" voice lines by using
        overlapping start and "end" indices. I checked this, and the assumption
        is correct for this game, thankfully!
        """

        # If we don't parse all the cells first, this sort
        # is really slow.
        self.parseAllCells()

        # Sort all the cells by voiceStartIndex, then get their names.
        cellsInVoiceOrder: List[str] = list(map(
            lambda c: c.name,
            sorted(self.cells(duplicates=False, useTqdm=False), key=lambda c: c.info.voiceStartIndex)))
        
        bar = tqdm(total=self.totalCellCount())
        
        # For each cell, store the indices of voice lines that belong to it, using
        # the next cell's start index to compute the range.
        #
        # silenceWarning=True because I'm handling duplicate cells below
        for i in range(len(cellsInVoiceOrder) - 1):
            current = self.getCell(cellsInVoiceOrder[i], silenceWarning=True)
            bar.desc = current.name
            next = self.getCell(cellsInVoiceOrder[i + 1], silenceWarning=True)
            start = current.info.voiceStartIndex
            end = next.info.voiceStartIndex
            # Note: `start` might equal `end`, and `list` handles that correctly.
            current.info.voiceLineIds = list(range(start, end))
            bar.update(1)

        # The last cell is special, because there is no next cell to use as the
        # end index.
        lastCell = self.getCell(cellsInVoiceOrder[-1], silenceWarning=True)
        bar.desc = lastCell.name
        start = lastCell.info.voiceStartIndex
        end = len(self._voiceFiles.subFiles)
        lastCell.info.voiceLineIds = list(range(start, end))
        bar.update(1)

        # Now handle duplicate cells. Copy the voice lines into their underworld
        # counterpart.
        for name in self.cellDuplicateNames():
            bar.desc = name
            self.getCell(name, False).info.voiceLineIds = self.getCell(name, True).info.voiceLineIds
            bar.update(1)

    def export(self, root):
        """
        Exports all of the game's data into the directory path `root`. The `root`
        path MAY end in `/`, it is not required.
        """
        self.assignVoiceLines()
        if root[-1] != "/":
            root += "/"

        self._exportCommonData(root + "common")
        
        overworldFolder = root + "overworld"
        underworldFolder = root + "underworld"
        for cell in self.cells(duplicates=True):
            if cell.info.isOverworld:
                cell.export(overworldFolder, self)
            else:
                cell.export(underworldFolder, self)
    
    def _exportCommonData(self, commonRoot):
        """
        Exports all of the game's common data (shared by all cells) to the
        directory path `commonRoot`. ASSUMES that commonRoot does not end
        in `/`.
        """
        os.makedirs(commonRoot + "/zelda", exist_ok=True)
        castJson = {
            "zeldaActor": self.zeldaActor,
            "zeldaDescription": self.zeldaActor.description,
            "lootDescription": self.lootActorDesc,
            "weapons": self.weapons
        }
        with open(commonRoot + "/zelda/cast.json", "w") as f:
            json.dump(castJson, f, default=_cellSerializer)

        for i, group in enumerate(self.zeldaActor.description.groups):
            for j, sprite in enumerate(group.sprites):
                os.makedirs("{}/zelda/sprites/group{}".format(commonRoot, i), exist_ok=True)
                sprite.save("{}/zelda/sprites/group{}/sprite{}.png".format(commonRoot, i, j), "png")
        metadataImages = self.zeldaActor.description.makeMetadataImages()
        assert metadataImages != None
        for i, image in enumerate(metadataImages):
            image.save("{}/zelda/sprites/group{}/metadata.png".format(commonRoot, i), "png")

        os.makedirs(commonRoot + "/hudSprites", exist_ok=True)
        sprite: PIL.Image.Image
        for i, sprite in enumerate(self.lootActorDesc.groups[0].sprites):
            sprite.save("{}/hudSprites/{}.png".format(commonRoot, i), "png")

        # TODO: Export weapons
        #for weapon in self.weapons.values():
        #    os.makedirs("{}/weaponSprites/{}".format(commonRoot, weapon.name), exist_ok=True)
        #    

    def _exportVoiceLine(self, globalId: int, filename: str):
        """
        Encodes a single voice line as a WAV file, by its global ID value.

        Used by `Cell` to export voice lines, because `Game` retains the actual
        audio data streams.
        """
        file = self._voiceFiles.subFiles[globalId]
        sectors = self._voiceFiles.realFile.sectors[file.blockOffset:]
        foundFile = saveSoundFile(sectors, 1 << (file.channel & 0x7F), filename)
        assert foundFile, (globalId, filename, file.__dict__)

class Attack:
    """
    The sprites and metadata to define an attack, its projectile actors, and
    how they're animated.
    """
    # The item/inventory ID for the weapon/spell.
    id: int
    # The name of the weapon/spell. This list is manual, the names aren't in
    # the raw data.
    name: str
    # The actor description for the projectile.
    desc: "ActorDescription"
    # The commands that spawn the projectiles and animate them. We still don't
    # know what the commands do, exactly.
    commands: List[int]
    # Weapons can share metadata with other weapons. This contains the "parent"
    # or original weapon's name.
    sharedWithZeldaWeapon: Optional[str]

    def __init__(self, desc: "ActorDescription", id: int, commands: List[int], sharedWithZeldaWeapon: Optional[str] = None):
        self.id = id
        self.name = SPELL_LOOKUP[id]
        self.desc = desc
        self.commands = commands
        self.sharedWithZeldaWeapon = sharedWithZeldaWeapon

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
    animationType: str
    # The description for this actor.
    description: Optional["ActorDescription"]
    # The animation state for this actor.
    animation: Optional["Animation"]

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
        
        if animationType in ANIMATION_TYPE_MAYBE_LOOKUP:
            self.animationType: str = ANIMATION_TYPE_MAYBE_LOOKUP[animationType]
        else:
            self.animationType = ANIMATION_TYPE_MAYBE_LOOKUP["default"].format(animationType)
        
        assert x == 0 and y == 0, "Nonzero current position: ({}, {})".format(x, y)
        assert touchDuration == 0, "Nonzero touch duration: {}".format(touchDuration)
        assert frame == 0, "Nonzero frame value: {}".format(frame)
        assert iframeState == 0, "Nonzero iframeState: {}".format(iframeState)
        assert unk_0x31 == 0, unk_0x31

        self.description: Optional[ActorDescription] = None
        self.animation: Optional["Animation"] = None

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
    collisionSamplePoints: List[Coords]
    bonusDamage: int
    unk_0x2b: int
    unk_0x2c: int
    canUseProjectiles: str
    type_maybe: str
    lootDropped: str
    groupCount: int
    maxHealth_maybe: int
    useCostOrDefense: int
    unk_0x14: int
    unk_0x15: int
    weakToSpell: str
    interactsWithItem: str
    groups: Optional[List["SpriteGroup"]]
    scripts: Optional["ScriptSet"]
    unusedSpritePointer: Optional[int]
    unusedGroups: List["SpriteGroup"]
    _cachedHashOfGroups: Optional[int]
    commonName: Optional[str]

    def __init__(self, stream: StructStream):
        assert len(stream) == 46

        self.size = Coords.fromStream(stream, xFirst=False)
        self.groupCount, pointer1, pointer2 = stream.take("HII")
        
        self.maxHealth_maybe, self.useCostOrDefense = stream.take("HH")
        self.baseDamageOrPurchasePrice_maybe, padding = stream.take("HH")

        self.collisionSamplePoints: List[Coords] = []
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

        assert projectile in PROJECTILE_FIELD_LOOKUP, projectile
        self.canUseProjectiles = PROJECTILE_FIELD_LOOKUP[projectile]

        if metaType_maybe in ACTOR_TYPE_MAYBE_LOOKUP:
            self.type_maybe: str = ACTOR_TYPE_MAYBE_LOOKUP[metaType_maybe]
        else:
            self.type_maybe = ACTOR_TYPE_MAYBE_LOOKUP["default"].format(metaType_maybe)
        
        assert lootDropped in LOOT_DROP_TYPE_LOOKUP, lootDropped
        self.lootDropped = LOOT_DROP_TYPE_LOOKUP[lootDropped]

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

        self.groups: Optional[List[SpriteGroup]] = None
        self.scripts: Optional["ScriptSet"]  = None
        self.unusedSpritePointer: Optional[int] = None
        self.unusedGroups: List[SpriteGroup] = []
        self._cachedHashOfGroups: Optional[int] = None
        self.commonName: Optional[str] = None

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
    
    def makeMetadataImages(self, palette: Optional[bytes] = None) -> Optional[List[PIL.Image.Image]]:
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
        box.updateMaxAndMin(self.collisionSamplePoints)
        box.updateMaxAndMin(self.size)
        for g in self.groups:
            box.updateMaxAndMin(g.treeHeightSamples)
            box.updateMaxAndMin(g.damageSamplePoints_maybe)
            for s in g.sprites:
                box.updateMaxAndMin(s.size)
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
        self.sprites: Optional[List[PIL.Image.Image]] = None
        self.unusedSprites: List[PIL.Image.Image] = []
        self.unusedSpritePointer: Optional[int] = None
        self._cachedHash: Optional[int] = None
    
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

class CycleDefinition:
    CYCLE_MODES = {
        1: "IncreaseOnly",
        2: "Oscillate"
    }

    CYCLE_DIRECTION_LOOKUP = {
        1: "Increasing",
        2: "Decreasing"
    }

    STAGGER_MODES = {
        0: "None",
        3: "RandomAfterLooping",
    }

    def __init__(self, stream):
        assert len(stream) == 20, len(stream)
        self.start, self.length, mode, self.delay = stream.take("HHHH")
        self.currentOffset, cycleDirection, enabled, self.timer = stream.take("HHHh")
        staggerMode, hasLooped = stream.take("HH")

        self.errors: List[str] = []

        self.start: int
        self.length: int
        self.delay: int
        self.currentOffset: int
        self.timer: int
        
        assert len(stream) == 0, stream

        self.mode: Optional[Literal["IncreaseOnly", "Oscillate"]]
        if mode == 1:
            self.mode = "IncreaseOnly"
        elif mode == 2:
            self.mode = "Oscillate"
        else:
            self.errors.append("Unknown mode {}".format(mode))
            self.mode = None

        self.cycleDirection: Optional[Literal["Increasing", "Decreasing"]]
        if cycleDirection == 1:
            self.cycleDirection = "Increasing"
        elif cycleDirection == 2:
            self.cycleDirection = "Decreasing"
        else:
            self.errors.append("Unknown direction {}".format(cycleDirection))
            self.cycleDirection = None

        self.staggerMode: Optional[Literal["None", "RandomAfterLooping"]]
        if staggerMode == 0:
            self.staggerMode = "None"
        elif staggerMode == 3:
            self.staggerMode = "RandomAfterLooping"
        else:
            self.errors.append("Unknown stagger mode {}".format(staggerMode))
            self.staggerMode = None
        
        self.enabled = enabled != 0
        self.hasLooped = hasLooped != 0
    
    def getRange(self) -> range:
        return range(self.start, self.start + self.length)

    def isUsed(self, image: PIL.Image.Image, palette: bytes) -> bool:
        if not self.enabled:
            return False
        
        if self.length == 0:
            return False
        
        usedColors = [p for count, p in image.getcolors()]
        atLeastOneUsedColor = False
        for i in self.getRange():
            if i in usedColors:
                atLeastOneUsedColor = True
                break
        if not atLeastOneUsedColor:
            #print("Skipping cycler; no pixels use the colors")
            return False
        
        return True
    
    def overlapsWith(self, other: Self) -> bool:
        r = self.getRange()
        for color in other.getRange():
            if color in r:
                return True
        return False

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

        musicData: List[StructStream] = tree.children["play;"].elements
        voiceData: List[StructStream] = tree.children["voice"].elements
        self.musicName: Optional[str]
        self.voiceStartIndex: Optional[bytes] = None
        self.voiceLineIds: Optional[List[int]] = None
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
        self._cachedTreeHeightRegionImage: Optional[PIL.Image.Image] = None
        self.unusedSpritePointer: Optional[int] = None
    
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

@dataclass
class AnimationCommand:
    coords: Coords
    command: str

    def __repr__(self):
        if self.command == "nop":
            return repr(self.coords)
        else:
            return "{{{}, then {}}}".format(self.coords, self.command)

class Animation:
    def __init__(self, vectorStream: StructStream, tableStream: StructStream):
        self.vectorUnkCoord_maybeStart = Coords.fromStream(vectorStream)
        self.error = False
        tableSize: int = vectorStream.take("H")
        pointer1, pointer2 = vectorStream.take("II")
        assert pointer1 == 0 and pointer2 == 0, (pointer1, pointer2)
        assert len(vectorStream) == 0, len(vectorStream)

        if len(tableStream) < tableSize * 2:
            print("Malformed animation table: expected {} bytes, found {}" \
                  .format(tableSize * 2, len(tableStream)))
            self.error = True
        
        table: List[int] = list(tableStream.take("{}H".format(tableSize), fillZeros=True))
        
        self.commands: List[str] = []
        for encoded in table:
            # X and Y are encoded as bias-signed nibbles.
            x = ((encoded >> 4) & 0xF) - 8
            y = (encoded & 0xF) - 8

            param = (encoded >> 8) & 0xF
            opcode = (encoded >> 12) & 0xF
            
            if opcode == 0:
                command = "nop"
            elif opcode == 1:
                command = "setGroup({})".format(param)
            elif opcode == 2:
                command = "shootProjectile()"
            elif opcode == 3:
                command = "stopMovement(random(0, 128))"
            elif opcode == 5:
                command = "self.invulnerable = {}".format(param > 0)
            elif opcode == 6:
                command = "triggerAndDespawn()"
            else:
                command = "InvalidOp{}({})".format(opcode, param)
            self.commands.append(AnimationCommand(Coords(x, y), command))

    def serializeToDict(self):
        ret = copy.copy(self.__dict__)
        if self._extraTableData == None:
            del ret["_extraTableData"]
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

    
    def _parseActors(self, data) -> Tuple[List["Actor"], List["ActorDescription"]]:
        tree = ResourceTree.parseFromStream(StructStream(data, endianPrefix=">"))
        self.actors = [Actor(s) for s in tree.children["sp_cast"].elements]
        
        self._vectorData: Optional[StructStream] = None
        self._tableData: Optional[StructStream] = None
        self._weaponData: Optional[StructStream] = None

        self.descriptions: List[ActorDescription] = []
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
                    if actor.animationType in ["UnknownType1", "FloatingRaft", "MovingRaft"]:
                        actor.animation = animations[i]
                        i += 1
                assert i == len(tree.children["sp_vector"].elements), (i, tree.children["sp_vector"].elements, self.showActors())

            if "wp_cmds" in tree.children:
                self._weaponData = tree.children["wp_cmds"]
        
    def _parseSprites(self, subFile: ResourceFileSystemFolder):
        self.rawPalette = getClut(subFile.getRecord(7, kind="data"))
        self.palette = convertClutToRgba(self.rawPalette, indices=[0, 4])

        sprites = subFile.getRecord(5, kind="data")
        hasNonzeroByte = False
        for b in sprites:
            if b != 0:
                hasNonzeroByte = True
                break
        
        self.unusedSpriteGroups: List[PointerArray] = []
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
            desc.scripts = ScriptSet(tree, ACTOR_SCRIPT_TYPE_LOOKUP)

        cellScriptTree = scriptFileTree.children[len(self.descriptions)]
        self.scripts = ScriptSet(cellScriptTree, CELL_SCRIPT_TYPE_LOOKUP)

        cellVarArray = scriptFileTree.children[len(self.descriptions) + 1]
        if self.name != "gl6":
            self.vars = [s.take("H") for s in cellVarArray.children[0].elements]
            lastUsedIndex = len(self.descriptions) + 1
        else:
            self.vars = []
            lastUsedIndex = len(self.descriptions)
        
        self.extraScriptData: List[List[List[bytes]]] = []
        if self.name != "gl6":
            for i in range(lastUsedIndex + 1, len(scriptFileTree.children)):
                sublist: List[str] = []
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
            print("Actor", i)
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

    def export(self, root: str, parentGame: Game):
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
            json.dump(castJson, f, default=_cellSerializer)
        
        convertedPalette = ["#" + self.rawPalette[i:i+3].hex() for i in range(0, len(self.palette), 3)]
        cellJson = {
            "palette": convertedPalette,
            "DYUVInitialValues": self.backgroundInitialColors,
            "paletteCycles": None
        }
        if self.info.hasPaletteCycling:
            cellJson["paletteCycles"] = self.info.cyclers
        with open(folder + "cell.json", "w") as f:
            json.dump(cellJson, f, default=_cellSerializer)

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
    
    def _exportVoiceLines(self, folder: str, parentGame: Game):
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
            ret += "# Local variables\n"
            var: int
            for i, var in enumerate(self.vars):
                ret += "local{} = {} # {}, {}\n".format(i, var, hex(var), repr(var.to_bytes(2, "big")))
        else:
            ret += "# No local variables\n\n"

        if len(self.extraScriptData) > 0:
            ret += "# Extra script data\n"
            ret += "extraData = [\n"
            for sublist in self.extraScriptData:
                ret += "\t{},\n".format(sublist)
            ret += "]\n"
        
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
def putTargets(img: PIL.Image.Image, offset: Coords, points: List[Coords], color: int):
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