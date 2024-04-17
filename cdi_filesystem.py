import json
import datetime
import math
import struct
from typing import Dict, Literal, List, Optional

from tqdm import tqdm_notebook as tqdm
from struct_stream import StructStream

class CdiSector:
	def __init__(self, metadata: dict, rawData: bytes):
		self.minute: int = metadata["minute"]
		self.second: int = metadata["second"]
		self.frame: int = metadata["frame"]
		if metadata["mode"] == "MODE1":
			self.mode = 1
		else:
			assert metadata["mode"] == "MODE2"
			self.mode = 2
		
		if self.mode == 2:
			assert rawData[:4] == rawData[4:8]
			self.file = rawData[0]
			self.channel = rawData[1]
			submode = rawData[2]
			self.coding = rawData[3]
			
			self.isEof = submode & 0x80 != 0
			self.isRealtime = submode & 0x40 != 0
			self.form = ((submode & 0x20) >> 5) + 1
			self.isTrigger = submode & 0x10 != 0
			self.kind: Literal["empty", "data", "audio", "video"] = 'empty'
			if submode & 0x08 != 0:
				self.kind = "data"
			if submode & 0x04 != 0:
				assert self.kind == 'empty'
				self.kind = "audio"
			if submode & 0x02 != 0:
				assert self.kind == 'empty'
				self.kind = "video"
			self.isEndOfRecord = submode & 0x01 != 0
			
			if self.form == 1:
				self.data = rawData[8:8 + 2048]
			else:
				self.data = rawData[8:8 + 2324]
		else:
			self.file = None
			self.channel = None
			self.coding = None
			self.isEof = None
			self.isRealtime = None
			self.form = None
			self.isTrigger = None
			self.kind = None
			self.isEndOfRecord = None
			self.data = rawData
	
	def __repr__(self) -> str:
		ret = "CdiSector(({}m, {}s, {}f), ".format(self.minute, self.second, self.frame)
		if self.mode == 1:
			return ret + "mode 1)"
		ret += "mode 2, form {}, {}".format(self.form, self.kind)
		if self.kind != "empty":
			ret += ", file {}, channel {}, coding {}".format(self.file, self.channel, self.coding)
			if self.isEof:
				ret += ", File End"
			if self.isEndOfRecord:
				ret += ", Record End"
			if self.isTrigger:
				ret += ", Trigger"
		return ret + ")"

class CdiVolumeDescriptor:
	def __init__(self, sector: CdiSector):
		assert sector.mode == 2
		assert sector.form == 1
		assert sector.isEndOfRecord
		
		s = StructStream(sector.data, endianPrefix=">")
		assert s.takeRaw(1)[0] == 1 # Record Type = Standard Volume Structure
		assert s.takeRaw(5) == b'CD-I ' # Standard Id
		assert s.takeRaw(1)[0] == 1 # Version = 1
		assert s.takeRaw(1)[0] == 0 # Character set identifier flag
		assert s.takeRaw(32) == b'CD-RTOS' + b' ' * (32 - 7) # System Identifier
		self.volumeName: str = s.takeRaw(32).decode('ascii').strip()
		self.size: int = s.skip(12).take("I")
		self.charSet: bytes = list(s.takeRaw(32))
		self.volumesInAlbum: int = s.skip(2).take("H")
		self.volumeSeqNumber: int = s.skip(2).take("H")
		self.blockSize: int = s.skip(2).take("H")
		self.pathTableSize: int = s.skip(4).take("I")
		self.pathTableAddress: int = s.skip(8).take("I")
		self.album = s.skip(38).takeRaw(128).decode("ascii").strip()
		self.publisher = s.takeRaw(128).decode("ascii").strip()
		self.dataPrepPerson = s.takeRaw(128).decode("ascii").strip()
		self.applicationFileName = s.takeRaw(128).decode("ascii").strip()
		self.copyrightFileName = s.takeRaw(32).decode("ascii").strip()
		self.abstractFileName = s.skip(5).takeRaw(32).decode("ascii").strip()
		self.biblioFileName = s.skip(5).takeRaw(32).decode("ascii").strip()
		self.creationDateRaw = s.skip(5).takeRaw(16)
		self.modificationDateRaw = s.skip(1).takeRaw(16)
		self.expirationDateRaw = s.skip(1).takeRaw(16)
		self.effectiveDateRaw = s.skip(1).takeRaw(16)
		assert s.skip(1).takeRaw(1)[0] == 1 # File Structure Version = 1
		self.appData = s.skip(1).takeRaw(512)

class CdiDirectory:
	def __init__(self, sector: CdiSector):
		s = StructStream(sector.data, endianPrefix=">")
		
		# The first file entry is self-describing.
		self.thisDescriptor = CdiFile(s)
		
		# The next file entry is the parent dir.
		self.parentDescriptor = CdiFile(s)
		
		# We continue reading until we've read bytes equal to the size of the directory.
		self.fileDescriptors: List[CdiFile] = []
		while s._cursor < self.thisDescriptor.size:
			file = CdiFile(s)
			
			# I'm not going to support nested directories yet.
			assert "Directory" not in file.attributes
			
			self.fileDescriptors.append(file)

class CdiFile:
	def __init__(self, stream: StructStream):
		s = stream
		mark = len(s)
		
		self._cachedBytes: Optional[bytes] = None
		
		recordLength: int = s.take("B")
		self.exAttribs: int = s.take("B")
		self.startBlock: int = s.skip(4).take("I")
		self.size: int = s.skip(4).take("I")
		creationDateRaw: List[int] = list(s.take("6B"))
		self.creationDate = datetime.datetime(
			creationDateRaw[0] + 1900,
			creationDateRaw[1],
			creationDateRaw[2],
			hour=creationDateRaw[3],
			minute=creationDateRaw[4],
			second=creationDateRaw[5]
		)
		flags: int = s.skip(1).take("B")
		self.isHidden = flags & 1 != 0
		self.interleaveRatio: List[int] = list(s.take("BB"))
		self.sequenceNumber: int = s.skip(2).take("H")
		nameLength: int = s.take("B")
		rawName = s.takeRaw(nameLength)
		if rawName == b'\x00':
			self.name = "<PhloNickname:ROOT>"
		else:
			self.name = rawName.decode("ascii")
		
		# If the name length is even, skip a byte. This aligns the owner ID to a word
		# boundry, which was useful because it is two words.
		if nameLength % 2 == 0:
			s.skip(1)
		
		ownerGroup, ownerUser = s.take("HH")
		self.owner = {"group": ownerGroup, "user": ownerUser}
		attributeFlags: int = s.take("H")
		self.fileNumber: int = s.skip(2).take("B")
		s.skip(1)
		
		self.attributes: List[Literal[
			"Owner Read", "Owner Execute", "Group Read",
			"Group Execute", "World Read", "World Execute",
			"CD-DA file", "Directory"
				]] = []
		if attributeFlags & 0x0001 != 0:
			self.attributes.append("Owner Read")
		if attributeFlags & 0x0004 != 0:
			self.attributes.append("Owner Execute")
		if attributeFlags & 0x0010 != 0:
			self.attributes.append("Group Read")
		if attributeFlags & 0x0040 != 0:
			self.attributes.append("Group Execute")
		if attributeFlags & 0x0100 != 0:
			self.attributes.append("World Read")
		if attributeFlags & 0x0400 != 0:
			self.attributes.append("World Execute")
		if attributeFlags & 0x4000 != 0:
			self.attributes.append("CD-DA file")
		if attributeFlags & 0x8000 != 0:
			self.attributes.append("Directory")
			
		self.sectors: List[CdiSector] = []
		self.blocks: List[bytes] = []
		self.modules: Optional[List[dict]] = None
		self.unusedBytes: Optional[bytes] = None
		
		# For now, I'm not supporting interleaving.
		assert self.interleaveRatio == [0, 0], "Interleave not supported yet"
		
		# Not supporting extra attributes.
		assert self.exAttribs == 0
		
		assert mark - len(s) == recordLength, (len(s), mark, recordLength, self.__dict__)
	
	def getBytes(self) -> bytes:
		if self._cachedBytes == None:
			self._cachedBytes = b''.join(self.blocks)
		return self._cachedBytes
		

class CdiFileSystem:
	def __init__(self, fileBytes: bytes):
		
		self._parseSectors(fileBytes)
		
		# Figure out where the CDH starts. It can chop off the first two seconds, or it can start immediately, or
		# anywhere in between.
		firstSector = self.sectors[0]
		self._firstIndex = CdiFileSystem.absoluteTimeToIndex(firstSector.minute, firstSector.second, firstSector.frame)
		
		# Disk label starts at 2s 16f and continues until a termination record.
		diskLabelSectors: List[CdiSector] = []
		i = self.getSectorIndex(0, 2, 16)
		currentSector = self.sectors[i]
		while not currentSector.isEof:
			diskLabelSectors.append(currentSector)
			i += 1
			currentSector = self.sectors[i]
		
		# For now, only support single-volume, default-character-set CD-I disks.
		assert len(diskLabelSectors) == 1
		self.volume = CdiVolumeDescriptor(diskLabelSectors[0])
		
		# Now read the path table. Its index is given in the volume descriptor.
		# TODO: I don't understand why this is off by 1.
		rootDirSector = self.sectors[self.volume.pathTableAddress + 1]
		self.rootDir = CdiDirectory(rootDirSector)
	
		self.files: Dict[str, CdiFile] = {}
		file: CdiFile
		for file in tqdm(self.rootDir.fileDescriptors, desc="building files"):
			self.files[file.name] = file
			file.sectors = self.sectors[file.startBlock:file.startBlock + math.ceil(file.size / self.volume.blockSize)]
			file.blocks = [s.data for s in file.sectors]
			if file.size % self.volume.blockSize != 0:
				file.blocks[-1] = file.blocks[-1][:file.size % self.volume.blockSize]
		
		self._identifyModules()
		
	def absoluteTimeToIndex(minute: int, second: int, frame: int) -> int:
		return (minute * 60 + second) * 75 + frame
	
	def getSectorIndex(self, minute: int, second: int, frame: int) -> int:
		return CdiFileSystem.absoluteTimeToIndex(minute, second, frame) - self._firstIndex
	
	def getSector(self, minute: int, second: int, frame: int) -> CdiSector:
		return self.sectors[self.getSectorIndex(minute, second, frame)]
	
	def _parseSectors(self, fileBytes: bytes):
		"""
		Parses a disk file. This is a custom format I created.
		The first 16 bytes are a header:
			[0:8] rawDataOffset (offset is relative to start of file)
			[8:16] jsonStringLength
		The header is followed by jsonStringLength bytes of packed JSON.
		Then the rest of the file, from rawDataOffset on, is a binary blob that is referenced by the JSON.
		
		Each sector in the json "sectors" array has a data offset and a data length, which refer to the
		binary blob.
		
		`file` is a `bytes` object.
		"""
		offset, strlen = struct.unpack("QQ", fileBytes[:16])
		blob = fileBytes[offset:]
		with tqdm(total = 1, desc = "parsing file") as t:
			metadata = json.loads(fileBytes[16:16 + strlen].decode('utf-8'))
			t.update(1)
		
		# Parse all the sectors.
		self.sectors: List[CdiSector] = []
		for sector in tqdm(metadata["sectors"], desc = "building sectors"):
			rawData = blob[sector["dataOffset"]:sector["dataOffset"] + sector["dataLength"]]
			self.sectors.append(CdiSector(sector, rawData))
	
	def _identifyModules(self):
		self.modules = {}
		
		duplicateNames: List[str] = []
		
		for f in tqdm(self.files, desc = "searching files for modules"):
			if not f[:4] == "cdi_":
				continue
			blocks = self.files[f].blocks
			assert blocks[0][:2] == b'\x4A\xFC', blocks[0][:2]
			
			with tqdm(total = len(blocks), desc = "searching " + f + " for modules") as t:
				currentBlockIndex = 0
				currentOffset = 0
				#print("There are", len(blocks), "blocks")
				while currentBlockIndex < len(blocks):
					#print("block", currentBlockIndex, "offset", currentOffset)
					currentBlock = blocks[currentBlockIndex]
					
					# Look for the next sync bytes
					foundModule = currentBlock[currentOffset:currentOffset + 2] == b'\x4A\xFC'
					
					# If no sync bytes, stop searching
					if not foundModule:
						unusedBytes = [currentBlock[currentOffset:]]
						total = len(unusedBytes[-1])
						currentBlockIndex += 1
						t.update(1)
						while currentBlockIndex < len(blocks):
							unusedBytes.append(blocks[currentBlockIndex])
							total += len(unusedBytes[-1])
							currentBlockIndex += 1
							t.update(1)
						#print("Unused byte count:", total)
						self.files[f].unusedBytes = unusedBytes
						break
					
					# Make sure the whole header is in the same byte string
					if currentBlockIndex + 1 < len(blocks):
						dualBlock = currentBlock + blocks[currentBlockIndex + 1]
					
					# +4 is file size
					moduleSize = struct.unpack(">I", dualBlock[currentOffset + 4:currentOffset + 8])[0]
					#print("size:", hex(moduleSize))
					
					# +12 is name pointer
					moduleNamePointer = struct.unpack(">I", dualBlock[currentOffset + 12:currentOffset + 16])[0]
					if moduleNamePointer >= moduleSize:
						break
					
					# Gather module bytes
					currentModule = []
					currentBlock = currentBlock[currentOffset:]
					while len(currentBlock) < moduleSize and currentBlockIndex < len(blocks):
						currentModule.append(currentBlock)
						moduleSize -= len(currentBlock)
						currentOffset = 0
						currentBlockIndex += 1
						t.update(1)
						if currentBlockIndex < len(blocks):
							currentBlock = blocks[currentBlockIndex]
						else:
							raise Exception("Ran out of blocks to add: " + str(currentBlockIndex))
					
					currentOffset += moduleSize
					currentModule.append(currentBlock[:currentOffset])
					#print("Module is", len(currentModule), "blocks")
					#print("Name pointer is", moduleNamePointer)
					
					
					# Get the module name string
					name = None
					takeNameFromStartOfBlock = False
					for i, block in enumerate(currentModule):
						#print("Searching block", i, "for name")
						#print("Block length", len(block), "name ptr", moduleNamePointer)
						if name == None:
							if len(block) > moduleNamePointer:
								#print("Name starts within this block")
								nameEnd = block.index(0, moduleNamePointer)
								if nameEnd < 0:
									#print("Name crosses block boundary")
									name = block[moduleNamePointer:]
									moduleNamePointer -= len(name)
									takeNameFromStartOfBlock = True
								else:
									name = block[moduleNamePointer:nameEnd]
							else:
								moduleNamePointer -= len(block)
						elif takeNameFromStartOfBlock:
							nameEnd = block.index(0)
							assert nameEnd >= 0
							name += block[:nameEnd]
							takeNameFromStartOfBlock = False
						else:
							break
					assert name != None
					assert not takeNameFromStartOfBlock
					
					#name = name.decode('ascii')
					
					#print("Module name is", name, "inside file", f)
					
					if name in duplicateNames:
						fullName = f + ":" + name
					elif name in self.modules:
						print("Warning: duplicate module with name", name)
						oldModule = self.modules[name]
						self.modules[oldModule["parentFile"] + ":" + name] = oldModule
						fullName = f + ":" + name
						duplicateNames.append(name)
					else:
						fullName = name
					
					self.modules[fullName] = {"blocks": currentModule, "name": name, "parentFile": f}

def loadCdiImageFile(filename: str) -> CdiFileSystem:
	with open(filename, "rb") as f:
		return CdiFileSystem(f.read())

