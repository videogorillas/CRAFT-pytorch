# for [1..255] return 256
# for 256 return 256
# for 0 return 0
import collections
import json
import subprocess
from math import ceil
from subprocess import Popen
from typing import List

import numpy as np


def align16up(x: int) -> int:
    return x + 15 & (-15 - 1)


def video_stream(ffp):
    return next(filter(lambda x: x['codec_type'] == 'video', ffp['streams']))


Rational = collections.namedtuple('Rational', ['num', 'den'])


def parse_rational(r: str) -> Rational:
    (num, den) = r.replace(":", "/").split("/")
    return Rational(int(num), int(den))


def fps(ffp) -> Rational:
    name = ffp['format']['format_name']
    vstream = video_stream(ffp)
    fps: str = vstream['avg_frame_rate'] if name != "mxf" else vstream['r_frame_rate']
    if fps is None:
        return None
    return parse_rational(fps)


def ffmpeg_cmd(ffp, downscale: float = 2.0, startframe: int = 0, endframe_inclusive: int = -1) -> List[str]:
    vstream = video_stream(ffp)
    bps = int(vstream.get('bits_per_raw_sample', '8'))
    sarstr = vstream.get('sample_aspect_ratio', '1/1')
    sar = parse_rational(sarstr)

    duration: int = int(vstream['nb_frames'])
    assert duration > 0, "video has zero frames"
    if endframe_inclusive > -1:
        endframe_inclusive = min(duration - 1, endframe_inclusive)
    duration = min(duration, endframe_inclusive - startframe + 1)
    ss = 0
    if startframe > 0:
        _fps = fps(ffp)
        ss = startframe * _fps.den / _fps.num

    pix_fmt = "rgb48le" if bps > 8 else "rgb24"  # cv2.imread reads images in BGR order
    width = int(vstream['width'])
    height = int(vstream['height'])

    interlaced = False  # True  # TODO: vstream['..']
    # fix non-square pixel videos
    width = ceil(width * sar.num / sar.den)

    width16 = align16up(width)
    height16 = align16up(height)

    if downscale != 1:
        width16 = align16up(int(width / downscale))
        height16 = align16up(int(height / downscale))

    videopath = ffp['format']['filename']

    cmd: List[str] = ['ffmpeg', '-i', videopath]
    if ss > 0:
        cmd.extend(['-ss', str(ss)])
    if endframe_inclusive > -1:
        cmd.extend(['-vframes', str(duration)])

    if interlaced:
        yadif = "yadif,"
    else:
        yadif = ""
    if width != width16 or height != height16:
        cmd.extend(['-vf', "%sscale=%d:%d" % (yadif, width16, height16)])
    cmd.extend(['-pix_fmt', pix_fmt, '-f', 'rawvideo', '-'])

    return cmd


def ffprobejson(path: str):
    process: Popen = subprocess.Popen(
        ['ffprobe', '-i', path, '-show_streams', '-show_format', '-print_format', 'json'],
        stdout=subprocess.PIPE)
    return process.communicate()[0]


def ffprobe(path: str):
    return json.loads(ffprobejson(path))


class VideoLoader:
    def __init__(self, videopath: str, downscale: float = 1.0, startframe: int = 0, endframe_inclusive: int = -1):
        super(VideoLoader).__init__()
        assert startframe >= 0, "cant start with negative frame"
        self.videopath = videopath
        self.downscale = downscale
        self.previdx = -1
        self.process: Popen = None
        self.bytes_per_sample: int = 1
        self.nextfn = 0
        ffp = ffprobe(videopath)
        vstream = video_stream(ffp)
        assert vstream is not None, "video stream not found in " + videopath
        self.duration = int(vstream['nb_frames'])
        assert self.duration > 0, "video has zero frames"
        if endframe_inclusive < 0:
            endframe_inclusive = self.duration - 1
        self.duration = min(self.duration, endframe_inclusive - startframe + 1)

        bps = int(vstream['bits_per_raw_sample'])
        self.bytes_per_sample = 2 if bps > 8 else 1
        self.max_val = 65535. if bps > 8 else 255.
        self.want255 = 1. / 257. if bps > 8 else 1.
        uint16le = np.dtype(np.uint16)
        uint16le = uint16le.newbyteorder('L')
        self.dtype = uint16le if bps > 8 else np.uint8

        width = int(vstream['width'])
        height = int(vstream['height'])
        # fix non-square pixel videos
        sar = parse_rational(vstream.get('sample_aspect_ratio', '1/1'))
        width = ceil(width * sar.num / sar.den)

        self.width16 = align16up(int(width / downscale))
        self.height16 = align16up(int(height / downscale))
        self.cmd = ffmpeg_cmd(ffp, downscale, startframe, endframe_inclusive)
        print(" ".join(self.cmd))

    def forkffmpeg(self):
        self.process: Popen = subprocess.Popen(self.cmd, stdout=subprocess.PIPE)

    def readnextframe(self):
        if self.process is None:
            self.forkffmpeg()
        expected_len = self.width16 * self.height16 * 3 * self.bytes_per_sample
        b = self.process.stdout.read(expected_len)
        assert len(b) == expected_len
        nb = np.frombuffer(b, dtype=np.dtype(self.dtype), count=self.width16 * self.height16 * 3).reshape(
            (self.height16, self.width16, 3))
        self.nextfn += 1
        return nb * self.want255


class VideoEncoder:
    def __init__(self, outpath: str, in_w: int, in_h: int, fps: int = 24, crf: int = 21, in_pix_fmt: str = 'bgr24',
                 out_pix_fmt: str = 'yuv420p'):
        self.in_h = in_h
        self.in_w = in_w
        self.cmd = ['ffmpeg',
                    '-v', 'info',
                    '-f', 'rawvideo',
                    '-pix_fmt', in_pix_fmt, "-s:v", "%dx%d" % (in_w, in_h),
                    '-r', str(fps),
                    '-i', '-',
                    '-vcodec', 'libx264', '-g', str(int(fps)), '-bf', '0', '-crf', str(crf), '-pix_fmt', out_pix_fmt,
                    '-movflags', 'faststart', '-y', outpath]
        self.process = None

    def forkffmpeg(self):
        print(self.cmd)
        self.process = Popen(self.cmd, stdin=subprocess.PIPE)

    def imwrite(self, img: np.ndarray):
        if self.process is None:
            self.forkffmpeg()
        h = np.shape(img)[0]
        w = np.shape(img)[1]
        assert self.in_w == w and self.in_h == h
        uimg = img
        if img.dtype != np.uint8:
            uimg = img.astype(np.uint8)
        self.process.stdin.write(uimg.tobytes('C'))

    def close(self):
        if self.process is not None:
            self.process.stdin.close()
            self.process.wait(10.0)
