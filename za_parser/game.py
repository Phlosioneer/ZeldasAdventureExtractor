
from dataclasses import dataclass
import json
import os
from typing import Any, Callable, Iterator

import PIL.Image
from tqdm import tqdm_notebook as tqdm

from .cdi_spec.audio import saveSoundFile
from .cdi_spec.filesystem import CdiFileSystem, loadCdiImageFile
from .constants import SPELL_LOOKUP, LootDropType
from .actor import Actor, ActorDescription, SpriteGroup
from .basic_types import ActorDescLocation
from .cell import Cell, cellSerializer
from .scripts import Attack
from .resource_tree import ResourceFileSystem, ResourceFileSystemFolder, ResourceTree
from .sprites import convertClutToRgba, decompressSprite, getClut, unpackPointerArray, unpackSpriteTree
from .struct_stream import StructStream

#################
# Stuff used for actor metadata images
RED = 6
BLUE = 7
GREEN = 8
BLACK = 9

class Game:
    ##############
    # Cells

    # Cells from `over.rtf`
    overworldCells: dict[str, Cell]
    # Cells from `under.rtf`
    underworldCells: dict[str, Cell]
    # Overworld cells that had errors while parsing
    errorOverworldCells: list[str]
    # Underworld cells that had errors while parsing
    errorUnderworldCells: list[str]

    ##############
    # Common Data
    #
    # This data is stored separately from all other cells, because it's used on every
    # screen. All of this data is parsed during __init__().

    # The actor entry for Zelda.
    zeldaActor: Actor
    # The actor description for loot (hearts, rupees (no I will not call them rubies))
    lootActorDesc: ActorDescription
    # Heart sprites, used for the health bar. I think this is also used for the heart
    # loot?
    heartSprites: list[PIL.Image.Image]
    rupeeCounterSprite: PIL.Image.Image
    # Weapon animation definitions (scripts, actors, sprites, etc) organized by weapon
    # name.
    weapons: dict[str, Attack]

    ##############
    # Aggregate Data
    #
    # Various fields that organize info from all the cells in the game for easier lookup.

    # A list of all actor descriptions across all cells, organized by name. Actors are
    # considered "the same" if they have identical sprites. Uses names that I came up with,
    # or that were provide by fans; name list can be edited in `spriteNames.json` file.
    spriteNames: dict[str, list[list[ActorDescLocation]]]

    # The reverse of the spriteNames list, for convenience.
    spriteNameReverseLookup: dict[ActorDescLocation, str]

    ##############
    # Internal data

    # The CDI disk's filesystem
    _gameData: CdiFileSystem
    
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

        self._gameData = loadCdiImageFile(dataFileName)
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
        self.weapons: dict[str, Attack] = {}
        bar = tqdm(total=len(weaponFiles))
        for i, filename in enumerate(weaponFiles):
            bar.desc = SPELL_LOOKUP[i]
            commonName = SPELL_LOOKUP[i]
            self.weapons[commonName] = self._parseZeldaWeapon(filename, i + 1)
            bar.update(1)
        bar.close()

    def _parseZeldaWeapon(self, filename: str, id: int) -> Attack:
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
        self.spriteNames: dict[str, list[list[ActorDescLocation]]] = {}
        self.spriteNameReverseLookup: dict[ActorDescLocation, str] = {}
        
        variants: list[dict]
        for name, variants in rawData.items():
            parsedVariants: list[list[ActorDescLocation]] = []
            variant: dict
            for variant in variants:
                locations: list[dict] = variant["locations"]
                parsedLocations: list[ActorDescLocation] = []
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

    def cellNames(self, duplicates: bool = False) -> Iterator[tuple[str, bool]]:
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

    def cells(self, duplicates: bool = True, useTqdm: bool = True) -> Iterator[Cell]:
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

    def exportJustScripts(self, scriptPath: str, libraryScriptFolder: str | None):
        """
        Exports all the cell scripts into a separate directory. Useful for
        e.g. looking up every script for a particular shrine.

        The `path` argument MAY end in `/` but this is not required.

        If the `libraryScriptFolder` path is provided, then all the python files
        in that folder will be copied to the export's `scripts` folder.
        """

        # Correct the path if needed
        if scriptPath[-1] != "/":
            scriptPath += "/"
        if libraryScriptFolder and libraryScriptFolder[-1] != "/":
            libraryScriptFolder += "/"
        bar = tqdm(total=len(self._overFiles.subFiles) + len(self._underFiles.subFiles))
        
        def exportWorld(folder: str, names: list[str], isOverworld: bool):
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
            exportWorld(scriptPath + "overworld", self._overFiles.subFiles.keys(), True)
            exportWorld(scriptPath + "underworld", self._underFiles.subFiles.keys(), False)
        finally:
            bar.close()
        
        if libraryScriptFolder:
            files = os.listdir(libraryScriptFolder)
            for file in files:
                if file.endswith(".py"):
                    with open(libraryScriptFolder + file, "r") as f:
                        text = f.read()
                    with open(scriptPath + file, "w") as f:
                        f.write(text)

    def getCell(self, name: str, isOverworld: bool | None = None, silenceWarning: bool = False) -> Cell:
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
    
    def _parseCell(self, file: ResourceFileSystemFolder, name: str, isOverworld: bool) -> Cell:
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
    
    def getSpritesByName(self, name: str, variant: int = 0) -> SpriteGroup:
        """
        Get the sprite group for a given NPC name. Uses the first location in
        the locations list to fetch the sprite group.

        The variant defaults to 0 (the first variant).
        """
        location = self._getActorVariantLocationsByName(name, variant)[0]
        desc = self._getActorByLocation(location)
        return desc.groups
    
    def getActorsByName(self, name: str, variant: int = 0) -> list[ActorDescription]:
        """
        Get all actor descriptions for a given NPC name, across all cells in
        the game.

        The variant defaults to 0 (the first variant).
        """
        locations = self._getActorVariantLocationsByName(name, variant)
        return [self._getActorByLocation(l) for l in locations]

    def _getActorByLocation(self, location: ActorDescLocation) -> ActorDescription:
        """
        Find the actor description that corresponds to a particular location entry
        in spriteNames.json.
        """
        cell = self.getCell(location.cell, location.isOverworld)
        return cell.descriptions[location.index]
    
    def getAllActorVariantsByName(self, name: str) -> list[list[ActorDescription]]:
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

    def _getActorVariantLocationsByName(self, name: str, variant: int) -> list[ActorDescription]:
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
        cellsInVoiceOrder: list[str] = list(map(
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

    def export(self, root: str, templateFolder: str | None, libraryScriptFolder: str | None):
        """
        Exports all of the game's data into the directory path `root`. The `root`
        path MAY end in `/`, it is not required.

        `templateFolder` is the path to markdown headers for curiosities.
        """
        self.assignVoiceLines()
        if root[-1] != "/":
            root += "/"
        
        if templateFolder and templateFolder[-1] != "/":
            templateFolder += "/"
        
        if libraryScriptFolder and libraryScriptFolder[-1] != "/":
            libraryScriptFolder += "/"

        self._exportCommonData(root + "common")
        
        overworldFolder = root + "overworld"
        underworldFolder = root + "underworld"
        for cell in self.cells(duplicates=True):
            if cell.info.isOverworld:
                cell.export(overworldFolder, self)
            else:
                cell.export(underworldFolder, self)
        print("Exporting curiosities")
        self._exportCuriosities(root + "curiosities", templateFolder)
        print("Exporting copy of scripts to separate dir")
        self.exportJustScripts(root + "scripts", libraryScriptFolder)
    
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
            json.dump(castJson, f, default=cellSerializer, indent=2)

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

    def _exportCuriosities(self, curiositiesRoot: str, templateFolder: str | None):
        """
        Exports some useful or neat stats from the huge amount of exported data.
        """
        if curiositiesRoot.endswith("/"):
            curiositiesRoot = curiositiesRoot[:-1]
        os.makedirs(curiositiesRoot, exist_ok=True)
        
        self._exportCurioProjectileField(curiositiesRoot, templateFolder)
        self._exportCurioWeaknesses(curiositiesRoot)
        self._exportCurioEnemyStats(curiositiesRoot)
    
    def _exportCurioProjectileField(self, curiositiesRoot: str, templateFolder: str | None):
        if templateFolder:
            with open(templateFolder + "Actor Desc Projectile Field.md", "r") as f:
                template = f.read()
        else:
            template = "{data}"
        
        values = self._gatherValuesForDescFieldByEntityName(lambda desc: str(desc.canUseProjectiles))
        dataText = self._renderValuesByEntityName(values)
        
        with open(curiositiesRoot + "/Actor Desc Projectile Field.md", "w") as f:
            f.write(template.replace("{data}", dataText.strip(), 1))

    def _gatherValuesForDescFieldByEntityName(self, fieldGetter: Callable[[ActorDescription], Any]) -> dict[str, dict[Any, list[str]]]:
        """
        Gathers machine-readable info on the possible values that an actor description field can take.
        """
        valuesPerEntity = {}
        for cell in self.cells(duplicates=True):
            for desc in cell.descriptions:
                if desc.commonName not in valuesPerEntity:
                    valuesPerEntity[desc.commonName] = {}
                value = fieldGetter(desc)
                if value not in valuesPerEntity[desc.commonName]:
                    valuesPerEntity[desc.commonName][value] = []
                if cell.name not in valuesPerEntity[desc.commonName][value]:
                    valuesPerEntity[desc.commonName][value].append(cell.name)
        
        return valuesPerEntity

    def _renderValuesByEntityName(self, valuesPerEntity: dict[str, dict[Any, list[str]]]):
        text = ""
        for name in sorted(valuesPerEntity):
            values = valuesPerEntity[name]
            if len(values) == 1:
                text += f"{name} always has value {list(values.keys())[0], list(values.values())[0]}\n"
            else:
                text += f"{name} has different values on different cells:\n"
                for value, cellNames in values.items():
                    cellNameList = ", ".join(cellNames)
                    cellsWord = "cells" if len(cellNames) > 1 else "cell"
                    text += f"\t{value} on {cellsWord} {cellNameList}\n"
        return text
    
    def _exportCurioWeaknesses(self, curiositiesRoot):
        """
        Exports a human-readable text file listing all the weaknesses for enemies.
        """
        with open(curiositiesRoot + "/weaknesses.txt", "w") as f:
            for cell in self.cells():
                for desc in cell.descriptions:
                    if desc.weakToSpell != "None" and desc.bonusDamage != 0:
                        message = "On {} {} is weak to {} and it deals this much bonus damage: {}\n".format(cell.name, desc.commonName, desc.weakToSpell, desc.bonusDamage)
                        f.write(message)
        
    def _exportCurioEnemyStats(self, curiositiesRoot):
        """
        Exports a human-readable text file listing all the combat stats for enemies.
        """

        @dataclass(eq=True, frozen=True)
        class StatBlock:
            health: int | None
            damage: int
            defense: int
            weakness: str
            bonusDamage: int
            loot: LootDropType

            def __repr__(self):
                notableStats = []
                notableStats.append("damage={}".format(self.damage))
                if self.defense != 0:
                    notableStats.append("defense={}".format(self.defense))
                if self.health == None:
                    notableStats.append("health=(Not Spawned, or Projectile)")
                else:
                    notableStats.append("health={}".format(self.defense))
                if self.weakness != "None" or self.bonusDamage != 0:
                    notableStats.append("weakness={}".format(self.weakness))
                    notableStats.append("bonusDamage={}".format(self.bonusDamage))
                if self.loot != LootDropType.NOTHING:
                    notableStats.append("loot={}".format(self.loot))
                return "[{}]".format(", ".join(notableStats))

        stats = {}

        for cell in self.cells():
            for actor in cell.actors:
                name = actor.description.commonName
                if name not in stats:
                    stats[name] = {}

                hasWeakness = actor.description.weakToSpell != "None"
                statBlock = StatBlock(
                    health=actor.health,
                    damage=actor.description.baseDamageOrPurchasePrice_maybe,
                    defense=actor.description.useCostOrDefense,
                    weakness=actor.description.weakToSpell,
                    bonusDamage=actor.description.bonusDamage,
                    loot=actor.description.lootDropped
                )

                if statBlock not in stats[name]:
                    stats[name][statBlock] = []
                if cell.name not in stats[name][statBlock]:
                    stats[name][statBlock].append(cell.name)

            for desc in cell.descriptions:
                isUsed = False
                for actor in cell.actors:
                    if actor.description == desc:
                        isUsed = True
                        break
                if isUsed:
                    continue
                
                if desc.commonName not in stats:
                    stats[desc.commonName] = {}

                statBlock = StatBlock(
                    health=None,
                    damage=desc.baseDamageOrPurchasePrice_maybe,
                    defense=desc.useCostOrDefense,
                    weakness=desc.weakToSpell,
                    bonusDamage=desc.bonusDamage,
                    loot=desc.lootDropped
                )
                if statBlock not in stats[desc.commonName]:
                    stats[desc.commonName][statBlock] = []
                if cell.name not in stats[desc.commonName][statBlock]:
                    stats[desc.commonName][statBlock].append(cell.name)

        with open(curiositiesRoot + "/enemyStats.txt", "w") as f:
            for name in sorted(stats):
                #if name.startswith("enemy.") or "projectile" in name:
                if len(stats[name]) == 1:
                    f.write("{} always has the stats:\n".format(name))
                    f.write("\t{} on cells {}\n".format(
                        list(stats[name].keys())[0],
                        ", ".join(list(stats[name].values())[0])
                        ))
                else:
                    f.write("{} has different stats on different cells:\n".format(name))
                    for statBlock, cells in stats[name].items():
                        f.write("\t{} on cells {}\n".format(statBlock, ', '.join(cells)))
