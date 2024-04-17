
from typing import Self
import struct

class StructStream:
	def __init__(self, data, cursor = 0, endianPrefix = None, simpleReturn = True):
		"""
		Endian prefix can be '<' for little endian, '>' for big endian.
		"""
		assert isinstance(data, bytes)
		self._data = data
		self._cursor = cursor
		self._prefix = endianPrefix
		self._simplify = simpleReturn
		
		self._peekAmount = 0
	
	###############
	# Built-ins
	
	def __len__(self):
		"""The remaining bytes in the stream."""
		return max(0, len(self._data) - self._cursor)

	def __str__(self):
		return str(self._data[self._cursor:])
	
	def __repr__(self):
		ret = "StructStream(" + repr(self.peekRaw(30))
		if len(self) > 30:
			ret += "..."
		ret += ", cursor=" + str(min(self._cursor, len(self._data)))
		if self._prefix:
			ret += ", endianPrefix=" + self._prefix
		return ret + ")"
	
	###############
	# Raw byte functions
	
	def peekRaw(self, count, fillZeros = False) -> bytes:
		ret = self._data[self._cursor:self._cursor + count]
		if fillZeros and len(ret) < count:
			ret += b'0' * (count - len(ret))
		self._peekAmount = count
		return ret
	
	def takeRaw(self, count, fillZeros = False) -> bytes:
		ret = self.peekRaw(count, fillZeros)
		self._cursor += count
		return ret
		
	def peekAll(self) -> bytes:
		return self.peekRaw(len(self))
	
	def takeAll(self) -> bytes:
		return self.takeRaw(len(self))
	
	###############
	# Struct-style functions
	
	def peek(self, formatStr, fillZeros = False):
		if len(formatStr) == 0:
			return ()
		if self._prefix and formatStr[0] not in "@=<>!":
			formatStr = self._prefix + formatStr
		retTuple = struct.unpack(formatStr, self.peekRaw(struct.calcsize(formatStr), fillZeros))
		if self._simplify and len(retTuple) == 1:
			return retTuple[0]
		else:
			return retTuple
	
	def take(self, formatStr, fillZeros = False):
		ret = self.peek(formatStr, fillZeros)
		self._cursor += self._peekAmount
		return ret
	
	def peekNullTermString(self, includeTerminator = False) -> bytes:
		self._cursor = max(self._cursor, 0)
		try:
			ret = self.peekRaw(self._data.index(0, self._cursor) - self._cursor + 1)
			if includeTerminator:
				return ret
			else:
				return ret[:-1]
		except ValueError:
			ret = self._data[self._cursor:]
			self._peekAmount = len(ret)
			return ret
	
	def takeNullTermString(self, includeTerminator = False) -> bytes:
		ret = self.peekNullTermString(includeTerminator=includeTerminator)
		self._cursor += self._peekAmount
		return ret
	
	###############
	# Stream operations
	
	def skip(self, count) -> Self:
		self._cursor = max(0, self._cursor + count)
		return self
	
	def seek(self, offset) -> Self:
		self._cursor = max(0, offset)
		return self
	
	def copy(self) -> Self:
		"""
		Performs a shallow copy, a second view into the same data stream. INCLUDES data from before the current
		cursor position.
		"""
		return StructStream(self._data, cursor=self._cursor, endianPrefix=self._prefix, simpleReturn=self._simplify)
	
	def fork(self, skip = 0) -> Self:
		"""
		Performs a shallow copy, a second view into the same data stream. EXCLUDES data from before the current
		cursor position.

		Optionally skips `skip` bytes before taking the fork, without modifying this stream.
		"""
		return StructStream(self._data[self._cursor + skip:], endianPrefix=self._prefix, simpleReturn=self._simplify)
	
	def peekFork(self, count, fillZeros = False) -> Self:
		"""Performs a peekRaw, and then constructs a new stream out of the data."""
		data = self.peekRaw(count, fillZeros)
		return StructStream(data, endianPrefix=self._prefix, simpleReturn=self._simplify)
	
	def takeFork(self, count, fillZeros = False) -> Self:
		"""Performs a peekRaw, and then constructs a new stream out of the data."""
		data = self.takeRaw(count, fillZeros)
		return StructStream(data, endianPrefix=self._prefix, simpleReturn=self._simplify)


def testStructStream():
	test = StructStream(b'hello\x00world\x00partial')
	t = test.peekNullTermString()
	assert t == b'hello', t
	t = test.takeNullTermString()
	assert t == b'hello', t
	t = test.takeNullTermString()
	assert t == b'world', t
	t = test.takeNullTermString()
	assert t == b'partial', t
	t = test.takeNullTermString()
	assert t == b''
	del t
	del test
	print("All tests passed")