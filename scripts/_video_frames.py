"""Extract evenly spaced frames from a video for visual inspection.

Usage: python scripts/_video_frames.py <video> [n_frames]
Writes <video-dir>/_frames/frame_NNN.jpg and prints probe info.
"""
import json
import os
import subprocess
import sys

import imageio_ffmpeg

VIDEO = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\LONI GROUPS DM1\Downloads\AQMoNR7ST6MV-KPPaM8My6EMFTtaRzJdStrW3rGeoLcLrvy3Olvd8dfyuHHRoHkSyDkUGTphukj9pOsnYrOVWjbz5ySpz2cnh0NWU7_6Gg.mp4"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 24
FF = imageio_ffmpeg.get_ffmpeg_exe()

# probe duration via ffmpeg banner parse (no ffprobe available)
r = subprocess.run([FF, "-i", VIDEO], capture_output=True, text=True, errors="replace")
info = r.stderr
dur = None
for line in info.splitlines():
    if "Duration:" in line:
        print(line.strip())
        h, m, s = line.split("Duration:")[1].strip().split(",")[0].split(":")
        dur = int(h) * 3600 + int(m) * 60 + float(s)
    if "Video:" in line or "Audio:" in line:
        print(line.strip())

out = os.path.join(os.path.dirname(VIDEO), "_frames")
os.makedirs(out, exist_ok=True)
if dur is None:
    print("could not read duration")
    raise SystemExit(1)

print("duration %.1fs -> %d frames" % (dur, N))
for i in range(N):
    t = dur * (i + 0.5) / N
    dst = os.path.join(out, "frame_%03d.jpg" % i)
    subprocess.run([FF, "-y", "-ss", "%.2f" % t, "-i", VIDEO,
                    "-frames:v", "1", "-q:v", "3", dst],
                   capture_output=True)
    print("frame %02d @ %6.1fs -> %s" % (i, t, os.path.basename(dst)))
print("done:", out)
