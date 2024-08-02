import math
import sys
import os
import re
import subprocess
import PIL

startupinfo = None
if sys.platform == "win32":
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW


def spritesheet(ffmpeg_path, probe, image, worker=None):
    ffp = subprocess.Popen(
            [
                ffmpeg_path,
                '-v',
                'error',
                '-vcodec',
                'libvpx-vp9',
                '-r', '1',
                '-i', image,
                '-r', '1',
                '-progress', 'ffmpeg.log',
                os.path.splitext(image)[0]+"-frame%05d.png"
            ],
            startupinfo=startupinfo,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL
        )
    # ffp.wait()
    print(probe)
    duration = probe['duration']
    with open("ffmpeg.log", "a+") as f:
        logged = False
        pct = 0
        while ffp.poll() is None:
            l = f.readline()
            m = re.match(r"(.*?)=(.*)", l)
            if m:
                key = m.group(1)
                val = m.group(2)
                if key == "frame":
                    if not logged:
                        print(
                            " webm->sprite:    ",
                            file=sys.stderr,
                            end="",
                        )
                        logged = True
                    elif pct >= 100:
                        print("\b", file=sys.stderr, end="")
                    pos = round(float(val) * 100, 2)
                    pct = round(pos / float(probe["nb_read_frames"]) * .5)
                    print(
                        "\b\b\b{:02d}%".format(pct),
                        file=sys.stderr,
                        end="",
                    )
                    if worker:
                        worker.updateProgress(pct)
                    sys.stderr.flush()
    os.remove("ffmpeg.log")
    framewidth = probe['width']
    frameheight = probe['height']
    frames = []
    for afile in sorted(os.listdir(os.path.dirname(image))):
        if re.match(re.escape(os.path.splitext(os.path.basename(image))[0])+"-frame[0-9]{5}\.png",afile):
            frames.append(os.path.join(os.path.dirname(image), afile))

    def getGrid(n):
        i = 1
        factors = []
        while (i < n+1):
            if n % i == 0:
                factors.append(i)
            i += 1
        gw = factors[(len(factors)//2)]
        gh = factors[(len(factors)//2)-1]
        if gw*framewidth > 4096 or gh*frameheight > 4096:
            return (gh, gw)
        else:
            return (gw, gh)
    (gw, gh) = getGrid(len(frames))
    with PIL.Image.new('RGBA', (round(framewidth*gw), round(frameheight*gh)), color=(0, 0, 0, 0)) as img:
        px = 0
        py = 0
        for i in range(len(frames)):
            img.paste(PIL.Image.open(frames[i]), (framewidth*px, frameheight*py))
            os.remove(frames[i])
            px += 1
            if px == gw:
                px = 0
                py += 1
            pos = round(float(i) * 100, 2)
            if pct >= 100:
                print("\b", file=sys.stderr, end="")
            pct = round(pos / float(probe["nb_read_frames"]) * .5)+50
            print(
                "\b\b\b{:02d}%".format(pct),
                file=sys.stderr,
                end="",
            )
            if worker:
                worker.updateProgress(pct)
            sys.stderr.flush()
        if img.width > 4096 or img.height > 4096:
            
            scale = 4096/img.width if img.width >= img.height else 4096/img.height
            framewidth = math.floor(framewidth*scale)
            frameheight = math.floor(frameheight*scale)
            img = img.resize(((framewidth*gw), (frameheight*gh)))
        img.save(os.path.splitext(image)[0]+"-sprite.png")
    os.remove(image)
    return [os.path.splitext(image)[0]+"-sprite.png", duration, framewidth, frameheight]
