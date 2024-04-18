
from typing import Self, Dict, List, Literal, TYPE_CHECKING, Optional, Union

from struct_stream import StructStream
if TYPE_CHECKING:
    from cdi_filesystem import CdiFile, CdiSector

#######################
# Resource Tree Format

class ResourceTree:
    """
    The base class for all resource tree nodes. This class also has the recommended
    method of parsing a resource tree, `parseFromStream`.

    This is TECHNICALLY not an abstract class! It can be constructed and returned
    by `parseFromStream` for unknown `tag` values.
    """

    # The tag indicates which type of resource tree node this is.
    tag: Union[0, 1, 2]
    # The size, in bytes, of all data that is part of THIS node (not child
    # nodes). The definition is weird and flexible because it's not actually
    # used for anything.
    #
    # Note that `size` is sometimes very weird for ResourceTreeSet nodes in
    # particular.
    size: int

    def __init__(self, stream: StructStream):
        self.tag, self.size = stream.take("II")
    
    # Static
    def parseFromStream(stream: StructStream) \
        -> Union["ResourceTreeNode", "ResourceTreeArray", "ResourceTreeSet", Self]:
        """
        Parse a resource tree from data. This method takes care of parsing the `tag`
        to figure out which ResourceTree subclass to create.

        If the tag is not recognized, it returns the base class.
        """
        
        tag = stream.peek("I")
        if tag == 0:
            return ResourceTreeNode(stream)
        elif tag == 1:
            return ResourceTreeArray(stream)
        elif tag == 2:
            return ResourceTreeSet(stream)
        else:
            print("Unknown tag type:", tag)
            return ResourceTree(stream)
    
    def simplify(self) -> Union[dict, list]:
        """
        Convert this node and all its children into json-serializable types.
        """

        # Abstract method
        raise NotImplementedError()

class ResourceTreeNode(ResourceTree):
    """
    The Tree part of the Resource Tree. It's named poorly.

    The node's children use either names or numbers for access. Children
    are usually stored immediately after the node in memory, but this
    is not required. Note that 

    Internally, this node has two "immediate" children: an optional Set node
    containing ascii names, and a mandatory Set node with the actual
    children nodes. While Set nodes generally contain arbitrary bytes,
    the children Set node will always contain ResourceTree objects. This
    is an implementation detail and these "immedate" children are hidden.

    The children are ALWAYS ResourceTree nodes, a limitation that leads
    to raw data being stored as arrays with a size of 1.
    """

    # If true, `children` uses `str` keys. If false, it uses number keys.
    hasNames: bool
    # The children of this node in the tree. Keys are either all numbers, or
    # all strings. They're almost alway strings.
    children: Union[Dict[int, ResourceTree], Dict[str, ResourceTree]]

    def __init__(self, stream: StructStream):
        originalStream = stream.copy()
        ResourceTree.__init__(self, stream)
        assert self.tag == 0, self.tag
        
        originalStream = originalStream.takeFork(self.size)
        
        # The two main parts of the node are the list of names and the list of
        # children data streams. childCount CAN be used for parsing these lists,
        # but the name list is a full ResourceTreeSet with its own length value,
        # so it wasn't necessary.
        childCount, nameListNodeOffset, childListNodeOffset = stream.take("III")
        #print("root", childCount, nameListNodeOffset, childListNodeOffset)
        
        nameListStream = originalStream.copy().skip(nameListNodeOffset)
        childListStream = originalStream.copy().skip(childListNodeOffset)
        
        # I honestly don't know if this is necessary anymore. It used to be
        # important for the `stream` to be correctly sized (to find hidden/
        # unused data) but I don't think stream length is used for anything now.
        if nameListNodeOffset < childListNodeOffset:
            nameListStream = nameListStream.takeFork(childListNodeOffset - nameListNodeOffset)
        else:
            childListStream = childListStream.takeFork(nameListNodeOffset - childListNodeOffset)
        
        # Parse the child list first, since it's always present.
        childListNode = ResourceTreeSet(childListStream)

        # Parse all of the children recursively.
        children = [ResourceTree.parseFromStream(s) for s in childListNode.elements]
        
        # Check if there is a name list.
        if nameListNodeOffset == 0:
            # No, use numbers.
            names = list(range(len(children)))
            self.hasNames = False
        else:
            # Yes, parse the list then decode the data as null-terminated ascii strings.
            nameListNode = ResourceTreeSet(nameListStream)
            names = [s.copy().takeNullTermString().decode('ascii') for s in nameListNode.elements]
            self.hasNames = True
        
        # Combine the name list and child list into a single dict. Could probably do
        # something fancy with `zip()` and iterators. Whatever.
        self.children: Dict[str, ResourceTree] = {}
        for i in range(len(names)):
            self.children[names[i]] = children[i]
    
    def simplify(self) -> dict:
        ret = {}
        for name, child in self.children.items():
            ret[name] = child.simplify()
        return ret

class ResourceTreeSet(ResourceTree):
    """
    A Set node contains a list of data elements with varying sizes.

    A set node has an array of pointers to the actual data in the set.
    The size of the data is unspecified, though in Zelda's Adventure it
    is always contiguous and densely-packed, so size can be inferred
    from pointer math.

    The `size` field of the resource tree set behaves strangely, and
    doesn't seem to correspond to the actual size of the data. Unlike
    other ResourceTree objects, there are some Sets with data that is
    not contiguous with the object definition.
    """

    # Offset to the start of the array-of-offsets to element data.
    listOffset: int
    # Offset to the start of element data.
    baseOffset: int
    # Child elements as raw data.
    elements: List[StructStream]

    def __init__(self, stream: StructStream):
        originalStream = stream.copy()
        ResourceTree.__init__(self, stream)
        assert self.tag == 2, self.tag
        
        # For set nodes, the "size" field seems to be broken?
        #originalStream = originalStream.takeFork(self.size)
        
        count, self.baseOffset, self.listOffset = stream.take("III")
        #print("ResourceTreeSet(count={}, base={}, list={})".format(count, self.baseOffset, self.listOffset))
        baseData = originalStream.copy().skip(self.baseOffset)
        listData = originalStream.copy().skip(self.listOffset)
        if count > 1:
            elementOffsets: List[int] = list(baseData.copy().take("{}I".format(count)))
        elif count == 1:
            elementOffsets = [baseData.copy().take("I")]
        else:
            elementOffsets = []
        
        self.elements: List[StructStream] = []
        for i, currentOffset in enumerate(elementOffsets):
            elementStart = listData.copy().skip(currentOffset)
            if i < len(elementOffsets) - 1:
                nextOffset = elementOffsets[i + 1]
                elementLength = nextOffset - currentOffset
                #print("Next element offset", nextOffset)
                self.elements.append(elementStart.takeFork(elementLength))
            elif self.listOffset < self.baseOffset:
                nextOffset = self.baseOffset - self.listOffset
                elementLength = nextOffset - currentOffset
                #print("baseOffset", self.baseOffset, "is after listOffset", self.listOffset, "final offset", nextOffset)
                self.elements.append(elementStart.takeFork(elementLength))
            else:
                #print("Next offset is unknown. Using rest of buffer", len(listData) - currentOffset)
                self.elements.append(elementStart)
        

        #if len(baseData) + 20 != self.size:
        #    print("ResourceTreeSet(count={}, base={}, list={})".format(count, self.baseOffset, self.listOffset))
        #    print("Mismatched set node size; expected", len(baseData) + 20, "found", self.size)

    def simplify(self) -> list:
        return self.elements

class ResourceTreeArray(ResourceTree):
    """
    An Array node contains a list of data with fixed sizes.

    This node is also frequently used to store large, non-repeating data
    blobs. They are encoded as "arrays" of 1 element of some very large
    size.

    Although not required, the data always immediately follows the
    object definition.
    """
    elementCount: int
    elementSize: int
    elements: List[StructStream]

    def __init__(self, stream: StructStream):
        originalStream = stream.copy()
        ResourceTree.__init__(self, stream)
        assert self.tag == 1, self.tag
        
        originalStream = originalStream.takeFork(self.size)
        
        self.elementCount, self.elementSize, offset = stream.take("III")
        elementData = originalStream.takeFork(self.size).skip(offset)
        self.elements: List[StructStream] = [elementData.takeFork(self.elementSize) for _ in range(self.elementCount)]

    def simplify(self) -> list:
        return self.elements

#######################
# Filesystem built on top of Resource Tree Format

class ResourceMap:
    realFile: "CdiFile"
    subFiles: Dict[str, "ResourceMapFileEntry"]
    sortedFiles: List[str]

    def __init__(self, stream: StructStream, realFile: "CdiFile"):
        self.realFile = realFile
        
        root = ResourceTree.parseFromStream(stream).simplify()
        
        #assert "l" in root, root
        assert "r" in root, root
        if "l" in root:
            subFileNames: List[str] = [s.peekNullTermString().decode('ascii') for s in root["l"]]
        else:
            subFileNames = list(range(len(root["r"])))
        self.subFiles: Dict[str, ResourceMapFileEntry] = {}
        
        for i, name in enumerate(subFileNames):
            self.subFiles[name] = ResourceMapFileEntry(name, root["r"][i])
        
        subFileNames.sort(key=lambda f: self.subFiles[f].blockOffset)
        self.sortedFiles = [self.subFiles[name] for name in subFileNames]
        del subFileNames
        
        for i in range(len(self.sortedFiles) - 1):
            subFile = self.sortedFiles[i]
            nextSubFile = self.sortedFiles[i + 1]
            subFile.nextFile = nextSubFile
            endBlock = nextSubFile.blockOffset
            subFile.sectors = realFile.sectors[subFile.blockOffset:endBlock]
            #print(subFile.name, "start", subFile.blockOffset, "end", endBlock, "length", len(subFile.sectors))
        lastSubFile = self.sortedFiles[-1]
        lastSubFile.sectors = realFile.sectors[lastSubFile.blockOffset:]
        #print(lastSubFile.name, "start", lastSubFile.blockOffset, "length", len(lastSubFile.sectors))
        
        def handleSizeArray(name: str):
            if name not in root:
                return
            
            # Array of bytes
            sizes = list(root[name][0].takeAll())
            #print("array", name, "sizes", sizes)
            
            for i in range(len(self.sortedFiles)):
                f = self.sortedFiles[i]
                thisIndex = f._getSizeIndex(name)
                if thisIndex == 0xFFFF:
                    return
                
                if i == len(self.sortedFiles) - 1:
                    nextIndex = len(sizes)
                else:
                    nextF = self.sortedFiles[i + 1]
                    nextIndex = nextF._getSizeIndex(name)
                    if nextIndex == 0xFFFF:
                        nextIndex = len(sizes)
                
                f._setSizes(name, sizes[thisIndex:nextIndex])
        
        handleSizeArray("v")
        handleSizeArray("a")
        handleSizeArray("d")

        #print(self.getFileSummary())
        
    def getFileSummary(self) -> str:
        ret = ""
        for f in self.sortedFiles:
            ret += "{} {} {} {}".format(f.name, f.videoSizes, f.audioSizes, f.dataSizes)
        return ret
        
    
class ResourceMapFileEntry:
    name: str
    channel: int
    blockOffset: int
    sectors: List["CdiSector"]
    nextFile: Optional[Self]
    videoRecords: List[int]
    audioRecords: List[int]
    dataRecords: List[int]
    _cachedRecordData: Dict[str, Dict[int, bytes]]
    
    def __init__(self, name: str, stream: StructStream):
        self.name = name
        self.channel, self.blockOffset = stream.take("HI")
        self.sectors: List["CdiSector"] = []
        self.nextFile: Optional[Self] = None
        self.videoRecords = []
        self.audioRecords = []
        self.dataRecords = []
        self._cachedRecordData: Dict[str, Dict[int, bytes]] = {}
        if len(stream) == 6:
            # There are still 6 bytes left.
            
            self.videoSizesIndex, self.audioSizesIndex, self.dataSizesIndex = stream.take("HHH")
            self.videoSizes: List[int] = []
            self.audioSizes: List[int] = []
            self.dataSizes: List[int] = []
        else:
            print("6-byte file descriptors found:", len(stream))
    
    def getBytes(self, start = 0, end = None, kind = None):
        if end == None:
            end = len(self.sectors)
        filtered = [s for s in self.sectors if kind == None or kind == s.kind]
        return b''.join([s.data for s in filtered[start:end]])
    
    def getRecord(self, index: int, kind: Literal["video","audio","data"]):
        assert kind in ["video", "audio", "data"]
        if kind not in self._cachedRecordData:
            self._cachedRecordData[kind] = {}
        if index not in self._cachedRecordData[kind]:
            sizes = self._getSizes(kind[0])
            start = sum(sizes[:index])
            size = sizes[index]
            data = self.getBytes(start, start + size, kind = kind)
            self._cachedRecordData[kind][index] = data
        return self._cachedRecordData[kind][index]
    
    def _getSizeIndex(self, name: Literal["v", "a", "d"]) -> int:
        if name == "v":
            return self.videoSizesIndex
        elif name == "a":
            return self.audioSizesIndex
        else:
            assert name == "d"
            return self.dataSizesIndex
    
    def _setSizes(self, name: Literal["v", "a", "d"], sizes: List[int]):
        if name == "v":
            self.videoSizes = sizes
        elif name == "a":
            self.audioSizes = sizes
        else:
            assert name == "d"
            self.dataSizes = sizes
    
    def _getSizes(self, name: Literal["v", "a", "d"]) -> List[int]:
        if name == "v":
            return self.videoSizes
        if name == "a":
            return self.audioSizes
        assert name == "d"
        return self.dataSizes

