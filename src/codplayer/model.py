# codplayer - data model for discs and tracks
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""
Classes representing discs and tracks.

The unit of time in all objects is one sample.
"""


# Basic data formats

class LITTLE_ENDIAN: pass
class BIG_ENDIAN: pass

class PCM:
    channels = 2
    sample_size = 4
    rate = 44100
    byte_order = BIG_ENDIAN

    samples_per_frame = 588

    @classmethod
    def msf_to_samples(cls, msf):
        """Translate an MM:SS:FF to number of PCM samples."""

        d = msf.split(':')
        if len(d) != 3:
            raise ValueError(msf)

        m = int(d[0], 10)
        s = int(d[1], 10)
        f = int(d[2], 10)

        return (((m * 60) + s) * 75 + f) * cls.samples_per_frame



class RAW_CD:
    file_suffix = '.cdr'


# Various exceptions

class DiscInfoError(Exception):
    pass

    
# Actual data classes

class Disc(object):
    """Represents a CD, consisting of a number of tracks.
    """

    def __init__(self):
        self.data_file_name = None
        self.data_file_format = None
        self.sample_format = None

        self.tracks = []
        
        self.catalog = None
        

    def add_track(self, track):
        self.tracks.append(track)
        track.number = len(self.tracks)


    @classmethod
    def from_toc(cls, toc):
        """Parse a TOC generated by cdrdao into a Disc instance.

        This is not a full parse of all varieties that cdrdao itself
        allows, as this function is only intended to be used on TOCs
        generated by cdrdao itself.

        @param toc: a cdrdao TOC as a string

        @return: A L{Disc} object.

        @raise DiscInfoError: if the TOC can't be parsed.
        """

        disc = cls()

        track = None

        for line in toc.split('\n'):
            # Strip comments
            p = line.find('//')
            if p != -1:
                line = line[:p]
                
            line = line.strip()

            # Don't bother about disc flags
            if line in ('CD_DA', 'CD_ROM', 'CD_ROM_XA'):
                pass

            elif line.startswith('CATALOG '):
                disc.catalog = disc.get_toc_string_arg(line)

            # Start of a new track
            elif line.startswith('TRACK '):

                if track is not None:
                    disc.add_track(track)

                if line == 'TRACK AUDIO':
                    track = Track()
                else:
                    # Just skip non-audio tracks
                    track = None

            # Ignore some track flags that don't matter to us
            elif line in ('TWO_CHANNEL_AUDIO',
                          'COPY', 'NO COPY',
                          'PRE_EMPHASIS', 'NO PRE_EMPHASIS'):
                pass

            # Anyone ever seen one of these discs?
            elif line == 'FOUR_CHANNEL_AUDIO':
                raise DiscInfoError('no support for four-channel audio')

            # Implement CD_TEXT later
            elif line.startswith('CD_TEXT '):
                raise DiscInfoError('no support for parsing CD_TEXT yet')

            
            # Pick up the offsets within the data file
            elif line.startswith('FILE '):
                filename = disc.get_toc_string_arg(line)

                if disc.data_file_name is None:
                    disc.data_file_name = filename

                    if filename.endswith(RAW_CD.file_suffix):
                        disc.data_file_format = RAW_CD
                        disc.data_sample_format = PCM
                    else:
                        raise DiscInfoError('unknown file format: "%s"'
                                            % filename)

                elif disc.data_file_name != filename:
                    raise DiscInfoError('expected filename "%s", got "%s"'
                                        % (disc.data_file_name, filename))
                    

                p = line.split()

                # Just assume the last two are either 0 or an MSF
                if len(p) < 4:
                    raise DiscInfoError('missing offsets in file: %s' % line)

                offset = p[-2]
                length = p[-1]

                if offset == '0':
                    track.file_offset = 0
                else:
                    try:
                        track.file_offset = PCM.msf_to_samples(offset)
                    except ValueError:
                        raise DiscInfoError('bad offset for file: %s' % line)
                    
                try:
                    track.length = PCM.msf_to_samples(length)
                except ValueError:
                    raise DiscInfoError('bad length for file: %s' % line)


            elif line.startswith('SILENCE '):
                track.pregap_silence = disc.get_toc_msf_arg(line)

            elif line.startswith('START '):
                track.pregap_offset = disc.get_toc_msf_arg(line)

            elif line.startswith('INDEX '):
                # Adjust indices to be relative start of track instead
                # of pregap
                track.index.append(disc.get_toc_msf_arg(line)
                                   + track.pregap_offset)
                
            elif line.startswith('ISRC '):
                track.isrc = disc.get_toc_string_arg(line)

            elif line.startswith('DATAFILE '):
                pass

            elif line != '':
                raise DiscInfoError('unexpected line: %s' % line)
                

        if track is not None:
            disc.add_track(track)


        # Make sure we did read an audio disc
        if not disc.tracks:
            raise DiscInfoError('no audio tracks on disc')

        return disc


    @classmethod
    def from_musicbrainz_disc(cls, mb_disc, filename = None):
        """Translate a L{musicbrainz2.model.Disc} into a L{Disc}.
        This object will contain much less information than one read
        from a TOC, but will allow a data file to be played before
        cdrdao has finished writing the TOC.

        @param mb_disc: a L{musicbrainz2.model.Disc} object

        @param filename: the filename for the data file that is
        expected to be generated by cdrdao.

        @return: a L{Disc} object.
        """

        tracks = mb_disc.getTracks()

        # Make sure we have any tracks
        if not tracks:
            raise DiscInfoError('no audio tracks on disc')

        disc = cls()

        if filename is not None:
            disc.data_file_name = filename

            if filename.endswith(RAW_CD.file_suffix):
                disc.data_file_format = RAW_CD
                disc.data_sample_format = PCM
            else:
                raise DiscInfoError('unknown file format: "%s"'
                                    % filename)


        # Translate from frames into samples relative to the data file
        # that cdrdao will generate
        first_frame = tracks[0][0]

        for start, length in tracks:
            track = Track()
            track.file_offset = (start - first_frame) * PCM.samples_per_frame
            track.length = length * PCM.samples_per_frame
            disc.add_track(track)

        return disc
    

    @staticmethod
    def get_toc_string_arg(line):
        """Parse out a string argument from a TOC line."""
        s = line.find('"')
        if s == -1:
            raise DiscInfoError('no string argument in line: %s' % line)

        e = line.find('"', s + 1)
        if s == -1:
            raise DiscInfoError('no string argument in line: %s' % line)
        
        return line[s + 1 : e]


    @staticmethod
    def get_toc_msf_arg(line):
        """Parse an MSF from a TOC line."""

        p = line.split()
        if len(p) != 2:
            raise DiscInfoError(
                'expected a single MSF argument in line: %s' % line)

        try:
            return PCM.msf_to_samples(p[1])
        except ValueError:
            raise DiscInfoError('bad MSF in line: %s' % line)



class Track(object):
    """Represents one track on a disc and its offsets and indices.
    """

    def __init__(self):
        self.number = 0

        self.file_offset = 0
        self.length = 0

        # Where index switch from 0 to 1
        self.pregap_offset = 0

        # If part or all of the pregap isn't contained in the data
        # file at all
        self.pregap_silence = 0
        
        # Any additional indices
        self.index = []

        self.isrc = None
        