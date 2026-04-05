
import copy
from typing import Literal, Self

import PIL.Image

from .basic_types import Coords
from .scripts import AnimationCommand
from .struct_stream import StructStream


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

    def __init__(self, stream: StructStream):
        assert len(stream) == 20, len(stream)
        self.start, self.length, mode, self.delay = stream.take("HHHH")
        self.currentOffset, cycleDirection, enabled, self.timer = stream.take("HHHh")
        staggerMode, hasLooped = stream.take("HH")

        self.errors: list[str] = []

        self.start: int
        self.length: int
        self.delay: int
        self.currentOffset: int
        self.timer: int
        
        assert len(stream) == 0, stream

        self.mode: Literal["IncreaseOnly", "Oscillate"] | None
        if mode == 1:
            self.mode = "IncreaseOnly"
        elif mode == 2:
            self.mode = "Oscillate"
        else:
            self.errors.append("Unknown mode {}".format(mode))
            self.mode = None

        self.cycleDirection: Literal["Increasing", "Decreasing"] | None
        if cycleDirection == 1:
            self.cycleDirection = "Increasing"
        elif cycleDirection == 2:
            self.cycleDirection = "Decreasing"
        else:
            self.errors.append("Unknown direction {}".format(cycleDirection))
            self.cycleDirection = None

        self.staggerMode: Literal["None", "RandomAfterLooping"] | None
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
        
        table: list[int] = list(tableStream.take("{}H".format(tableSize), fillZeros=True))
        
        self.commands: list[str] = []
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
