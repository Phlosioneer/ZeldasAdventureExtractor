
# Slightly modified from https://github.com/roysmeding/cditools/blob/master/cdi_decode_audio.py
# (Commit bd69b78)

import wave
import dataclasses

from typing import TYPE_CHECKING, Tuple, List

if TYPE_CHECKING:
    from cdi_filesystem import CdiSector

# a lookup list for the index of each parameter byte in the sound group header
PARAM_IDX = range(4, 12)

@dataclasses.dataclass
class Encoding:
    sample_rate: int
    sample_width: int
    stereo: bool

class ADPCMDec:
    "ADPCM decoder"

    def __init__(self):
        self.delayed1 = 0.     # two delay lines
        self.delayed2 = 0.
        self.G        = 0      # gain
        self.K0       = 0.     # first order filter coefficient
        self.K1       = 0.     # second order filter coefficient

    def set_params(self, G, F):
        # set range (exponential gain) value
        self.G = int(G)

        # set predictor filter
        if F == 0:
            self.K0 =  0.
            self.K1 =  0.
        elif F == 1:
            self.K0 =  0.9375
            self.K1 =  0.
        elif F == 2:
            self.K0 = 1.796875
            self.K1 = -0.8125
        elif F == 3:
            self.K0 =  1.53125
            self.K1 = -0.859375
        else:
            raise ValueError("Invalid filter setting %d" % F)

    def reset(self):
        self.delayed1 = 0.
        self.delayed2 = 0.

    def propagate(self, data):
        output = data * 2.**self.G  +  self.delayed1 * self.K0  +  self.delayed2 * self.K1
        output = max(-2**15, min(2**15-1, int(output)))
        self.delayed2 = self.delayed1
        self.delayed1 = output
        return output


def _sign_extend(v):
    "Convert 4-bit two's complement to python int"
    if v & (1<<3):
        return (v & ~(1<<3)) - (1<<3)
    else:
        return v

def _extract_params(p):
    "Extract ADPCM parameters (range, filter) from byte."
    return p & 0b00001111, ( p & 0b11110000) >> 4

def _extract_chans(d):
    "Extract channel data (left, right) from byte"
    return _sign_extend(d & 0b00001111), _sign_extend((d & 0b11110000) >> 4)

def getRawSamples(sectors: List["CdiSector"], channelMask: int) -> Tuple[List[int], Encoding]:
    encoding = None
    outsamples = []
    for sector in sectors:
        if sector.kind != "audio":
            continue
        if channelMask == None:
            channelMask = 1 << sector.channel
        elif (1 << sector.channel) & channelMask == 0:
            continue

        # determine encoding
        if encoding is None:
            encoding = sector.coding
            assert not (sector.coding & (1<<5)), "Reserved sample width specified in encoding"
            sample_width = 8 if (sector.coding & (1<<4)) else 4

            assert not (sector.coding & (1<<3)), "Reserved sample rate specified in encoding"
            sample_rate  = 18900 if (sector.coding & (1<<2)) else 37800

            assert not (sector.coding & (1<<1)), "Reserved channel number specified in encoding"
            stereo = True if (sector.coding & (1<<0)) else False

            if stereo:
                decoder_l = ADPCMDec()
                decoder_r = ADPCMDec()
            else:
                decoder = ADPCMDec()

            #print("%dHz, %dbit, %s "%(sample_rate, sample_width, "stereo" if stereo else "mono"))
        else:
            assert encoding == sector.coding, "Entire file must have same encoding"
        
        # read sound groups in sector
        for group in range(18):
            sound_group   = sector.data[group * 128:(group + 1) * 128]

            if sample_width == 8:
                for i in range(4):
                    for j in range(1, 4):
                        assert sound_group[i] == sound_group[i + 4 * j]

                # level A audio
                for unit in range(4):
                    R, F = _extract_params(sound_group[unit])
                    decoder.set_params(8-R, F)
                    for sample in range(28):
                        D = ord(sound_group[16+unit+4*sample])
                        outsamples.append(decoder.propagate(D))

            elif sample_width == 4:
                # level B or C audio
                for i in range(4):
                    assert sound_group[i]   == sound_group[i+4]
                    assert sound_group[i+8] == sound_group[i+12]

                if stereo:
                    for unit in range(4):
                        R1, F1 = _extract_params(sound_group[PARAM_IDX[unit*2]])
                        R2, F2 = _extract_params(sound_group[PARAM_IDX[unit*2+1]])
                        decoder_l.set_params(12-R1, F1)
                        decoder_r.set_params(12-R2, F2)

                        for sample in range(28):
                            D1, D2 = _extract_chans(sound_group[16+unit+4*sample])
                            outsamples.append(decoder_l.propagate(D1))
                            outsamples.append(decoder_r.propagate(D2))

                else:
                    for unit in range(8):
                        R, F = _extract_params(sound_group[PARAM_IDX[unit]])
                        decoder.set_params(12-R, F)

                        for sample in range(28):
                            D1, D2 = _extract_chans(sound_group[16+(unit//2)+4*sample])
                            if unit%2 == 0:
                                outsamples.append(decoder.propagate(D1))
                            else:
                                outsamples.append(decoder.propagate(D2))
        if sector.isEndOfRecord:
            break
    if len(outsamples) == 0:
        return outsamples, None
    else:
        return outsamples, Encoding(sample_rate, sample_width, stereo)

def saveSoundFile(sectors: List["CdiSector"], channelMask: int, fileName: str) -> bool:
    """
    Expects the filename without the extension. Files are saved in .wav format.
    
    Returns true if data was saved, returns false if no data was found.
    """
    
    samples, encoding = getRawSamples(sectors, channelMask)
    
    if len(samples) == 0:
        return False

    # write output file
    outfile = wave.open("{}.wav".format(fileName), 'wb')
    outfile.setnchannels(2 if encoding.stereo else 1)
    outfile.setsampwidth(2)
    outfile.setframerate(encoding.sample_rate)
    sampleByteStream = b"".join([(s & 0xFFFF).to_bytes(2, "little") for s in samples])
    outfile.writeframes(sampleByteStream)
    outfile.close()

    return True