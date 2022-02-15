# vim: set tabstop=8 softtabstop=0 expandtab shiftwidth=4 smarttab : #
import xml.etree.cElementTree as ET
import json
import re
import sys
import os
import tempfile
import shutil
import argparse
import uuid
from slugify import slugify
import zipfile
import urllib.parse
import urllib.request
import math
import PIL.Image
import PIL.ImageOps
import PIL.ImageDraw
import PIL.ImageFont
import random
import html
import magic
import subprocess
from google.protobuf import text_format
import fonts_public_pb2

VERSION = "1.13.11"

zipfile.ZIP64_LIMIT = 4294967294
PIL.Image.MAX_IMAGE_PIXELS = 200000000

try:
    ffmpeg_path = shutil.which("ffmpeg") or shutil.which("ffmpeg", path=os.defpath)
    ffprobe_path = shutil.which("ffprobe") or shutil.which("ffprobe", path=os.defpath)
    if sys.platform == "darwin" and not ffmpeg_path and not ffprobe_path:
        # Try homebrew paths
        brewpath = "/usr/local/bin" + os.pathsep + "/opt/homebrew/bin"
        ffmpeg_path = shutil.which("ffmpeg", path=brewpath)
        ffprobe_path = shutil.which("ffprobe", path=brewpath)
    if ffmpeg_path:
        ffmpeg_path = os.path.abspath(ffmpeg_path)
    if ffprobe_path:
        ffprobe_path = os.path.abspath(ffprobe_path)
except Exception:
    ffmpeg_path = None
    ffprobe_path = None

"""For pyinstaller -w"""
startupinfo = None
if sys.platform == "win32":
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

tempdir = None


def ffprobe(video: str) -> dict:
    process = subprocess.Popen(
        [
            ffprobe_path,
            "-v",
            "error",
            "-count_frames",
            "-show_entries",
            "format=duration",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,height,width,nb_read_frames",
            "-of",
            "default=noprint_wrappers=1",
            video,
        ],
        startupinfo=startupinfo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE,
    )
    probe = {}
    lines = process.stdout.readlines()
    for entry in lines:
        m = re.match(r"(.*)=(.*)", entry.decode())
        if m:
            if m.group(1) == "duration":
                probe[m.group(1)] = float(m.group(2))
            elif m.group(1) in ["height", "width"]:
                probe[m.group(1)] = int(m.group(2))
            else:
                probe[m.group(1)] = m.group(2)
    return probe


# Argument Parser
parser = argparse.ArgumentParser(
    description="Converts Foundry Modules/Worlds to EncounterPlus Modules"
)
parser.add_argument(
    "-o",
    dest="output",
    action="store",
    default=None,
    help="output into given output (default: [name].module)",
)
parser.add_argument(
    "-p",
    dest="packdir",
    action="store",
    default=None,
    help="create an asset pack using path provided instead of module",
)
parser.add_argument(
    "-pn",
    dest="packname",
    action="store_const",
    default=False,
    const=True,
    help="use asset path for pack name",
)
parser.add_argument(
    "-c",
    dest="compendium",
    action="store_const",
    const=True,
    default=False,
    help="create compendium content with actors and items",
)
parser.add_argument(
    "-j",
    dest="jpeg",
    action="store_const",
    const=".jpg",
    default=".webp",
    help="convert WebP Maps to JPG, WebP tiles to PNG",
)
parser.add_argument(
    "--link-maps",
    dest="jrnmap",
    action="store_const",
    const=True,
    default=False,
    help="Link maps to pages with the same name",
)
parser.add_argument(
    "--system",
    dest="system",
    action="store",
    default=None,
    help="Restrict content to packs using specified system (will include packs without a system specified)",
)
parser.add_argument(
    "-nc",
    dest="noconv",
    action="store_const",
    const=True,
    default=False,
    help="Do not convert WebP (default)",
)
parser.add_argument(
    "-nj",
    dest="noj",
    action="store_const",
    const=True,
    default=False,
    help="Skip journals",
)
parserg = parser.add_mutually_exclusive_group()
parserg.add_argument(
    dest="srcfile",
    action="store",
    default=False,
    nargs="?",
    help="foundry file to convert",
)
parserg.add_argument(
    "-gui",
    dest="gui",
    action="store_const",
    default=False,
    const=True,
    help="use graphical interface",
)
parser.add_argument(
    "--cover",
    dest="covername",
    action="store",
    default=None,
    help="use scene name for cover image",
)
args = parser.parse_args()
if args.covername:
    args.covernames = [args.covername.lower()]
else:
    args.covernames = [
        "intro",
        "start",
        "start here",
        "title page",
        "title",
        "landing",
        "landing page",
    ]
if args.noconv and args.jpeg == ".png":
    args.jpeg = ".webp"
if not args.srcfile and not args.gui:
    if sys.platform in ["darwin", "win32"]:
        args.gui = True
    else:
        parser.print_help()
        exit()
numbers = ["zero", "one", "two", "three", "four"]
stats = {
    "str": "Strength",
    "dex": "Dexterity",
    "con": "Constitution",
    "int": "Intelligence",
    "wis": "Wisdom",
    "cha": "Charisma",
}
skills = {
    "acr": "Acrobatics",
    "ani": "Animal Handling",
    "arc": "Arcana",
    "ath": "Athletics",
    "dec": "Deception",
    "his": "History",
    "ins": "Insight",
    "inv": "Investigation",
    "itm": "Intimidation",
    "med": "Medicine",
    "nat": "Nature",
    "per": "Persuasion",
    "prc": "Perception",
    "prf": "Performance",
    "rel": "Religion",
    "slt": "Sleight of Hand",
    "ste": "Stealth",
    "sur": "Survival",
}
schools = {
    "abj": "A",
    "con": "C",
    "div": "D",
    "enc": "EN",
    "evo": "EV",
    "ill": "I",
    "nec": "N",
    "trs": "T",
}


def indent(elem, level=0):
    i = "\n" + level * "  "
    j = "\n" + (level - 1) * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for subelem in elem:
            indent(subelem, level + 1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = j
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = j
    return elem


def fixRoll(m):
    if m.group(2):
        return '<a href="/roll/{0}/{1}">{0}</a>'.format(m.group(1), m.group(2))
    else:
        return '<a href="/roll/{0}">{0}</a>'.format(m.group(1))


def convert(args=args, worker=None):
    def createMap(map, mapgroup):
        if "padding" in map:
            map["offsetX"] = (
                math.ceil((map["padding"] * map["width"]) / map["grid"]) * map["grid"]
            )
            map["offsetY"] = (
                math.ceil((map["padding"] * map["height"]) / map["grid"]) * map["grid"]
            )
        else:
            map["offsetX"] = (
                map["width"]
                + math.ceil(0.5 * map["width"] / (map["grid"] * 2)) * (map["grid"] * 2)
                - map["width"]
            ) * 0.5
            map["offsetY"] = (
                map["height"]
                + math.ceil(0.5 * map["height"] / (map["grid"] * 2)) * (map["grid"] * 2)
                - map["height"]
            ) * 0.5
        map["offsetX"] -= map["shiftX"]
        map["offsetY"] -= map["shiftY"]
        mapbaseslug = slugify(map["name"])
        mapslug = mapbaseslug + str(len([i for i in slugs if mapbaseslug in i]))
        slugs.append(mapslug)
        if not map["img"]:
            with PIL.Image.new(
                "RGB", (map["width"], map["height"]), color="gray"
            ) as img:
                if map["tiles"][0]["width"] >= (map["width"] * 0.9) and map["tiles"][0][
                    "height"
                ] >= (map["height"] * 0.9):
                    bg = map["tiles"].pop(0)
                    bg["img"] = urllib.parse.unquote(bg["img"])
                    imgext = os.path.splitext(
                        os.path.basename(urllib.parse.urlparse(bg["img"]).path)
                    )[1]
                    bgimg = PIL.Image.open(bg["img"])
                    bg["x"] = round(bg["x"] - map["offsetX"])
                    bg["y"] = round(bg["y"] - map["offsetY"])
                    if bgimg.width != bg["width"] or bgimg.height != bg["height"]:
                        bgimg = bgimg.resize((bg["width"], bg["height"]))
                    if bg["scale"] != 1:
                        bgimg = bgimg.resize(
                            (
                                round(bgimg.width * bg["scale"]),
                                round(bgimg.height * bg["scale"]),
                            )
                        )
                    if bg["x"] > 0 and (bgimg.width + bg["x"]) > img.width:
                        bgimg = bgimg.crop((0, 0, bgimg.width - bg["x"], bgimg.height))
                    elif bg["x"] < 0:
                        bgimg = bgimg.crop(
                            (bg["x"] * -1, 0, bgimg.width + bg["x"], bgimg.height)
                        )
                        bg["x"] = 0
                    if bg["y"] > 0 and (bgimg.width + bg["y"]) > img.width:
                        bgimg = bgimg.crop((0, 0, bgimg.width, bgimg.height - bg["y"]))
                    elif bg["y"] < 0:
                        bgimg = bgimg.crop(
                            (0, bg["y"] * -1, bgimg.width, bgimg.height + bg["y"])
                        )
                        bg["y"] = 0
                    img.paste(bgimg, (bg["x"], bg["y"]))
                if args.jpeg == ".webp":
                    img.save(os.path.join(tempdir, mapslug + "_bg.webp"))
                    map["img"] = mapslug + "_bg.webp"
                else:
                    img.save(os.path.join(tempdir, mapslug + "_bg.jpg"))
                    map["img"] = mapslug + "_bg.jpg"
        #            if not imgext:
        #                imgext = args.jpeg
        #            if imgext == ".webp" and args.jpeg != ".webp":
        #                PIL.Image.open(bg["img"]).save(os.path.join(tempdir,os.path.splitext(bg["img"])[0]+args.jpeg))
        #                os.remove(bg["img"])
        #                map["img"] = os.path.splitext(bg["img"])[0]+args.jpeg
        #            else:
        #                map["img"] = bg["img"]
        #            map["shiftX"] = bg["x"]-map["offsetX"]
        #            map["shiftY"] = bg["y"]-map["offsetY"]
        #            map["width"] = bg["width"]
        #            map["height"] = bg["height"]
        map["rescale"] = 1.0
        if map["width"] > 8192 or map["height"] > 8192:
            map["rescale"] = (
                8192.0 / map["width"]
                if map["width"] >= map["height"]
                else 8192.0 / map["height"]
            )
            map["width"] = round(map["width"]*map["rescale"])
            map["height"] = round(map["height"]*map["rescale"])

        mapentry = ET.SubElement(
            module,
            "map",
            {"id": str(uuid.uuid5(moduuid, map["_id"])), "sort": str(int(map["sort"]))},
        )
        if mapgroup:
            mapentry.set("parent", mapgroup)
        elif "folder" in map and map["folder"]:
            mapentry.set("parent", str(uuid.uuid5(moduuid, map["folder"])))
        ET.SubElement(mapentry, "name").text = map["name"]
        ET.SubElement(mapentry, "slug").text = mapslug
        if map["img"] and os.path.exists(urllib.parse.unquote(map["img"])):
            map["img"] = urllib.parse.unquote(map["img"])
            imgext = os.path.splitext(os.path.basename(map["img"]))[1]
            if imgext == ".webm" or imgext == ".mp4":
                try:
                    if imgext == ".webm":
                        if args.gui:
                            worker.outputLog("Converting video map")
                        duration = int(ffprobe(map["img"])["nb_read_frames"])
                        ffp = subprocess.Popen(
                            [
                                ffmpeg_path,
                                "-v",
                                "error",
                                "-i",
                                map["img"],
                                "-vf",
                                "pad='width=ceil(iw/2)*2:height=ceil(ih/2)*2'",
                                "-vcodec",
                                "libx264",
                                "-acodec",
                                "aac",
                                "-progress",
                                "ffmpeg.log",
                                os.path.splitext(map["img"])[0] + ".mp4",
                            ],
                            startupinfo=startupinfo,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL,
                        )
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
                                                " webm->mp4:    ",
                                                file=sys.stderr,
                                                end="",
                                            )
                                            logged = True
                                        elif pct >= 100:
                                            print("\b", file=sys.stderr, end="")
                                        pos = round(float(val) * 100, 2)
                                        pct = round(pos / duration)
                                        print(
                                            "\b\b\b{:02d}%".format(pct),
                                            file=sys.stderr,
                                            end="",
                                        )
                                        if args.gui:
                                            worker.updateProgress(pct)
                                        sys.stderr.flush()
                        os.remove("ffmpeg.log")
                    ffp = subprocess.Popen(
                        [
                            ffmpeg_path,
                            "-v",
                            "error",
                            "-i",
                            map["img"],
                            "-vf",
                            "pad='width=ceil(iw/2)*2:height=ceil(ih/2)*2'",
                            "-vframes",
                            "1",
                            os.path.splitext(map["img"])[0] + ".jpg",
                        ],
                        startupinfo=startupinfo,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL,
                    )
                    print("\b" * 16, file=sys.stderr, end="")
                    print(" extracting still", file=sys.stderr, end="")
                    sys.stderr.flush()
                    ffp.wait()
                    if imgext == ".webm":
                        os.remove(map["img"])
                    map["img"] = os.path.splitext(map["img"])[0] + ".jpg"
                    ET.SubElement(mapentry, "video").text = (
                        os.path.splitext(map["img"])[0] + ".mp4"
                    )
                    print ("\nRescale is now at ",map["rescale"])
                    with PIL.Image.open(map["img"]) as img:
                        if map["height"] != img.height or map["width"] != img.width:
                            print("\n\nMAP IS {}x{},\nIMG IS: {}x{}\n\n".format(
                                 map["width"],map["height"],
                                 img.width,img.height))
                            rescale = (
                                img.width / map["width"]
                                if map["width"] >= map["height"]
                                else img.height / map["height"]
                            )
                            map["width"] = round(map["width"]*rescale)
                            map["height"] = round(map["height"]*rescale)
                            map["rescale"] *= rescale
                    print ("\nRescale is now at ",map["rescale"])
                except Exception:
                    import traceback

                    if args.gui:
                        worker.outputLog(traceback.format_exc())
                    else:
                        print(traceback.format_exc())
            if imgext == ".webp" and args.jpeg != ".webp":
                ET.SubElement(mapentry, "image").text = (
                    os.path.splitext(map["img"])[0] + args.jpeg
                )
            else:
                ET.SubElement(mapentry, "image").text = map["img"]
            with PIL.Image.open(map["img"]) as img:
                if (map["width"] / map["height"]) != (img.width / img.height):
                    neww = map["width"]
                    newh = map["height"]
                    if newh != img.height or neww != img.width:
                        print(
                            map["name"],
                            "Resizing {}x{} to {}x{} ({}!={})".format(
                                img.width,
                                img.height,
                                neww,
                                newh,
                                (img.width / img.height),(map["width"] / map["height"]),
                            ),
                        )
                        img = img.resize((neww, newh))
                        img.save(os.path.join(tempdir, map["img"]))
                if img.width > 8192 or img.height > 8192:
                    scale = (
                        8192 / img.width
                        if img.width >= img.height
                        else 8192 / img.height
                    )
                    print("Rescaling {}x{} ".format(img.width, img.height), end="")
                    if args.gui:
                        worker.outputLog(
                            " - Resizing map from {}x{} to {}x{} {}".format(
                                img.width,
                                img.height,
                                round(img.width * scale),
                                round(img.height * scale),
                            )
                        )
                    img = img.resize(
                        (round(img.width * scale), round(img.height * scale))
                    )
                    print("to {}x{} {}x".format(img.width, img.height,scale))
                    if imgext == ".webp" and args.jpeg != ".webp":
                        if args.gui:
                            worker.outputLog(
                                " - Converting map from .webp to " + args.jpeg
                            )
                        img.save(
                            os.path.join(
                                tempdir, os.path.splitext(map["img"])[0] + args.jpeg
                            )
                        )
                        os.remove(map["img"])
                    else:
                        img.save(os.path.join(tempdir, map["img"]))
                elif imgext == ".webp" and args.jpeg != ".webp":
                    if args.gui:
                        worker.outputLog(" - Converting map from .webp to " + args.jpeg)
                    img.save(
                        os.path.join(
                            tempdir, os.path.splitext(map["img"])[0] + args.jpeg
                        )
                    )
                    os.remove(map["img"])
                if map["height"] != img.height or map["width"] != img.width:
                    map["scale"] = (
                        map["width"] / img.width
                        if map["width"] / img.width >= map["height"] / img.height
                        else map["height"] / img.height
                    )
                    if map["scale"] > 1.25:
                        map["scale"] = 1.0
                        map["rescale"] = (
                            img.width / map["width"]
                            if img.width / map["width"] >= img.height / map["height"]
                            else img.height / map["height"]
                        )
                else:
                    map["scale"] = 1.0
        else:
            print(
                " |> Map Error NO BG FOR: {}".format(map["name"]),
                file=sys.stderr,
                end="",
            )
            map["scale"] = 1.0
            with PIL.Image.new(
                "1", (map["width"], map["height"]), color="black"
            ) as img:
                if img.width > 8192 or img.height > 8192:
                    scale = (
                        8192 / img.width
                        if img.width >= img.height
                        else 8192 / img.height
                    )
                    if args.gui:
                        worker.outputLog(
                            " - Resizing map from {}x{} to {}x{}".format(
                                img.width,
                                img.height,
                                round(img.width * scale),
                                round(img.height * scale),
                            )
                        )
                    img = img.resize(
                        (round(img.width * scale), round(img.height * scale))
                    )
                img.save(os.path.join(tempdir, mapslug + "_bg.png"))
                if map["height"] != img.height or map["width"] != img.width:
                    map["scale"] = (
                        map["width"] / img.width
                        if map["width"] / img.width >= map["height"] / img.height
                        else map["height"] / img.height
                    )
                    if map["scale"] > 1.25:
                        map["scale"] = 1.0
                        map["rescale"] = (
                            img.width / map["width"]
                            if img.width / map["width"] >= img.height / map["height"]
                            else img.height / map["height"]
                        )
                else:
                    map["scale"] = 1.0

                ET.SubElement(mapentry, "image").text = mapslug + "_bg" + args.jpeg
            if "thumb" in map and map["thumb"] and os.path.exists(map["thumb"]):
                imgext = os.path.splitext(os.path.basename(map["img"]))[1]
                if imgext == ".webp" and args.jpeg != ".webp":
                    ET.SubElement(mapentry, "snapshot").text = (
                        os.path.splitext(map["thumb"])[0] + args.jpeg
                    )
                    PIL.Image.open(map["thumb"]).save(
                        os.path.join(
                            tempdir, os.path.splitext(map["thumb"])[0] + args.jpeg
                        )
                    )
                    os.remove(map["thumb"])
                else:
                    ET.SubElement(mapentry, "snapshot").text = map["thumb"]
        map["grid"] *= map["rescale"]
        map["shiftX"] *= map["rescale"]
        map["shiftY"] *= map["rescale"]
        if round(map["grid"]) != map["grid"]:
            map["realign"] = round(map["grid"]) / map["grid"]
        elif map["gridType"] > 1 and round(map["grid"] / 2.0) != (map["grid"] / 2.0):
            map["realign"] = round(map["grid"] / 2.0) / (map["grid"] / 2.0)
        else:
            map["realign"] = 1.0
        if map["gridType"] > 1:
            map["grid"] = round(map["grid"] / 2.0)
            if 2 <= map["gridType"] <= 3:
                if map["gridType"] == 2:
                    map["shiftY"] += map["grid"]
                else:
                    map["shiftY"] -= map["grid"] / 2.0
            elif 4 <= map["gridType"] <= 5:
                map["shiftY"] += map["grid"] / 2.0
                if map["gridType"] == 4:
                    map["shiftX"] -= map["grid"]
                else:
                    map["shiftX"] += map["grid"] / 2.0
            map["shiftX"] *= map["realign"]
            map["shiftY"] *= map["realign"]
        map["rescale"] *= map["realign"]
        ET.SubElement(mapentry, "gridSize").text = str(round(map["grid"]))
        ET.SubElement(mapentry, "scale").text = str(map["realign"])
        ET.SubElement(mapentry, "gridScale").text = str(round(map["gridDistance"]))
        ET.SubElement(mapentry, "gridUnits").text = str(map["gridUnits"])
        ET.SubElement(mapentry, "gridVisible").text = (
            "NO" if map["gridType"] == 0 else "YES" if map["gridAlpha"] > 0 else "NO"
        )
        ET.SubElement(mapentry, "gridColor").text = map["gridColor"]
        ET.SubElement(mapentry, "gridOffsetX").text = str(round(map["shiftX"]))
        ET.SubElement(mapentry, "gridOffsetY").text = str(round(map["shiftY"]))
        ET.SubElement(mapentry, "gridType").text = (
            "hexFlat"
            if 4 <= map["gridType"] <= 5
            else "hexPointy"
            if 2 <= map["gridType"] <= 3
            else "square"
        )
        ET.SubElement(mapentry, "lineOfSight").text = (
            "YES" if map["tokenVision"] else "NO"
        )
        if "fogExploration" in map and map["fogExploration"]:
            ET.SubElement(mapentry, "fogOfWar").text = "YES"
            ET.SubElement(mapentry, "fogExploration").text = "YES"
        if "globalLight" in map and map["globalLight"]:
            ET.SubElement(mapentry, "losDaylight").text = str(1.0-map["darkness"])
        if "walls" in map and len(map["walls"]) > 0:
            for i in range(len(map["walls"])):
                p = map["walls"][i]
                if "sight" in p:
                    p["sense"] = 1 if p["sight"] == 20 else 2 if p["sight"] == 10 else 0
                    p["move"] = 1 if p["move"] == 20 else 0
                print("\rwall {}".format(i), file=sys.stderr, end="")
                pathlist = [
                    (p["c"][0] - map["offsetX"]) * map["rescale"],
                    (p["c"][1] - map["offsetY"]) * map["rescale"],
                    (p["c"][2] - map["offsetX"]) * map["rescale"],
                    (p["c"][3] - map["offsetY"]) * map["rescale"],
                ]
                isConnected = False
                for pWall in mapentry.iter("wall"):
                    lastpath = pWall.find("data")
                    pWallID = pWall.get("id")
                    if lastpath is not None and lastpath.text.endswith(
                        ",{:.1f},{:.1f}".format(pathlist[0], pathlist[1])
                    ):
                        wType = pWall.find("type")
                        if p["door"] > 0:
                            if p["door"] == 1 and wType.text != "door":
                                continue
                            if p["door"] == 2 and wType.text != "secretDoor":
                                continue
                            if p["ds"] > 0:
                                door = pWall.find("door")
                                if door is None:
                                    continue
                                elif p["ds"] == 1 and door.text != "open":
                                    continue
                                elif p["ds"] == 2 and door.text != "locked":
                                    continue
                        elif wType.text in ["door", "secretDoor"]:
                            continue
                        elif (
                            p["move"] == 0
                            and p["sense"] == 1
                            and wType.text != "ethereal"
                        ):
                            continue
                        elif (
                            p["move"] == 1
                            and p["sense"] == 0
                            and wType.text != "invisible"
                        ):
                            continue
                        elif (
                            p["move"] == 1
                            and p["sense"] == 2
                            and wType.text != "terrain"
                        ):
                            continue
                        elif (
                            p["move"] == 1
                            and p["sense"] == 1
                            and wType.text != "normal"
                        ):
                            continue
                        if "dir" in p:
                            wSide = pWall.find("side")
                            if wSide is None and p["dir"] > 0:
                                continue
                            if p["dir"] == 1 and wSide.text != "left":
                                continue
                            if p["dir"] == 2 and wSide.text != "right":
                                continue
                        isConnected = True
                        # pWall.set('id',pWallID+' '+p['_id'])
                        lastpath.text += "," + ",".join(
                            "{:.1f}".format(x) for x in pathlist
                        )
                        break
                if not isConnected:
                    wall = ET.SubElement(
                        mapentry, "wall", {"id": str(uuid.uuid5(moduuid, p["_id"]))}
                    )
                    lastpath = ET.SubElement(wall, "data")
                    lastpath.text = ",".join("{:.1f}".format(x) for x in pathlist)
                if not isConnected:
                    if "door" in p and p["door"] == 1:
                        ET.SubElement(wall, "type").text = "door"
                        ET.SubElement(wall, "color").text = "#00ffff"
                        if p["ds"] > 0:
                            ET.SubElement(wall, "door").text = (
                                "locked" if p["ds"] == 2 else "open"
                            )
                    elif p["door"] == 2:
                        ET.SubElement(wall, "type").text = "secretDoor"
                        ET.SubElement(wall, "color").text = "#00ffff"
                        if p["ds"] > 0:
                            ET.SubElement(wall, "door").text = (
                                "locked" if p["ds"] == 2 else "open"
                            )
                    elif p["move"] == 0 and p["sense"] == 1:
                        ET.SubElement(wall, "type").text = "ethereal"
                        ET.SubElement(wall, "color").text = "#7f007f"
                    elif p["move"] == 1 and p["sense"] == 0:
                        ET.SubElement(wall, "type").text = "invisible"
                        ET.SubElement(wall, "color").text = "#ff00ff"
                    elif p["move"] == 1 and p["sense"] == 2:
                        ET.SubElement(wall, "type").text = "terrain"
                        ET.SubElement(wall, "color").text = "#ffff00"
                    else:
                        ET.SubElement(wall, "type").text = "normal"
                        ET.SubElement(wall, "color").text = "#ff7f00"
                    if "dir" in p and p["dir"] > 0:
                        ET.SubElement(wall, "side").text = (
                            "left" if p["dir"] == 1 else "right"
                        )

                    if "door" in p and p["door"] > 0:
                        p["stroke"] = "#00ffff"
                    else:
                        p["stroke"] = "#ff7f00"
                    p["stroke_width"] = 5
                    p["layer"] = "walls"

                    ET.SubElement(wall, "generated").text = "YES"

        if "tiles" in map:
            for i in range(len(map["tiles"])):
                image = map["tiles"][i]
                if image["img"] is None:
                    continue
                if "scale" not in image:
                    image["scale"] = 1
                image["img"] = urllib.parse.unquote(image["img"])
                print(
                    "\rtiles [{}/{}]".format(i, len(map["tiles"])),
                    file=sys.stderr,
                    end="",
                )
                tile = ET.SubElement(mapentry, "tile")
                ET.SubElement(tile, "x").text = str(
                    round(
                        (
                            image["x"]
                            - map["offsetX"]
                            + (image["width"] * image["scale"] / 2)
                        )
                        * map["rescale"]
                    )
                )
                ET.SubElement(tile, "y").text = str(
                    round(
                        (
                            image["y"]
                            - map["offsetY"]
                            + (image["height"] * image["scale"] / 2)
                        )
                        * map["rescale"]
                    )
                )
                ET.SubElement(tile, "zIndex").text = str(image["z"])
                ET.SubElement(tile, "width").text = str(
                    round(image["width"] * image["scale"] * map["rescale"])
                )
                ET.SubElement(tile, "height").text = str(
                    round(image["height"] * image["scale"] * map["rescale"])
                )
                ET.SubElement(tile, "opacity").text = "1.0"
                ET.SubElement(tile, "rotation").text = str(image["rotation"])
                ET.SubElement(tile, "locked").text = "YES" if image["locked"] else "NO"
                ET.SubElement(tile, "layer").text = "object"
                ET.SubElement(tile, "hidden").text = "YES" if image["hidden"] else "NO"

                asset = ET.SubElement(tile, "asset")
                ET.SubElement(asset, "name").text = os.path.splitext(
                    os.path.basename(image["img"])
                )[0]
                imgext = os.path.splitext(os.path.basename(image["img"]))[1]
                if imgext == ".webm":
                    try:
                        if os.path.exists(image["img"]):
                            if args.gui:
                                worker.outputLog(
                                    " - Converting webm tile to animated webp"
                                )
                            probe = ffprobe(image["img"])
                            duration = int(probe["nb_read_frames"])
                            if probe["codec_name"] != "vp9":
                                ffp = subprocess.Popen(
                                    [
                                        ffmpeg_path,
                                        "-v",
                                        "error",
                                        "-vcodec",
                                        "libvpx",
                                        "-progress",
                                        "ffmpeg.log",
                                        "-i",
                                        image["img"],
                                        "-loop",
                                        "0",
                                        image["img"] + ".webp",
                                    ],
                                    startupinfo=startupinfo,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL,
                                )
                            else:
                                ffp = subprocess.Popen(
                                    [
                                        ffmpeg_path,
                                        "-v",
                                        "error",
                                        "-vcodec",
                                        "libvpx-vp9",
                                        "-progress",
                                        "ffmpeg.log",
                                        "-i",
                                        image["img"],
                                        "-loop",
                                        "0",
                                        image["img"] + ".webp",
                                    ],
                                    startupinfo=startupinfo,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL,
                                )

                            with open("ffmpeg.log", "a+") as f:
                                logged = False
                                while ffp.poll() is None:
                                    l = f.readline()
                                    m = re.match(r"(.*?)=(.*)", l)
                                    if m:
                                        key = m.group(1)
                                        val = m.group(2)
                                        if key == "frame":
                                            if not logged:
                                                print(
                                                    " webm->webp:    ",
                                                    file=sys.stderr,
                                                    end="",
                                                )
                                                logged = True
                                            elif pct >= 100:
                                                print("\b", file=sys.stderr, end="")
                                            pos = round(float(val) * 100, 2)
                                            pct = round(pos / duration)
                                            print(
                                                "\b\b\b{:02d}%".format(pct),
                                                file=sys.stderr,
                                                end="",
                                            )
                                            if args.gui:
                                                worker.updateProgress(pct)
                                            sys.stderr.flush()
                            os.remove("ffmpeg.log")
                        if os.path.exists(image["img"] + ".webp"):
                            ET.SubElement(asset, "type").text = "animatedImage"
                            ET.SubElement(asset, "resource").text = (
                                image["img"] + ".webp"
                            )
                        continue
                    except Exception:
                        import traceback

                        print(traceback.format_exc())
                        if args.gui:
                            worker.outputLog(
                                " - webm tiles are not supported, consider converting to an animated image or spritesheet: "
                                + image["img"]
                            )
                        print(
                            " - webm tiles are not supported, consider converting to an animated image or a spritesheet:",
                            image["img"],
                            file=sys.stderr,
                            end="",
                        )
                    continue
                else:
                    ET.SubElement(asset, "type").text = "image"
                if image["img"].startswith("http"):
                    urllib.request.urlretrieve(
                        image["img"], os.path.basename(image["img"])
                    )
                    image["img"] = os.path.basename(image["img"])
                if not os.path.exists(image["img"]):
                    if os.path.exists(os.path.splitext(image["img"])[0] + ".png"):
                        image["img"] = os.path.splitext(image["img"])[0] + ".png"
                        imgext = ".png"
                    else:
                        if args.gui:
                            worker.outputLog(" - MISSING RESOURCE: " + image["img"])
                        print(
                            " - MISSING RESOURCE:",
                            image["img"],
                            file=sys.stderr,
                            end="",
                        )
                        continue
                img = PIL.Image.open(image["img"])
                if (
                    img.width <= 300
                    and img.height <= 300
                    and 0.9 <= img.width / img.height <= 1.1
                ):
                    if "journal" in map and map["journal"]:
                        try:
                            from markerocr import placeMarker

                            placeMarker(img, map, image, mapentry, module, moduuid)
                        except:
                            pass
                if imgext == ".webp" and args.jpeg != ".webp":
                    ET.SubElement(asset, "resource").text = (
                        os.path.splitext(image["img"])[0] + ".png"
                    )
                    if img.width > 4096 or img.height > 4096:
                        scale = (
                            4095 / img.width
                            if img.width >= img.height
                            else 4095 / img.height
                        )
                        img = img.resize(
                            (round(img.width * scale), round(img.height * scale))
                        )
                    if args.gui:
                        worker.outputLog(" - Converting tile from webp to png")
                    img.save(
                        os.path.join(
                            tempdir, os.path.splitext(image["img"])[0] + ".png"
                        )
                    )
                    os.remove(image["img"])
                else:
                    ET.SubElement(asset, "resource").text = image["img"]
                    if img.width > 4096 or img.height > 4096:
                        scale = (
                            4095 / img.width
                            if img.width >= img.height
                            else 4095 / img.height
                        )
                        img = img.resize(
                            (round(img.width * scale), round(img.height * scale))
                        )
                        img.save(os.path.join(tempdir, image["img"]))
        if "lights" in map:
            for i in range(len(map["lights"])):
                print(
                    "\rlights [{}/{}]".format(i, len(map["lights"])),
                    file=sys.stderr,
                    end="",
                )
                light = map["lights"][i]
                if "config" in light:
                    light["dim"] = light["config"]["dim"]
                    light["bright"] = light["config"]["bright"]
                    if "color" in light["config"]:
                        light["tintColor"] = light["config"]["color"]
                    light["tintAlpha"] = light["config"]["alpha"]
                if "lightAnimation" in light and light["lightAnimation"] and "type" in light["lightAnimation"] and light["lightAnimation"]["type"] == "ghost":
                    continue
                lightel = ET.SubElement(
                    mapentry,
                    "light",
                    {
                        "id": str(
                            uuid.uuid5(moduuid, mapslug + "/lights/" + str(i) + "light")
                        )
                    },
                )
                ET.SubElement(lightel, "radiusMax").text = (
                    str(round(light["dim"])) if light["dim"] else "0"
                )
                ET.SubElement(lightel, "radiusMin").text = (
                    str(round(light["bright"])) if light["bright"] else "0"
                )
                ET.SubElement(lightel, "color").text = (
                    light["tintColor"]
                    if "tintColor" in light and light["tintColor"]
                    else "#ffffff"
                )
                ET.SubElement(lightel, "opacity").text = str(light["tintAlpha"])
                ET.SubElement(lightel, "alwaysVisible").text = (
                    "YES" if "t" in light and light["t"] == "u" else "NO"
                )
                ET.SubElement(lightel, "x").text = str(
                    round((light["x"] - map["offsetX"]) * map["rescale"])
                )
                ET.SubElement(lightel, "y").text = str(
                    round((light["y"] - map["offsetY"]) * map["rescale"])
                )

        if "tokens" in map and len(map["tokens"]) > 0:
            # encentry = ET.SubElement(module,'encounter',{'id': str(uuid.uuid5(moduuid,mapslug+"/encounter")),'parent': str(uuid.uuid5(moduuid,map['_id']+map['name'])), 'sort': '1'})
            # ET.SubElement(encentry,'name').text = map['name'] + " Encounter"
            # ET.SubElement(encentry,'slug').text = slugify(map['name'] + " Encounter")
            for token in map["tokens"]:
                if "dimLight" not in token:
                    token["dimLight"] = token["light"]["dim"] if "light" in token else 0
                if "brightLight" not in token:
                    token["brightLight"] = token["light"]["bright"] if "light" in token else 0
                if "lightAlpha" not in token:
                    token["lightAlpha"] = token["light"]["alpha"] if "light" in token else 1
                if 4 <= map["gridType"] <= 5:
                    tokenOffsetX = round(
                        ((2 * map["grid"] * 0.75 * token["width"]) + (map["grid"] / 2))
                        / 2
                    )
                    tokenOffsetY = round(
                        (math.sqrt(3) * map["grid"] * token["height"]) / 2
                    )
                    if map["gridType"] == 5:
                        tokenOffsetX += round(map["grid"])
                    token["scale"] /= 0.8
                elif 2 <= map["gridType"] <= 3:
                    tokenOffsetX = round(
                        (math.sqrt(3) * map["grid"] * token["width"]) / 2
                    )
                    tokenOffsetY = round(
                        ((2 * map["grid"] * 0.75 * token["height"]) + (map["grid"] / 2))
                        / 2
                    )
                    if map["gridType"] == 3:
                        tokenOffsetX += round(map["grid"])
                else:
                    tokenOffsetX = round(token["width"] * (map["grid"] / 2))
                    tokenOffsetY = round(token["height"] * (map["grid"] / 2))
                tokenel = ET.SubElement(
                    mapentry,
                    "token",
                    {
                        "id": str(
                            uuid.uuid5(moduuid, mapslug + "/token/" + token["_id"])
                        )
                    },
                )
                ET.SubElement(tokenel, "name").text = token["name"]
                ET.SubElement(tokenel, "x").text = str(
                    round(((token["x"] - map["offsetX"]) * map["rescale"]))
                    + tokenOffsetX
                )
                ET.SubElement(tokenel, "y").text = str(
                    round(((token["y"] - map["offsetY"]) * map["rescale"]))
                    + tokenOffsetY
                )

                if os.path.exists(token["img"]):
                    tokenasset = ET.SubElement(
                        tokenel,
                        "asset",
                        {
                            "id": str(
                                uuid.uuid5(
                                    moduuid,
                                    mapslug + "/token/" + token["_id"] + "/asset",
                                )
                            )
                        },
                    )
                    ET.SubElement(tokenasset, "name").text = token["name"]
                    ET.SubElement(tokenasset, "type").text = "image"
                    ET.SubElement(tokenasset, "resource").text = token["img"]
                ET.SubElement(tokenel, "hidden").text = (
                    "YES" if token["hidden"] else "NO"
                )
                ET.SubElement(tokenel, "scale").text = str(token["scale"])
                if token["width"] == token["height"] and 1 <= token["width"] <= 6:
                    ET.SubElement(tokenel, "size").text = (
                        "C"
                        if token["width"] > 4
                        else "G"
                        if token["width"] > 3
                        else "H"
                        if token["width"] > 2
                        else "L"
                        if token["width"] > 1
                        else "M"
                    )
                elif token["width"] == token["height"] and token["width"] < 1:
                    ET.SubElement(tokenel, "size").text = (
                        "T" if token["width"] <= 0.5 else "S"
                    )
                else:
                    ET.SubElement(tokenel, "size").text = "{}x{}".format(
                        token["width"], token["height"]
                    )
                ET.SubElement(tokenel, "rotation").text = str(token["rotation"])
                ET.SubElement(tokenel, "elevation").text = str(token["elevation"])
                vision = ET.SubElement(
                    tokenel,
                    "vision",
                    {
                        "id": str(
                            uuid.uuid5(
                                moduuid, mapslug + "/token/" + token["_id"] + "/vision"
                            )
                        )
                    },
                )
                ET.SubElement(vision, "enabled").text = (
                    "YES" if token["vision"] else "NO"
                )
                ET.SubElement(vision, "light").text = (
                    "YES" if int(token["dimLight"]) > 0 or int(token["brightLight"]) > 0 else "NO"
                )
                ET.SubElement(vision, "lightRadiusMin").text = str(
                    round(token["brightLight"])
                )
                ET.SubElement(vision, "lightRadiusMax").text = str(
                    round(token["dimLight"])
                )
                ET.SubElement(vision, "lightOpacity").text = str(token["lightAlpha"])
                ET.SubElement(vision, "dark").text = (
                    "YES" if int(token["dimSight"]) > 0 or int(token["brightSight"]) > 0 else "NO"
                )
                ET.SubElement(vision, "darkRadiusMin").text = str(
                    round(int(token["brightSight"]))
                )
                ET.SubElement(vision, "darkRadiusMax").text = str(
                    round(int(token["dimSight"]))
                )

                actorLinked = False
                for a in actors:
                    if a["_id"] == token["actorId"]:
                        ET.SubElement(tokenel, "reference").text = "/monster/{}".format(
                            uuid.uuid5(moduuid, a["_id"])
                            if args.compendium
                            else slugify(a["name"])
                        )
                        actorLinked = True
                        break
                if not actorLinked and args.compendium:
                    for a in actors:
                        if a["token"]["name"] == token["name"]:
                            ET.SubElement(
                                tokenel, "reference"
                            ).text = "/monster/{}".format(
                                uuid.uuid5(moduuid, a["_id"])
                                if args.compendium
                                else slugify(a["name"])
                            )
                            actorLinked = True
                            break
                if not actorLinked:
                    ET.SubElement(tokenel, "reference").text = "/monster/{}".format(
                        slugify(token["name"])
                    )

        if "drawings" in map and len(map["drawings"]) > 0:
            for d in map["drawings"]:
                if d["type"] == "t":
                    with PIL.Image.new(
                        "RGBA",
                        (round(d["width"]), round(d["height"])),
                        color=(0, 0, 0, 0),
                    ) as img:
                        d["fontSize"] = round(d["fontSize"] / 0.75)
                        try:
                            font = PIL.ImageFont.truetype(
                                os.path.join(
                                    moduletmp,
                                    mod["name"],
                                    "fonts",
                                    d["fontFamily"] + ".ttf",
                                ),
                                size=d["fontSize"],
                            )
                        except Exception:
                            try:
                                font = PIL.ImageFont.truetype(
                                    d["fontFamily"] + ".ttf", size=d["fontSize"]
                                )
                            except Exception as e:
                                try:
                                    solbera = {
                                        "bookmania": "https://raw.githubusercontent.com/jonathonf/solbera-dnd-fonts/master/Bookinsanity/Bookinsanity.otf",
                                        "scala sans caps": "https://raw.githubusercontent.com/jonathonf/solbera-dnd-fonts/master/Scaly%20Sans%20Caps/Scaly%20Sans%20Caps.otf",
                                        "modesto condensed": "https://raw.githubusercontent.com/jonathonf/solbera-dnd-fonts/master/Nodesto%20Caps%20Condensed/Nodesto%20Caps%20Condensed.otf",
                                        "mrs eaves small caps": "https://raw.githubusercontent.com/jonathonf/solbera-dnd-fonts/master/Mr%20Eaves/Mr%20Eaves%20Small%20Caps.otf",
                                        "dai vernon misdirect": "https://raw.githubusercontent.com/jonathonf/solbera-dnd-fonts/master/Zatanna%20Misdirection/Zatanna%20Misdirection.otf",
                                        "scala sans": "https://raw.githubusercontent.com/jonathonf/solbera-dnd-fonts/master/Scaly%20Sans/Scaly%20Sans.otf",
                                    }
                                    if d["fontFamily"].lower() in solbera.keys():
                                        urllib.request.urlretrieve(
                                            solbera[d["fontFamily"].lower()],
                                            d["fontFamily"] + ".otf",
                                        )
                                        font = PIL.ImageFont.truetype(
                                            d["fontFamily"] + ".otf", size=d["fontSize"]
                                        )
                                    else:
                                        urllib.request.urlretrieve(
                                            "https://raw.githubusercontent.com/google/fonts/master/ofl/{}/METADATA.pb".format(
                                                urllib.parse.quote(
                                                    d["fontFamily"].lower()
                                                )
                                            ),
                                            d["fontFamily"] + ".pb",
                                        )
                                        protobuf_file_path = d["fontFamily"] + ".pb"
                                        protobuf_file = open(protobuf_file_path, "r")
                                        protobuf = protobuf_file.read()
                                        font_family = fonts_public_pb2.FamilyProto()
                                        text_format.Merge(protobuf, font_family)
                                        urllib.request.urlretrieve(
                                            "https://raw.githubusercontent.com/google/fonts/master/ofl/{}/{}".format(
                                                urllib.parse.quote(
                                                    d["fontFamily"].lower()
                                                ),
                                                font_family.fonts[0].filename,
                                            ),
                                            d["fontFamily"] + ".ttf",
                                        )
                                        font = PIL.ImageFont.truetype(
                                            d["fontFamily"] + ".ttf", size=d["fontSize"]
                                        )
                                except Exception as e:
                                    print(
                                        '\rUnable to load font for "{}"'.format(
                                            d["fontFamily"]
                                        ),
                                        e,
                                        file=sys.stderr,
                                        end="\n",
                                    )
                                    font = PIL.ImageFont.load_default()
                        text = d["text"]
                        draw = PIL.ImageDraw.Draw(img)
                        if draw.multiline_textsize(text, font=font)[0] > round(
                            d["width"]
                        ):
                            words = text.split(" ")
                            text = ""
                            for i in range(len(words)):
                                if draw.multiline_textsize(
                                    text + " " + words[i], font=font
                                )[0] <= round(d["width"]):
                                    text += " " + words[i]
                                else:
                                    text += "\n" + words[i]
                        draw.multiline_text(
                            (0, 0), text, (255, 255, 255), spacing=0, font=font
                        )
                        img.save(os.path.join(tempdir, "text_" + d["_id"] + ".png"))
                    tile = ET.SubElement(mapentry, "tile")
                    ET.SubElement(tile, "x").text = str(
                        round(
                            (d["x"] - map["offsetX"] + (d["width"] / 2))
                            * map["rescale"]
                        )
                    )
                    ET.SubElement(tile, "y").text = str(
                        round(
                            (d["y"] - map["offsetY"] + (d["height"] / 2))
                            * map["rescale"]
                        )
                    )
                    ET.SubElement(tile, "zIndex").text = str(d["z"])
                    ET.SubElement(tile, "width").text = str(
                        round(d["width"] * map["rescale"])
                    )
                    ET.SubElement(tile, "height").text = str(
                        round(d["height"] * map["rescale"])
                    )
                    ET.SubElement(tile, "opacity").text = "1.0"
                    ET.SubElement(tile, "rotation").text = str(d["rotation"])
                    ET.SubElement(tile, "locked").text = "YES" if d["locked"] else "NO"
                    ET.SubElement(tile, "layer").text = "object"
                    ET.SubElement(tile, "hidden").text = "YES" if d["hidden"] else "NO"
                    asset = ET.SubElement(tile, "asset")
                    ET.SubElement(asset, "name").text = d["text"]
                    ET.SubElement(asset, "type").text = "image"
                    ET.SubElement(asset, "resource").text = "text_" + d["_id"] + ".png"

                elif d["type"] == "p":
                    drawing = ET.SubElement(
                        mapentry, "drawing", {"id": str(uuid.uuid5(moduuid, d["_id"]))}
                    )
                    ET.SubElement(drawing, "layer").text = (
                        "dm" if d["hidden"] else "map"
                    )
                    ET.SubElement(drawing, "strokeWidth").text = str(d["strokeWidth"])
                    ET.SubElement(drawing, "strokeColor").text = d["strokeColor"]
                    ET.SubElement(drawing, "opacity").text = str(d["strokeAlpha"])
                    ET.SubElement(drawing, "fillColor").text = d["fillColor"]

                    points = []
                    for p in d["points"]:
                        points.append(
                            str((p[0] - map["offsetX"] + d["x"]) * map["rescale"])
                        )
                        points.append(
                            str((p[1] - map["offsetY"] + d["y"]) * map["rescale"])
                        )
                    ET.SubElement(drawing, "data").text = ",".join(points)
        if args.jrnmap:
            for j in sorted(journal, key=lambda j: j["name"] if "name" in j else ""):
                if j["name"].startswith(map["name"]):
                    marker = ET.SubElement(mapentry, "marker")
                    ET.SubElement(marker, "name").text = ""
                    ET.SubElement(marker, "label").text = "📖"
                    ET.SubElement(marker, "shape").text = "circle"
                    ET.SubElement(marker, "x").text = str(round(map["grid"]))
                    ET.SubElement(marker, "y").text = str(round(map["grid"]))
                    ET.SubElement(marker, "hidden").text = "YES"
                    ET.SubElement(
                        marker,
                        "content",
                        {"ref": "/page/{}".format(str(uuid.uuid5(moduuid, j["_id"])))},
                    )
                    break
        elif "journal" in map and map["journal"]:
            marker = ET.SubElement(mapentry, "marker")
            ET.SubElement(marker, "name").text = ""
            ET.SubElement(marker, "label").text = "📖"
            ET.SubElement(marker, "shape").text = "circle"
            ET.SubElement(marker, "x").text = str(round(map["grid"]))
            ET.SubElement(marker, "y").text = str(round(map["grid"]))
            ET.SubElement(marker, "hidden").text = "YES"
            ET.SubElement(
                marker,
                "content",
                {"ref": "/page/{}".format(str(uuid.uuid5(moduuid, map["journal"])))},
            )
        if "notes" in map and len(map["notes"]) > 0:
            for n in map["notes"]:
                marker = ET.SubElement(mapentry, "marker")
                ET.SubElement(marker, "name").text = next(
                    (
                        j["name"]
                        for (i, j) in enumerate(journal)
                        if "name" in j and j["_id"] == n["entryId"]
                    ),
                    None,
                )
                ET.SubElement(marker, "label").text = "📖"
                ET.SubElement(marker, "shape").text = "circle"
                ET.SubElement(marker, "x").text = str(
                    round((n["x"] - map["offsetX"]) * map["rescale"])
                )
                ET.SubElement(marker, "y").text = str(
                    round((n["y"] - map["offsetY"]) * map["rescale"])
                )
                ET.SubElement(marker, "hidden").text = "YES"
                ET.SubElement(
                    marker,
                    "content",
                    {"ref": "/page/{}".format(str(uuid.uuid5(moduuid, n["entryId"])))},
                )
        if "sounds" in map and len(map["sounds"]) > 0:
            for s in map["sounds"]:
                marker = ET.SubElement(mapentry, "marker")
                ET.SubElement(
                    marker, "name"
                ).text = (
                    ""  # "Sound: " + os.path.splitext(os.path.basename(s["path"]))[0]
                )
                ET.SubElement(marker, "label").text = "🔊"
                ET.SubElement(marker, "shape").text = "circle"
                ET.SubElement(marker, "x").text = str(
                    round((s["x"] - map["offsetX"]) * map["rescale"])
                )
                ET.SubElement(marker, "y").text = str(
                    round((s["y"] - map["offsetY"]) * map["rescale"])
                )
                ET.SubElement(marker, "hidden").text = "YES"
                ET.SubElement(
                    marker,
                    "content",
                    {
                        "ref": "/page/{}".format(
                            str(uuid.uuid5(moduuid, map["_id"] + s["_id"]))
                        )
                    },
                )
                page = ET.SubElement(
                    module,
                    "page",
                    {
                        "id": str(uuid.uuid5(moduuid, map["_id"] + s["_id"])),
                        "parent": str(uuid.uuid5(moduuid, map["_id"])),
                    },
                )
                ET.SubElement(page, "name").text = (
                    map["name"]
                    + " Sound: "
                    + os.path.splitext(os.path.basename(s["path"]))[0]
                )
                ET.SubElement(page, "slug").text = slugify(
                    map["name"]
                    + " Sound: "
                    + os.path.splitext(os.path.basename(s["path"]))[0]
                )
                content = ET.SubElement(page, "content")
                content.text = "<h1>Sound: {}</h1>".format(
                    s["name"]
                    if "name" in s
                    else os.path.splitext(os.path.basename(s["path"]))[0]
                )
                content.text += "<figure id={}>".format(s["_id"])
                content.text += "<figcaption>{}</figcaption>".format(
                    s["name"]
                    if "name" in s
                    else os.path.splitext(os.path.basename(s["path"]))[0]
                )
                if not os.path.exists(s["path"]) and os.path.exists(
                    os.path.splitext(s["path"])[0] + ".mp4"
                ):
                    s["path"] = os.path.splitext(s["path"])[0] + ".mp4"
                if os.path.exists(s["path"]):
                    if magic.from_file(
                        os.path.join(tempdir, urllib.parse.unquote(s["path"])),
                        mime=True,
                    ) not in [
                        "audio/mp3",
                        "audio/mpeg",
                        "audio/wav",
                        "audio/mp4",
                        "video/mp4",
                    ]:
                        try:
                            ffp = subprocess.Popen(
                                [
                                    ffmpeg_path,
                                    "-v",
                                    "error",
                                    "-i",
                                    s["path"],
                                    "-acodec",
                                    "aac",
                                    os.path.splitext(s["path"])[0] + ".mp4",
                                ],
                                startupinfo=startupinfo,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL,
                            )
                            ffp.wait()
                            os.remove(s["path"])
                            s["path"] = os.path.splitext(s["path"])[0] + ".mp4"
                        except Exception:
                            print("Could not convert to MP4")
                    try:
                        content.text += '<audio controls {}><source src="{}" type="{}"></audio>'.format(
                            " loop" if s["repeat"] else "",
                            s["path"],
                            magic.from_file(
                                os.path.join(tempdir, urllib.parse.unquote(s["path"])),
                                mime=True,
                            ),
                        )
                    except:
                        content.text += (
                            '<audio controls {}><source src="{}"></audio>'.format(
                                " loop" if s["repeat"] else "", s["path"]
                            )
                        )
                else:
                    content.text += (
                        '<audio controls {}><source src="{}"></audio>'.format(
                            " loop" if s["repeat"] else "", s["path"]
                        )
                    )
                content.text += "</figure>"

        return mapslug

    global tempdir
    if not tempdir:
        tempdir = tempfile.mkdtemp(prefix="convertfoundry_")
    nsuuid = uuid.UUID("ee9acc6e-b94a-472a-b44d-84dc9ca11b87")
    if args.srcfile.startswith("http"):
        urllib.request.urlretrieve(args.srcfile, os.path.join(tempdir, "manifest.json"))
        with open(os.path.join(tempdir, "manifest.json")) as f:
            manifest = json.load(f)
        if "download" in manifest:

            def progress(block_num, block_size, total_size):
                pct = "{:.2f}%".format(100.00 * ((block_num * block_size) / total_size)) if total_size > 0 else "{:.2f} mB".format((block_num*block_size)/1024.00/1024.00)
                print(
                    "\rDownloading module {}".format(pct), file=sys.stderr, end=""
                )

            urllib.request.urlretrieve(
                manifest["download"], os.path.join(tempdir, "module.zip"), progress
            )
            print("\r", file=sys.stderr, end="")
            args.srcfile = os.path.join(tempdir, "module.zip")

    with zipfile.ZipFile(args.srcfile) as z:
        dirpath = ""
        journal = []
        maps = []
        folders = []
        actors = []
        items = []
        tables = []
        playlists = []
        mod = None
        isworld = False
        for filename in z.namelist():
            if os.path.basename(filename) == "world.json":
                dirpath = os.path.dirname(filename)
                with z.open(filename) as f:
                    mod = json.load(f)
                isworld = True
            elif not mod and os.path.basename(filename) == "module.json":
                dirpath = os.path.dirname(filename)
                with z.open(filename) as f:
                    mod = json.load(f)
            elif (
                os.path.basename(os.path.dirname(filename)) == "data"
                and os.path.basename(filename) == "folders.db"
            ):
                with z.open(filename) as f:
                    l = f.readline().decode("utf8")
                    while l:
                        folder = json.loads(l)
                        folders.append(folder)
                        l = f.readline().decode("utf8")
                    f.close()
            elif (
                os.path.basename(os.path.dirname(filename)) == "data"
                and os.path.basename(filename) == "journal.db"
            ):
                with z.open(filename) as f:
                    l = f.readline().decode("utf8")
                    while l:
                        jrn = json.loads(l)
                        journal.append(jrn)
                        l = f.readline().decode("utf8")
                    f.close()
            elif (
                os.path.basename(os.path.dirname(filename)) == "data"
                and os.path.basename(filename) == "scenes.db"
            ):
                with z.open(filename) as f:
                    l = f.readline().decode("utf8")
                    while l:
                        scene = json.loads(l)
                        maps.append(scene)
                        l = f.readline().decode("utf8")
                    f.close()
            elif (
                os.path.basename(os.path.dirname(filename)) == "data"
                and os.path.basename(filename) == "actors.db"
            ):
                with z.open(filename) as f:
                    l = f.readline().decode("utf8")
                    while l:
                        actor = json.loads(l)
                        actors.append(actor)
                        l = f.readline().decode("utf8")
                    f.close()
            elif (
                os.path.basename(os.path.dirname(filename)) == "data"
                and os.path.basename(filename) == "items.db"
            ):
                with z.open(filename) as f:
                    l = f.readline().decode("utf8")
                    while l:
                        item = json.loads(l)
                        items.append(item)
                        l = f.readline().decode("utf8")
                    f.close()
            elif (
                os.path.basename(os.path.dirname(filename)) == "data"
                and os.path.basename(filename) == "tables.db"
            ):
                with z.open(filename) as f:
                    l = f.readline().decode("utf8")
                    while l:
                        table = json.loads(l)
                        tables.append(table)
                        l = f.readline().decode("utf8")
                    f.close()
            elif (
                os.path.basename(os.path.dirname(filename)) == "data"
                and os.path.basename(filename) == "playlists.db"
            ):
                with z.open(filename) as f:
                    l = f.readline().decode("utf8")
                    while l:
                        playlist = json.loads(l)
                        playlists.append(playlist)
                        l = f.readline().decode("utf8")
                    f.close()
        if not isworld and mod:
            if "EncounterPackDir" in mod:
                args.packdir = mod["EncounterPackDir"]
            if "packs" not in mod:
                mod["packs"] = []
            for pack in mod["packs"]:
                if args.system and "system" in pack and pack["system"] != args.system:
                    print("Skipping", pack["name"], pack["system"], "!=", args.system)
                    continue
                pack["path"] = (
                    pack["path"][1:] if os.path.isabs(pack["path"]) else pack["path"]
                )
                if any(x.startswith("{}/".format(mod["name"])) for x in z.namelist()):
                    pack["path"] = mod["name"] + "/" + pack["path"]
                if dirpath and not pack["path"].startswith("{}/".format(dirpath)) and any(x.startswith("{}/".format(dirpath)) for x in z.namelist()):
                    pack["path"] = dirpath + "/" + pack["path"]
                if pack["path"].startswith("./") and dirpath:
                    pack["path"] = dirpath + pack["path"][1:]
                elif pack["path"].startswith("./"):
                    pack["path"] = pack["path"][2:]
                try:
                    with z.open(pack["path"]) as f:
                        l = f.readline().decode("utf8")
                        while l:
                            if pack["entity"] == "JournalEntry":
                                jrn = json.loads(l)
                                journal.append(jrn)
                            elif pack["entity"] == "Scene":
                                scene = json.loads(l)
                                maps.append(scene)
                            elif pack["entity"] == "Actor":
                                actor = json.loads(l)
                                actors.append(actor)
                            elif pack["entity"] == "Item":
                                item = json.loads(l)
                                items.append(item)
                            elif pack["entity"] == "Playlist":
                                playlist = json.loads(l)
                                playlists.append(playlist)
                            l = f.readline().decode("utf8")
                        f.close()
                except Exception as e:
                    print("Could not open",pack["path"],e)
        if not mod and args.packdir:
            mod = {
                "title": os.path.splitext(os.path.basename(args.srcfile))[0].title(),
                "name": slugify(os.path.splitext(os.path.basename(args.srcfile))[0]),
                "version": 1,
                "description": "",
            }
        elif not mod:
            print("No foundry data was found in this zip file.")
            return
        if args.packdir and args.packname:
            mod["name"] += " "+os.path.basename(args.packdir)
            mod["title"] += " "+os.path.basename(args.packdir)
        print(mod["title"])
        global moduuid
        if isworld:
            moduletmp = os.path.join(tempdir, "worlds")
        else:
            moduletmp = os.path.join(tempdir, "modules")
        os.mkdir(moduletmp)
        if not any(x.startswith("{}/".format(mod["name"])) for x in z.namelist()):
            if dirpath:
                z.extractall(path=moduletmp)
                os.rename(os.path.join(moduletmp,dirpath),os.path.join(moduletmp,mod["name"]))
            else:
                os.mkdir(os.path.join(moduletmp, mod["name"]))
                z.extractall(path=os.path.join(moduletmp, mod["name"]))
        else:
            z.extractall(path=moduletmp)
    if os.path.exists(os.path.join(tempdir, "module.zip")):
        os.remove(os.path.join(tempdir, "module.zip"))
        os.remove(os.path.join(tempdir, "manifest.json"))
    moduuid = uuid.uuid5(nsuuid, mod["name"])
    slugs = []
    if args.packdir:
        if not args.packdir.startswith("{}/".format(mod["name"])):
            args.packdir = os.path.join(mod["name"], args.packdir)
        args.packdir = os.path.join(moduletmp, args.packdir)
        module = ET.Element(
            "pack", {"id": str(moduuid), "version": "{}".format(mod["version"])}
        )
    else:
        module = ET.Element(
            "module", {"id": str(moduuid), "version": "{}".format(mod["version"])}
        )
    name = ET.SubElement(module, "name")
    name.text = mod["title"]
    author = ET.SubElement(module, "author")
    if "author" not in mod:
        mod["author"] = ""
    author.text = mod["author"]
    if type(mod["author"]) == list:
        author.text = ", ".join(mod["author"])
    category = ET.SubElement(module, "category")
    if args.packdir:
        category.text = "personal"
    else:
        category.text = "adventure"
    code = ET.SubElement(module, "code")
    code.text = mod["name"]
    slug = ET.SubElement(module, "slug")
    slug.text = slugify(mod["title"])
    description = ET.SubElement(module, "description")
    description.text = re.sub(r"<.*?>", "", html.unescape(mod["description"]))
    modimage = ET.SubElement(module, "image")
    order = 0
    cwd = os.getcwd()
    os.chdir(tempdir)
    maxorder = 0
    sort = 0
    if args.packdir:
        journal.clear()
        maps.clear()
        folders.clear()
        actors.clear()
        items.clear()
        tables.clear()
        playlists.clear()
        packdir = os.path.join(tempdir, "packdir")
        os.mkdir(packdir)
        packroot = [
            folder
            for folder in os.listdir(args.packdir)
            if os.path.isdir(os.path.join(args.packdir, folder))
        ]
        packroot.append(".")
        pos = 0.00
        if sys.platform == "win32":
            args.packdir = args.packdir.replace("/", "\\")
        for root, dirs, files in os.walk(args.packdir):
            if args.gui:
                worker.updateProgress((pos / len(packroot)) * 70)
            groupname = os.path.relpath(root, start=args.packdir)
            if groupname != ".":
                if args.gui:
                    worker.outputLog("Creating group " + groupname.title())
                splitpath = []
                path = groupname
                while True:
                    parts = os.path.split(path)
                    if parts[0] == path:
                        splitpath.insert(0, parts[0])
                        break
                    elif parts[1] == path:
                        splitpath.insert(0, parts[1])
                        break
                    else:
                        path = parts[0]
                        splitpath.insert(0, parts[1])
                parent = None
                dirid = None
                for i, subdir in enumerate(splitpath):
                    if not subdir:
                        continue
                    if dirid:
                        parent = dirid
                    dirid = str(
                        uuid.uuid5(moduuid, slugify("/".join(splitpath[: i + 1])))
                    )
                    gInUse = False
                    for g in module.iter("group"):
                        if dirid == g.get("id"):
                            gInUse = True
                    if not gInUse:
                        sort += 1
                        group = ET.SubElement(
                            module, "group", {"id": dirid, "sort": str(int(sort))}
                        )
                        if parent:
                            group.set("parent", parent)
                        ET.SubElement(group, "name").text = subdir.title()
                        ET.SubElement(group, "slug").text = slugify(subdir)
                groupid = str(uuid.uuid5(moduuid, slugify(groupname)))
            else:
                groupid = None
            for f in files:
                pos += 1.00 / len(files)
                image = os.path.join(root, f)
                if not re.match(
                    r"(image/.*?|video/webm)", magic.from_file(image, mime=True)
                ):
                    print("\r - Skipping", f, file=sys.stderr, end="")
                    sys.stderr.write("\033[K")
                    sys.stderr.flush()
                    continue
                print("\r Adding", f, file=sys.stderr, end="")
                sys.stderr.write("\033[K")
                sys.stderr.flush()
                if args.gui:
                    worker.outputLog(" adding " + f)
                    worker.updateProgress((pos / len(packroot)) * 70)
                if groupid:
                    asset = ET.SubElement(
                        module,
                        "asset",
                        {
                            "id": str(
                                uuid.uuid5(
                                    moduuid, os.path.relpath(image, start=tempdir)
                                )
                            ),
                            "parent": groupid,
                        },
                    )
                else:
                    asset = ET.SubElement(
                        module,
                        "asset",
                        {
                            "id": str(
                                uuid.uuid5(
                                    moduuid, os.path.relpath(image, start=tempdir)
                                )
                            )
                        },
                    )
                ET.SubElement(asset, "name").text = os.path.splitext(
                    os.path.basename(image)
                )[0]
                tags = re.search(
                    r"(.*)_(?:tiny|small|medium|large|huge)(?:plus)?_.*",
                    os.path.splitext(os.path.basename(image))[0],
                    re.I,
                )
                if tags:
                    ET.SubElement(asset, "tags").text = (
                        tags.group(1).replace("_", " ").strip()
                    )
                else:
                    tags = re.search(
                        r"(?:VAM)?((.*?)(?:[0-9]+)|(.*))",
                        os.path.splitext(os.path.basename(image))[0],
                        re.I,
                    )
                    if tags:
                        tag = tags.group(3) or tags.group(2)
                        ET.SubElement(asset, "tags").text = tag.replace(
                            "_", " "
                        ).strip()
                imgext = os.path.splitext(os.path.basename(image))[1]
                if imgext == ".webm":
                    try:
                        if os.path.exists(image):
                            if args.gui:
                                worker.outputLog(
                                    " - Converting webm tile to animated webp"
                                )
                            probe = ffprobe(image)
                            duration = int(probe["nb_read_frames"])
                            if probe["codec_name"] != "vp9":
                                ffp = subprocess.Popen(
                                    [
                                        ffmpeg_path,
                                        "-v",
                                        "error",
                                        "-vcodec",
                                        "libvpx",
                                        "-progress",
                                        "ffmpeg.log",
                                        "-i",
                                        image,
                                        "-loop",
                                        "0",
                                        image + ".webp",
                                    ],
                                    startupinfo=startupinfo,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL,
                                )
                            else:
                                ffp = subprocess.Popen(
                                    [
                                        ffmpeg_path,
                                        "-v",
                                        "error",
                                        "-vcodec",
                                        "libvpx-vp9",
                                        "-progress",
                                        "ffmpeg.log",
                                        "-i",
                                        image,
                                        "-loop",
                                        "0",
                                        image + ".webp",
                                    ],
                                    startupinfo=startupinfo,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL,
                                )

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
                                                    " webm->webp:    ",
                                                    file=sys.stderr,
                                                    end="",
                                                )
                                                logged = True
                                            elif pct >= 100:
                                                print("\b", file=sys.stderr, end="")
                                            pos = round(float(val) * 100, 2)
                                            pct = round(pos / duration)
                                            print(
                                                "\b\b\b{:02d}%".format(pct),
                                                file=sys.stderr,
                                                end="",
                                            )
                                            if args.gui:
                                                worker.updateProgress(pct)
                                            sys.stderr.flush()
                            os.remove("ffmpeg.log")
                        if os.path.exists(image + ".webp"):
                            ET.SubElement(asset, "type").text = "animatedImage"
                            image = image + ".webp"
                            if os.path.exists(
                                os.path.join(packdir, os.path.basename(image).lower())
                            ):
                                exist_count = 1
                                image_name, image_ext = os.path.splitext(image)
                                while os.path.exists(
                                    os.path.join(
                                        packdir,
                                        os.path.basename(
                                            "{}{}{}".format(
                                                image_name, exist_count, image_ext
                                            )
                                        ).lower(),
                                    )
                                ):
                                    exist_count += 1
                                newimage = "{}{}{}".format(
                                    image_name, exist_count, image_ext
                                ).lower()
                            else:
                                newimage = image.lower()
                            shutil.copy(
                                image, os.path.join(packdir, os.path.basename(newimage))
                            )
                            size = re.search(
                                r"(([0-9]+) ?ft|([0-9]+)[xX]([0-9]+)(?:x([0-9\.]+))?|(tiny|small|medium|large|huge)(x[0-9\.]+)?)", os.path.splitext(os.path.basename(newimage))[0].lower()
                            )
                            if size:
                                h = 1
                                w = 1
                                if size.group(2):
                                    w = max(int(int(size.group(2))/5),1)
                                elif size.group(3) and size.group(4):
                                    w = int(size.group(3))
                                    h = int(size.group(4))
                                    if size.group(5):
                                        ET.SubElement(asset, "scale").text = str(size.group(5))
                                elif size.group(6):
                                    if size.group(5) == "large":
                                        w = 2
                                        h = 2
                                    elif size.group(5) == "huge":
                                        w = 3
                                        h = 3
                                    if size.group(7):
                                        ET.SubElement(asset, "scale").text = str(size.group(7)) 
                                with PIL.Image.open(os.path.join(packdir, os.path.basename(newimage))) as img:
                                    if img.width == w and img.height == h:
                                        w = max(int(w/100),1)
                                        h = max(int(h/100),1)
                                ET.SubElement(asset, "size").text = "{}x{}".format(w,h)
                            ET.SubElement(asset, "resource").text = os.path.basename(
                                newimage
                            )
                        continue
                    except Exception:
                        import traceback

                        print(traceback.format_exc())
                        if args.gui:
                            worker.outputLog(
                                " - webm tiles are not supported, consider converting to an animated image or a spritesheet: "
                                + image
                            )
                        print(
                            " - webm tiles are not supported, consider converting to an animated image or a spritesheet:",
                            image,
                            file=sys.stderr,
                            end="",
                        )
                    continue
                with PIL.Image.open(image) as img:
                    if getattr(img, "is_animated", False):
                        ET.SubElement(asset, "type").text = "animatedImage"
                    else:
                        ET.SubElement(asset, "type").text = "image"
                    size = re.search(
                        r"(([0-9]+) ?ft|([0-9]+)[xX]([0-9]+)(?:x([0-9.]+))?|(tiny|small|medium|large|huge)(x[0-9.]+)?)", os.path.splitext(os.path.basename(image))[0].lower()
                    )
                    if size:
                        h = 1
                        w = 1
                        if size.group(2):
                            w = max(int(int(size.group(2))/5),1)
                        elif size.group(3) and size.group(4):
                            w = int(size.group(3))
                            h = int(size.group(4))
                            if size.group(5):
                                ET.SubElement(asset, "scale").text = str(size.group(5))
                        if img.width == w and img.height == h:
                            w = max(int(w/100),1)
                            h = max(int(h/100),1)
                        elif size.group(6):
                            if size.group(6) == "large":
                                w = 2
                                h = 2
                            elif size.group(6) == "huge":
                                w = 3
                                h = 3
                            if size.group(7):
                                ET.SubElement(asset, "scale").text = str(size.group(7)) 
                        ET.SubElement(asset, "size").text = "{}x{}".format(w,h)
                    if imgext == ".webp" and args.jpeg != ".webp":
                        if img.width > 4096 or img.height > 4096:
                            scale = (
                                4095 / img.width
                                if img.width >= img.height
                                else 4095 / img.height
                            )
                            img = img.resize(
                                (round(img.width * scale), round(img.height * scale))
                            )
                        if args.gui:
                            worker.outputLog(" - Converting tile from webp to png")
                        img.save(
                            os.path.join(tempdir, os.path.splitext(image)[0] + ".png")
                        )
                        os.remove(image)
                        image = os.path.join(
                            tempdir, os.path.splitext(image)[0] + ".png"
                        )
                    else:
                        if img.width > 4096 or img.height > 4096:
                            scale = (
                                4095 / img.width
                                if img.width >= img.height
                                else 4095 / img.height
                            )
                            img = img.resize(
                                (round(img.width * scale), round(img.height * scale))
                            )
                            img.save(os.path.join(tempdir, image))
                if os.path.exists(
                    os.path.join(packdir, os.path.basename(image).lower())
                ):
                    exist_count = 1
                    image_name, image_ext = os.path.splitext(image)
                    while os.path.exists(
                        os.path.join(
                            packdir,
                            os.path.basename(
                                "{}{}{}".format(image_name, exist_count, image_ext)
                            ).lower(),
                        )
                    ):
                        exist_count += 1
                    newimage = "{}{}{}".format(
                        image_name, exist_count, image_ext
                    ).lower()
                else:
                    newimage = image.lower()
                shutil.copy(image, os.path.join(packdir, os.path.basename(newimage)))
                ET.SubElement(asset, "resource").text = os.path.basename(newimage)
                if not modimage.text and "preview" in f.lower():
                    modimage.text = os.path.basename(newimage)
    actors = list(
        filter(
            lambda actor: actor["_id"]
            not in [a["_id"] for a in actors if "$$deleted" in a and a["$$deleted"]],
            actors,
        )
    )
    items = list(
        filter(
            lambda item: item["_id"]
            not in [a["_id"] for a in items if "$$deleted" in a and a["$$deleted"]],
            items,
        )
    )
    folders = list(
        filter(
            lambda folder: folder["_id"]
            not in [a["_id"] for a in folders if "$$deleted" in a and a["$$deleted"]],
            folders,
        )
    )
    journal = [] if args.noj else list(
        filter(
            lambda j: j["_id"]
            not in [a["_id"] for a in journal if "$$deleted" in a and a["$$deleted"]],
            journal,
        )
    )
    maps = list(
        filter(
            lambda map: map["_id"]
            not in [a["_id"] for a in maps if "$$deleted" in a and a["$$deleted"]],
            maps,
        )
    )
    playlists = list(
        filter(
            lambda playlist: playlist["_id"]
            not in [a["_id"] for a in playlists if "$$deleted" in a and a["$$deleted"]],
            playlists,
        )
    )
    tables = list(
        filter(
            lambda table: table["_id"]
            not in [a["_id"] for a in tables if "$$deleted" in a and a["$$deleted"]],
            tables,
        )
    )
    sort = 1
    for f in sorted(folders, key=lambda f: f["name"] if "name" in f else ""):
        f["sort"] = sort if "sort" not in f or not f["sort"] else f["sort"]
        if f["sort"] > maxorder:
            maxorder = f["sort"]
        sort += 1
    sort = 1
    for j in sorted(journal, key=lambda j: j["name"] if "name" in j else ""):
        j["sort"] = sort if "sort" not in j or not j["sort"] else j["sort"]
        if (
            "flags" in j
            and "R20Converter" in j["flags"]
            and "handout-order" in j["flags"]["R20Converter"]
        ):
            j["sort"] += j["flags"]["R20Converter"]["handout-order"]
        if j["sort"] > maxorder:
            maxorder = j["sort"]
        sort += 1
    sort = 1
    for m in sorted(maps, key=lambda m: m["name"] if "name" in m else ""):
        m["sort"] = sort if "sort" not in m or not m["sort"] else m["sort"]
        if m["sort"] and m["sort"] > maxorder:
            maxorder = m["sort"]
        sort += 1

    def fixLink(m):
        if m.group(2) == "JournalEntry":
            return '<a href="/page/{}" {} {} {}>'.format(
                str(uuid.uuid5(moduuid, m.group(4))),
                m.group(1),
                m.group(3),
                m.group(5),
            )
        if m.group(2) == "Actor":
            for a in actors:
                if a["_id"] == m.group(4):
                    return '<a href="/monster/{}" {} {} {}>'.format(
                        slugify(a["name"]), m.group(1), m.group(3), m.group(5)
                    )
        return m.group(0)

    def fixFTag(m):
        if m.group(1) == "JournalEntry":
            for j in journal:
                if j["_id"] == m.group(2) or j["name"] == m.group(2):
                    return '<a href="/page/{}">{}</a>'.format(
                        str(uuid.uuid5(moduuid, j["_id"])), m.group(3) or j["name"]
                    )
            return '<a href="/page/{}">{}</a>'.format(
                str(uuid.uuid5(moduuid, m.group(2))), m.group(3) or "Journal Entry"
            )
        if m.group(1) == "RollTable":
            return '<a href="/page/{}">{}</a>'.format(
                str(uuid.uuid5(moduuid, m.group(2))), m.group(3) or "Roll Table"
            )
        if m.group(1) == "Scene":
            for map in maps:
                if map["_id"] == m.group(2) or map["name"] == m.group(2):
                    return '<a href="/map/{}">{}</a>'.format(
                        str(uuid.uuid5(moduuid, map["_id"])), m.group(3) or map["name"]
                    )
            return '<a href="/map/{}">{}</a>'.format(
                str(uuid.uuid5(moduuid, m.group(2))), m.group(3) or "Map"
            )
        if m.group(1) == "Actor":
            for a in actors:
                if a["_id"] == m.group(2) or a["name"] == m.group(2):
                    return '<a href="/monster/{}">{}</a>'.format(
                        uuid.uuid5(moduuid, a["_id"])
                        if args.compendium
                        else slugify(a["name"]),
                        m.group(3) or a["name"],
                        m.group(3),
                    )
        if m.group(1) == "Compendium" and m.group(3):
            (system, entrytype, idnum) = m.group(2).split(".", 2)
            if args.compendium:
                slug = uuid.uuid5(moduuid, idnum)
            else:
                slug = slugify(m.group(3))
            entrytype = entrytype.lower().replace("actor", "monster").rstrip("s")
            if "packs" in mod:
                for p in mod["packs"]:
                    if p["name"] == entrytype and p["entity"] == "Actor":
                        entrytype = "monster"
                    elif p["name"] == entrytype and p["entity"] == "Item":
                        entrytype = "item"
                        for i in items:
                            if i["_id"] == idnum and i["type"].lower() == "spell":
                                entrytype = "spell"

            return '<a href="/{}/{}">{}</a>'.format(entrytype, slug, m.group(3))
        if m.group(1) == "Item":
            for i in items:
                if i["_id"] == m.group(2) or i["name"] == m.group(2):
                    return '<a href="/item/{}">{}</a>'.format(
                        uuid.uuid5(moduuid, i["_id"])
                        if args.compendium
                        else slugify(i["name"]),
                        m.group(3) or i["name"],
                    )
        if m.group(1) == "Macro":
            if m.group(3):
                return "<details><summary>{}</summary>This was a Foundry Macro, which cannot be converted.</details>".format(
                    m.group(3)
                )
            else:
                return "<details><summary>Unsupported</summary>This was a Foundry Macro, which cannot be converted.</details>"
        return m.group(0)

    if args.gui and len(folders) > 0:
        worker.outputLog("Converting folders")
    for f in folders:
        order += 1
        if args.gui:
            worker.updateProgress((order / len(folders)) * 5)
        print(
            "\rCreating Folders [{}/{}] {:.0f}%".format(
                order, len(folders), order / len(folders) * 100
            ),
            file=sys.stderr,
            end="",
        )
        if f["type"] not in ["JournalEntry", "RollTable", "Scene"]:
            continue
        folder = ET.SubElement(
            module,
            "group",
            {"id": str(uuid.uuid5(moduuid, f["_id"])), "sort": str(int(f["sort"]))},
        )
        ET.SubElement(folder, "name").text = f["name"]
        if f["parent"] is not None:
            folder.set("parent", str(uuid.uuid5(moduuid, f["parent"])))
    order = 0
    if len(journal) > 0 and args.gui:
        worker.outputLog("Converting journal")
    for j in journal:
        order += 1
        if args.gui:
            worker.updateProgress(5 + (order / len(journal)) * 10)
        if "$$deleted" in j and j["$$deleted"]:
            continue
        if not j["content"] and ("img" not in j or not j["img"]):
            continue
        print(
            "\rConverting journal [{}/{}] {:.0f}%".format(
                order, len(journal), order / len(journal) * 100
            ),
            file=sys.stderr,
            end="",
        )
        page = ET.SubElement(
            module,
            "page",
            {"id": str(uuid.uuid5(moduuid, j["_id"])), "sort": str(j["sort"] or order)},
        )
        if "folder" in j and j["folder"] is not None:
            page.set("parent", str(uuid.uuid5(moduuid, j["folder"])))
        ET.SubElement(page, "name").text = j["name"]
        ET.SubElement(page, "slug").text = slugify(j["name"])
        content = ET.SubElement(page, "content")
        content.text = j["content"] or ""
        content.text = re.sub(
            r'<a(.*?)data-entity="?(.*?)"? (.*?)data-id="?(.*?)"?( .*?)?>',
            fixLink,
            content.text,
        )
        content.text = re.sub(r"@(.*?)\[(.*?)\](?:\{(.*?)\})?", fixFTag, content.text)
        content.text = re.sub(
            r"\[\[(?:/(?:gm)?r(?:oll)? )?(.*?)(?: ?# ?(.*?))?\]\]",
            fixRoll,
            content.text,
        )
        if "img" in j and j["img"]:
            content.text += '<img src="{}">'.format(j["img"])
    order = 0
    maxorder = len(folders) + len(journal) if not maxorder else maxorder
    if len(playlists) > 0:
        if args.gui:
            worker.outputLog("Converting playlists")
        playlistsbaseslug = "playlists"
        playlistsslug = playlistsbaseslug + str(
            len([i for i in slugs if playlistsbaseslug in i])
        )
        playlistsgroup = str(uuid.uuid5(moduuid, playlistsslug))
        group = ET.SubElement(
            module, "group", {"id": playlistsgroup, "sort": str(int(maxorder + 1))}
        )
        ET.SubElement(group, "name").text = "Playlists"
        ET.SubElement(group, "slug").text = playlistsslug
    for p in playlists:
        order += 1
        if args.gui:
            worker.updateProgress(15 + (order / len(playlists)) * 10)
        if "$$deleted" in p and p["$$deleted"]:
            continue
        print(
            "\rConverting playlists [{}/{}] {:.0f}%".format(
                order, len(playlists), order / len(playlists) * 100
            ),
            file=sys.stderr,
            end="",
        )
        page = ET.SubElement(
            module,
            "page",
            {
                "id": str(uuid.uuid5(moduuid, p["_id"])),
                "parent": playlistsgroup,
                "sort": str(p["sort"] if "sort" in p and p["sort"] else order),
            },
        )
        ET.SubElement(page, "name").text = p["name"]
        ET.SubElement(page, "slug").text = slugify(p["name"])
        content = ET.SubElement(page, "content")
        content.text = "<h1>{}</h1>".format(p["name"])
        content.text += "<table><thead><tr><td>"
        content.text += "Track"
        content.text += "</td>"
        content.text += "</tr></thead><tbody>"
        for s in p["sounds"]:
            content.text += "<tr>"
            content.text += "<td><figure>"
            content.text += "<figcaption>{}</figcaption>".format(s["name"])
            if not os.path.exists(s["path"]) and os.path.exists(
                os.path.splitext(s["path"])[0] + ".mp4"
            ):
                s["path"] = os.path.splitext(s["path"])[0] + ".mp4"
            if os.path.exists(s["path"]):
                if magic.from_file(
                    os.path.join(tempdir, urllib.parse.unquote(s["path"])), mime=True
                ) not in [
                    "audio/mp3",
                    "audio/mpeg",
                    "audio/wav",
                    "audio/mp4",
                    "video/mp4",
                ]:
                    try:
                        ffp = subprocess.Popen(
                            [
                                ffmpeg_path,
                                "-v",
                                "error",
                                "-i",
                                s["path"],
                                "-acodec",
                                "aac",
                                os.path.splitext(s["path"])[0] + ".mp4",
                            ],
                            startupinfo=startupinfo,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL,
                        )
                        ffp.wait()
                        s["path"] = os.path.splitext(s["path"])[0] + ".mp4"
                    except Exception:
                        print("Could not convert to MP4")
                content.text += (
                    '<audio controls {}><source src="{}" type="{}"></audio>'.format(
                        " loop" if s["repeat"] else "",
                        s["path"],
                        magic.from_file(
                            os.path.join(tempdir, urllib.parse.unquote(s["path"])),
                            mime=True,
                        ),
                    )
                )
            else:
                content.text += '<audio controls {}><source src="{}"></audio>'.format(
                    " loop" if s["repeat"] else "", s["path"]
                )
            content.text += "</figure></td>"
            content.text += "</tr>"
        content.text += "</tbody></table>"
    order = 0
    if len(tables) > 0:
        if args.gui:
            worker.outputLog("Converting roll tables")
        tablesbaseslug = "tables"
        tablesslug = tablesbaseslug + str(
            len([i for i in slugs if tablesbaseslug in i])
        )
        tablesgroup = str(uuid.uuid5(moduuid, tablesslug))
        group = ET.SubElement(
            module, "group", {"id": tablesgroup, "sort": str(int(maxorder + 1))}
        )
        ET.SubElement(group, "name").text = "Roll Tables"
        ET.SubElement(group, "slug").text = tablesslug
    for t in tables:
        order += 1
        if args.gui:
            worker.updateProgress(25 + (order / len(tables)) * 10)
        if "$$deleted" in t and t["$$deleted"]:
            continue
        print(
            "\rConverting tables [{}/{}] {:.0f}%".format(
                order, len(tables), order / len(tables) * 100
            ),
            file=sys.stderr,
            end="",
        )
        page = ET.SubElement(
            module,
            "page",
            {
                "id": str(uuid.uuid5(moduuid, t["_id"])),
                "parent": tablesgroup,
                "sort": str(t["sort"] if "sort" in t and t["sort"] else order),
            },
        )
        if "folder" in t and t["folder"]:
            page.set("parent", str(uuid.uuid5(moduuid, t["folder"])))
        ET.SubElement(page, "name").text = t["name"]
        ET.SubElement(page, "slug").text = slugify(t["name"])
        content = ET.SubElement(page, "content")
        content.text = "<h1>{}</h1>".format(t["name"])
        content.text += "<table><thead><tr><td>"
        content.text += '<a href="/roll/{0}/{1}">{0}</a>'.format(
            t["formula"], t["name"]
        )
        content.text += '</td><td colspan="2" align="center">{}</td>'.format(t["name"])
        content.text += "</tr></thead><tbody>"
        for r in t["results"]:
            content.text += "<tr>"
            content.text += "<td>{}</td>".format(
                "{}-{}".format(*r["range"])
                if r["range"][0] != r["range"][1]
                else r["range"][0]
            )
            content.text += "<td>"
            linkMade = False
            if "collection" in r:
                if r["collection"] == "dnd5e.monsters":
                    content.text += '<a href="/monster/{}">{}</a>'.format(
                        slugify(r["text"]), r["text"]
                    )
                    linkMade = True
                elif r["collection"] == "Actor":
                    for a in actors:
                        if a["_id"] == r["resultId"]:
                            content.text += '<a href="/monster/{}">{}</a>'.format(
                                slugify(a["name"]), r["text"]
                            )
                            linkMade = True
                elif r["collection"] == "Item":
                    for i in items:
                        if i["_id"] == r["resultId"]:
                            content.text += '<a href="/item/{}">{}</a>'.format(
                                slugify(i["name"]), r["text"]
                            )
                            linkMade = True
            if not linkMade:
                content.text += "{}".format(r["text"] if r["text"] else "&nbsp;")
            content.text += "</td>"
            if "img" in r and os.path.exists(r["img"]):
                content.text += (
                    '<td style="width:50px;height:50px;"><img src="{}"></td>'.format(
                        r["img"]
                    )
                )
            else:
                content.text += '<td style="width:50px;height:50px;">&nbsp;</td>'
            content.text += "</tr>"
        content.text += "</tbody></table>"
        content.text = re.sub(
            r"\[\[(?:/(?:gm)?r(?:oll)? )?(.*?)(?: ?# ?(.*?))?\]\]",
            fixRoll,
            content.text,
        )
    if "media" in mod:
        for media in mod["media"]:
            if "url" not in media and "link" in media:
                media["url"] = media["link"]
            if media["type"] == "cover" and media["url"]:

                def progress(block_num, block_size, total_size):
                    pct = 100.00 * ((block_num * block_size) / total_size)
                    print(
                        "\rDownloading cover {:.2f}%".format(pct),
                        file=sys.stderr,
                        end="",
                    )
                if urllib.parse.urlparse(media['url']).scheme:
                    urllib.request.urlretrieve(
                        media["url"],
                        os.path.join(tempdir, os.path.basename(media["url"]).lower()),
                        progress,
                    )
                else:
                    shutil.copy(os.path.join(os.path.join(moduletmp, mod["name"]),os.path.basename(media["url"])),os.path.join(tempdir,os.path.basename(media["url"]).lower()))
                if args.packdir:
                    shutil.copy(os.path.join(tempdir,os.path.basename(media["url"].lower())),os.path.join(packdir,os.path.basename(media["url"]).lower()))
                modimage.text = os.path.basename(media["url"]).lower()
    mapcount = 0
    if len(maps) > 0:
        if args.gui:
            worker.outputLog("Converting maps")
        if any([journal, folders, tables, playlists]) and not any(
            [x["folder"] for x in maps if "folder" in x]
        ):
            mapsbaseslug = "maps"
            mapsslug = mapsbaseslug + str(len([i for i in slugs if mapsbaseslug in i]))
            mapgroup = str(uuid.uuid5(moduuid, mapsslug))
            group = ET.SubElement(
                module, "group", {"id": mapgroup, "sort": str(int(maxorder + 2))}
            )
            ET.SubElement(group, "name").text = "Maps"
            ET.SubElement(group, "slug").text = mapsslug
        else:
            mapgroup = None
        for map in maps:
            if "$$deleted" in map and map["$$deleted"]:
                continue
            if not modimage.text and map["name"].lower() in args.covernames:
                if args.gui:
                    worker.outputLog("Generating cover image")
                print("\rGenerating cover image", file=sys.stderr, end="")
                if not os.path.exists(
                    urllib.parse.unquote(map["img"] or map["tiles"][0]["img"])
                ):
                    if os.path.exists(
                        os.path.splitext(
                            urllib.parse.unquote(map["img"] or map["tiles"][0]["img"])
                        )[0]
                        + args.jpeg
                    ):
                        map["img"] = os.path.splitext(map["img"])[0] + args.jpeg
                with PIL.Image.open(
                    urllib.parse.unquote(map["img"] or map["tiles"][0]["img"])
                ) as img:
                    if img.width <= img.height:
                        img = img.crop((0, 0, img.width, img.width))
                    else:
                        img = img.crop((0, 0, img.height, img.height))
                    if img.width > 1024:
                        img = img.resize((1024, 1024))
                    if args.jpeg == ".jpg" and img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")
                    img.save(os.path.join(tempdir, "module_cover" + args.jpeg))
                modimage.text = "module_cover" + args.jpeg
            if not map["img"] and len(map["tiles"]) == 0:
                continue
            mapcount += 1
            sys.stderr.write("\033[K")
            if args.gui:
                worker.updateProgress(35 + (mapcount / len(maps)) * 35)
            print(
                "\rConverting maps [{}/{}] {:.0f}%".format(
                    mapcount, len(maps), mapcount / len(maps) * 100
                ),
                file=sys.stderr,
                end="",
            )
            createMap(map, mapgroup)
    while True:
        removed = False
        for g in module.iter("group"):
            gInUse = False
            for tag in ["page", "map", "group", "asset"]:
                for p in module.iter(tag):
                    if p.get("parent") == g.get("id"):
                        gInUse = True
                        break
                if gInUse:
                    break
            if gInUse:
                continue
            module.remove(g)
            removed = True
        if not removed:
            break
    if not modimage.text and len(maps) > 0:
        randomok = False
        loopcount = len(maps)*5
        while not randomok:
            loopcount -= 1
            if loopcount < 0: break
            map = random.choice(maps)
            while "$$deleted" in map and mapcount > 0:
                map = random.choice(maps)
            if not os.path.exists(
                urllib.parse.unquote(map["img"] or map["tiles"][0]["img"])
            ):
                if os.path.exists(
                    os.path.splitext(
                        urllib.parse.unquote(map["img"] or map["tiles"][0]["img"])
                    )[0]
                    + args.jpeg
                ):
                    map["img"] = os.path.splitext(map["img"])[0] + args.jpeg
                elif os.path.exists(
                    os.path.splitext(
                        urllib.parse.unquote(map["img"] or map["tiles"][0]["img"])
                    )[0]
                    + ".jpg"
                ):
                    map["img"] = os.path.splitext(map["img"])[0] + ".jpg"
            if os.path.exists(map["img"]):
                randomok = True
        if args.gui:
            worker.outputLog("Generating cover image")
        print("\rGenerating cover image", file=sys.stderr, end="")
        if randomok:
            with PIL.Image.open(map["img"] or map["tiles"][0]["img"]) as img:
                if img.width <= img.height:
                    img = img.crop((0, 0, img.width, img.width))
                else:
                    img = img.crop((0, 0, img.height, img.height))
                if img.width > 1024:
                    img = img.resize((1024, 1024))
                if args.jpeg == ".jpg" and img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                img.save(os.path.join(tempdir, "module_cover" + args.jpeg))
            modimage.text = "module_cover" + args.jpeg
    # write to file
    sys.stderr.write("\033[K")
    if args.gui:
        worker.updateProgress(70)
        if args.packdir:
            worker.outputLog("Generating pack.xml")
        else:
            worker.outputLog("Generating module.xml")
    print("\rWriting XML", file=sys.stderr, end="")
    tree = ET.ElementTree(indent(module, 1))
    tree.write(
        os.path.join(
            packdir if args.packdir else tempdir,
            "pack.xml" if args.packdir else "module.xml",
        ),
        xml_declaration=True,
        short_empty_elements=False,
        encoding="utf-8",
    )
    if "styles" in mod:
        if not os.path.exists(os.path.join(tempdir, "assets")):
            os.mkdir(os.path.join(tempdir, "assets"))
        if not os.path.exists(os.path.join(tempdir, "assets", "css")):
            os.mkdir(os.path.join(tempdir, "assets", "css"))
        for style in mod["styles"]:
            if os.path.exists(os.path.join(moduletmp, mod["name"], style)):
                with open(
                    os.path.join(tempdir, "assets", "css", "custom.css"), "a"
                ) as f:
                    with open(os.path.join(moduletmp, mod["name"], style)) as css:
                        for l in css:
                            f.write(l)
        if os.path.exists(os.path.join(moduletmp, mod["name"], "fonts")):
            os.rename(
                os.path.join(moduletmp, mod["name"], "fonts"),
                os.path.join(tempdir, "assets", "fonts"),
            )
    if args.compendium and (len(items) + len(actors)) > 0:
        if args.gui:
            worker.updateProgress(75)
            worker.outputLog("Generating compendium data")

        def fixHTMLContent(text):
            text = re.sub(
                r'<a(.*?)data-entity="?(.*?)"? (.*?)data-id="?(.*?)"?( .*?)?>',
                fixLink,
                text,
            )
            text = re.sub(r"@(.*?)\[(.*?)\](?:\{(.*?)\})?", fixFTag, text)
            text = re.sub(r"<h([0-9]).*?>(.*?)</h\1>", r"<b>\2</b>\n", text)
            text = re.sub(r"<em.*?>(.*?)</em>", r"<i>\1</i>", text)
            text = re.sub(r"<strong.*?>(.*?)</strong>", r"<b>\1</b>", text)
            text = re.sub(
                r"<blockquote.*?>(.*?)</blockquote>",
                r"-------------\n\1-------------\n",
                text,
            )
            text = re.sub(
                r'<img(.*?)src="?(.*?)"?( .*?)?>', r'<a\1href="\2"\3>Image</a>', text
            )
            text = re.sub(r"<tr.*?><td.*?>(.*?)</td>", r"\1", text)
            text = re.sub(r"<td.*?>(.*?)</td>", r" | \1", text)
            text = re.sub(r"</tr>", "\n", text)
            text = re.sub(r"</?p.*?>", "", text)
            text = re.sub(r"<br.*?>", "\n", text)
            text = re.sub(r"<hr.*?>", "------------------------\n", text)
            text = re.sub(r"<!--.*?-->", "", text)
            text = re.sub(
                r"\[\[(?:/(?:gm)?r(?:oll)? )?(.*?)(?: ?# ?(.*?))?\]\]", fixRoll, text
            )
            text = re.sub(
                r"<section .*?class=.secret..*?>(.*?)</section>.*",
                r"\1",
                text,
                flags=re.S,
            )
            return html.unescape(text.strip())

        compendium = ET.Element("compendium")
        os.mkdir(os.path.join(tempdir, "items"))
        os.mkdir(os.path.join(tempdir, "spells"))
        os.mkdir(os.path.join(tempdir, "monsters"))
        itemnumber = 0
        for i in items:
            itemnumber += 1
            if args.gui:
                worker.updateProgress(
                    75 + (itemnumber / (len(items) + len(actors))) * 10
                )
            print(
                "\rGenerating compendium [{}/{}]".format(
                    itemnumber, len(items) + len(actors)
                ),
                file=sys.stderr,
                end="",
            )
            if i["type"] in ["feat"]:
                continue
            d = i["data"]
            if i["type"] == "spell":
                spell = ET.SubElement(
                    compendium, "spell", {"id": str(uuid.uuid5(moduuid, i["_id"]))}
                )
                ET.SubElement(spell, "name").text = i["name"]
                ET.SubElement(spell, "slug").text = slugify(i["name"])
                ET.SubElement(spell, "level").text = str(d["level"])
                ET.SubElement(spell, "school").text = (
                    schools[d["school"]] if d["school"] in schools else d["school"]
                )
                ET.SubElement(spell, "ritual").text = (
                    "YES" if d["components"]["ritual"] else "NO"
                )
                ET.SubElement(spell, "time").text = "{} {}".format(
                    d["activation"]["cost"], d["activation"]["type"]
                )
                ET.SubElement(spell, "range").text = "{} {}".format(
                    "{}/{}".format(d["range"]["value"], d["range"]["long"])
                    if d["range"]["long"]
                    else d["range"]["value"],
                    d["range"]["units"]
                )
                components = []
                for component in d["components"].keys():
                    if component in ["value", "ritual", "concentration"]:
                        continue
                    elif d["components"][component]:
                        comp = component[0].upper()
                        if (
                            comp == "M"
                            and "value" in d["materials"]
                            and d["materials"]["value"]
                        ):
                            if d["materials"]["consumed"]:
                                d["materials"]["value"] += ", which the spell consumes"
                            comp += " ({})".format(d["materials"]["value"])
                        components.append(comp)
                ET.SubElement(spell, "components").text = ",".join(components)
                ET.SubElement(spell, "duration").text = (
                    ("Concentration" if d["components"]["concentration"] else "")
                    + "Instantaneous"
                    if d["duration"]["units"] == "inst"
                    else "{} {}".format(d["duration"]["value"], d["duration"]["units"])
                )
                ET.SubElement(spell, "source").text = d["source"]
                ET.SubElement(spell, "text").text = (
                    d["description"]["value"] + "\n<i>Source: " + d["source"] + "</i>"
                )
                continue
            item = ET.SubElement(
                compendium, "item", {"id": str(uuid.uuid5(moduuid, i["_id"]))}
            )
            ET.SubElement(item, "name").text = i["name"]
            ET.SubElement(item, "slug").text = slugify(i["name"])
            if "weight" in d and d["weight"]:
                ET.SubElement(item, "weight").text = str(d["weight"])
            if "rarity" in d and d["rarity"]:
                ET.SubElement(item, "rarity").text = d["rarity"].title()
            if "price" in d and d["price"]:
                value = ET.SubElement(item, "value")
                if d["price"] >= 100:
                    value.text = "{:g} gp".format(d["price"] / 100)
                elif d["price"] >= 10:
                    value.text = "{:g} sp".format(d["price"] / 10)
                else:
                    value.text = "{:g} cp".format(d["price"])
            if i["type"] in ["consumable"]:
                if d["consumableType"] == "potion":
                    ET.SubElement(item, "type").text = "P"
                elif d["consumableType"] == "wand":
                    ET.SubElement(item, "type").text = "WD"
                elif d["consumableType"] == "scroll":
                    ET.SubElement(item, "type").text = "SC"
                elif d["consumableType"] in ["food", "trinket"]:
                    ET.SubElement(item, "type").text = "G"
                elif d["consumableType"] == "ammo":
                    ET.SubElement(item, "type").text = "A"
                else:
                    print("Dont know consumable:", d["consumableType"])
                    ET.SubElement(item, "type").text = "G"
            elif i["type"] in ["equipment"]:
                if d["armor"]["type"] in ["clothing", "light"]:
                    ET.SubElement(item, "type").text = "LA"
                elif d["armor"]["type"] in ["medium"]:
                    ET.SubElement(item, "type").text = "MA"
                elif d["armor"]["type"] in ["heavy"]:
                    ET.SubElement(item, "type").text = "HA"
                elif d["armor"]["type"] in ["shield"]:
                    ET.SubElement(item, "type").text = "S"
                elif d["armor"]["type"] in ["trinket"]:
                    ET.SubElement(item, "type").text = "G"
                else:
                    print("Dont know armor type:", d["armor"]["type"])
                    ET.SubElement(item, "type").text = "AA"
                if d["armor"]["value"]:
                    ET.SubElement(item, "ac").text = str(d["armor"]["value"])
            elif i["type"] == "weapon":
                if d["weaponType"] in ["simpleR", "martialR"]:
                    ET.SubElement(item, "type").text = "R"
                elif d["weaponType"] in ["simpleM", "martialM"]:
                    ET.SubElement(item, "type").text = "M"
                elif "staff" in d and d["staff"]:
                    ET.SubElement(item, "type").text = "ST"
                else:
                    if d["weaponType"] not in ["natural"]:
                        print("Dont know weapon:", d["weaponType"])
                    ET.SubElement(item, "type").text = "WW"
                props = []
                for prop in d["properties"].keys():
                    if not d["properties"][prop]:
                        continue
                    if prop == "amm":
                        props.append("A")
                    if prop == "fin":
                        props.append("F")
                    if prop == "hvy":
                        props.append("H")
                    if prop == "lgt":
                        props.append("L")
                    if prop == "lod":
                        props.append("LD")
                    if prop == "rch":
                        props.append("R")
                    if prop == "spc":
                        props.append("S")
                    if prop == "thr":
                        props.append("T")
                    if prop == "two":
                        props.append("2H")
                    if prop == "ver":
                        props.append("V")
                ET.SubElement(item, "property").text = ",".join(props)
                if d["damage"]["parts"]:
                    ET.SubElement(item, "dmg1").text = re.sub(
                        r"[ ]?\+[ ]?@mod", r"", d["damage"]["parts"][0][0], re.I
                    )
                    if d["damage"]["parts"][0][1]:
                        ET.SubElement(item, "dmgType").text = d["damage"]["parts"][0][
                            1
                        ][0].upper()
                if d["damage"]["versatile"]:
                    ET.SubElement(item, "dmg2").text = re.sub(
                        r"\[\[a-z]*\]?[ ]?\+[ ]?(@mod)?", r"", d["damage"]["versatile"], re.I
                    )
                if "range" in d:
                    ET.SubElement(item, "range").text = "{} {}".format(
                        "{}/{}".format(d["range"]["value"], d["range"]["long"])
                        if d["range"]["long"]
                        else d["range"]["value"],
                        d["range"]["units"]
                    )
            elif i["type"] in ["loot", "backpack", "tool"]:
                ET.SubElement(item, "type").text = "G"
            else:
                print("Dont know item type", i["type"])
            ET.SubElement(item, "text").text = fixHTMLContent(d["description"]["value"])
            if i["img"]:
                i["img"] = urllib.parse.unquote(i["img"])
            if i["img"] and os.path.exists(i["img"]):
                ET.SubElement(item, "image").text = (
                    slugify(i["name"]) + "_" + os.path.basename(i["img"])
                )
                shutil.copy(
                    i["img"],
                    os.path.join(
                        tempdir,
                        "items",
                        slugify(i["name"]) + "_" + os.path.basename(i["img"]),
                    ),
                )
        for a in actors:
            itemnumber += 1
            if args.gui:
                worker.updateProgress(
                    75 + (itemnumber / (len(items) + len(actors))) * 10
                )
            print(
                "\rGenerating compendium [{}/{}]".format(
                    itemnumber, len(items) + len(actors)
                ),
                file=sys.stderr,
                end="",
            )
            monster = ET.SubElement(
                compendium, "monster", {"id": str(uuid.uuid5(moduuid, a["_id"]))}
            )
            d = a["data"]
            ET.SubElement(monster, "name").text = a["name"]
            ET.SubElement(monster, "slug").text = slugify(a["name"])
            ET.SubElement(monster, "size").text = d["traits"]["size"][0].upper()
            if "type" in d["details"]:
                if type(d["details"]["type"]) == dict:
                    monstertype = d["details"]["type"]["value"]
                    if d["details"]["type"]["swarm"]:
                        monstertype = "swarm of {} {}s".format(d["details"]["type"]["swarm"].title(), monstertype)
                    if d["details"]["type"]["subtype"]:
                        monstertype += " ({})".format(d["details"]["type"]["subtype"])
                    ET.SubElement(monster, "type").text = d["details"]["type"]["custom"] or monstertype
                else:
                    ET.SubElement(monster, "type").text = d["details"]["type"]
            if "alignment" in d["details"]:
                ET.SubElement(monster, "alignment").text = d["details"]["alignment"]
            ET.SubElement(monster, "ac").text = str(d["attributes"]["ac"]["value"] if "value" in d["attributes"]["ac"] else d["attributes"]["ac"]["flat"])
            if "formula" in d["attributes"]["hp"] and d["attributes"]["hp"]["formula"]:
                ET.SubElement(monster, "hp").text = "{} ({})".format(
                    d["attributes"]["hp"]["value"], d["attributes"]["hp"]["formula"]
                )
            else:
                ET.SubElement(monster, "hp").text = "{}".format(
                    d["attributes"]["hp"]["value"]
                )
            if "speed" in d["attributes"] and "_deprecated" not in d["attributes"]["speed"]:
                if d["attributes"]["speed"]["special"]:
                    ET.SubElement(monster, "speed").text = (
                        d["attributes"]["speed"]["value"]
                        + ", "
                        + d["attributes"]["speed"]["special"]
                    )
                else:
                    ET.SubElement(monster, "speed").text = d["attributes"]["speed"][
                        "value"
                    ]
            elif "movement" in d["attributes"]:
                speed = []
                m = d["attributes"]["movement"]
                for k, v in m.items():
                    if not m[k]:
                        continue
                    if k == "walk":
                        speed.insert(0, "{} {}".format(m[k], m["units"]))
                    elif k != "units":
                        speed.append("{} {} {}".format(k, m[k], m["units"]))
                ET.SubElement(monster, "speed").text = ", ".join(speed)
            ET.SubElement(monster, "str").text = str(d["abilities"]["str"]["value"])
            ET.SubElement(monster, "dex").text = str(d["abilities"]["dex"]["value"])
            ET.SubElement(monster, "con").text = str(d["abilities"]["con"]["value"])
            ET.SubElement(monster, "int").text = str(d["abilities"]["int"]["value"])
            ET.SubElement(monster, "wis").text = str(d["abilities"]["wis"]["value"])
            ET.SubElement(monster, "cha").text = str(d["abilities"]["cha"]["value"])
            ET.SubElement(monster, "save").text = ", ".join(
                [
                    "{} {:+d}".format(k.title(), v["save"])
                    for (k, v) in d["abilities"].items()
                    if "save" in v and (v["save"] != v["mod"] and v["proficient"])
                ]
            )
            ET.SubElement(monster, "skill").text = ", ".join(
                [
                    "{} {:+d}".format(
                        skills[k],
                        v["total"]
                        if "total" in v
                        else v["mod"] + v["prof"]
                        if "prof" in v
                        else v["mod"],
                    )
                    for (k, v) in d["skills"].items()
                    if ("total" in v and v["mod"] != v["total"])
                    or (
                        "mod" in d["abilities"][v["ability"]] and "mod" in v
                        and v["mod"] != d["abilities"][v["ability"]]["mod"]
                    )
                ]
            ) if "skills" in d else ""
            ET.SubElement(monster, "immune").text = "; ".join(
                d["traits"]["di"]["value"]
            ) + (
                " {}".format(d["traits"]["di"]["special"])
                if "special" in d["traits"]["di"] and d["traits"]["di"]["special"]
                else ""
            )
            ET.SubElement(monster, "vulnerable").text = "; ".join(
                d["traits"]["dv"]["value"]
            ) + (
                " {}".format(d["traits"]["dv"]["special"])
                if "special" in d["traits"]["dv"] and d["traits"]["dv"]["special"]
                else ""
            )
            ET.SubElement(monster, "resist").text = "; ".join(
                d["traits"]["dr"]["value"]
            ) + (
                " {}".format(d["traits"]["dr"]["special"])
                if "special" in d["traits"]["dr"] and d["traits"]["dr"]["special"]
                else ""
            )
            ET.SubElement(monster, "conditionImmune").text = ", ".join(
                d["traits"]["ci"]["value"]
            ) + (
                " {}".format(d["traits"]["ci"]["special"])
                if "special" in d["traits"]["ci"] and d["traits"]["ci"]["special"]
                else ""
            )
            if "senses" in d["traits"]:
                if type(d["traits"]["senses"]) == dict:
                    #darkvision': 60, 'blindsight': 0, 'tremorsense': 0, 'truesight': 0, 'units': 'ft', 'special': ''}
                    senses = d["traits"]["senses"]
                    units = senses["units"] if "units" in senses else "ft"
                    special = ", {}".format(senses["special"]) if "special" in senses and senses["special"] else ""
                    ET.SubElement(monster, "senses").text = ", ".join([
                        "{} {} {}".format(k,v,units) for k,v in senses.items() if v != 0 and k not in ["units","special"]
                        ])+special
                else:
                    ET.SubElement(monster, "senses").text = d["traits"]["senses"]
            ET.SubElement(monster, "passive").text = (
                str(d["skills"]["prc"]["passive"])
                if "skills" in d and "passive" in d["skills"]["prc"]
                else ""
            )
            ET.SubElement(monster, "languages").text = ", ".join(
                d["traits"]["languages"]["value"]
            ) + (
                " {}".format(d["traits"]["languages"]["special"])
                if "special" in d["traits"]["languages"]
                and d["traits"]["languages"]["special"]
                else ""
            ) if "traits" in d and "languages" in d["traits"] else ""

            ET.SubElement(monster, "description").text = fixHTMLContent(
                (
                    (d["details"]["biography"]["value"] or "")
                    + "\n"
                    + (d["details"]["biography"]["public"] or "")
                ).rstrip()
            )
            if "cr" in d["details"]:
                ET.SubElement(monster, "cr").text = (
                    "{}/{}".format(*d["details"]["cr"].as_integer_ratio())
                    if type(d["details"]["cr"]) != str and 0 < d["details"]["cr"] < 1
                    else str(d["details"]["cr"])
                )
            if "source" in d["details"]:
                ET.SubElement(monster, "source").text = d["details"]["source"]
            if "environment" in d["details"]:
                ET.SubElement(monster, "environments").text = d["details"][
                    "environment"
                ]
            if a["img"]:
                a["img"] = urllib.parse.unquote(a["img"])
            if a["img"] and os.path.exists(a["img"]):
                if os.path.splitext(a["img"])[1] == ".webp" and args.jpeg != ".webp":
                    PIL.Image.open(a["img"]).save(
                        os.path.join(
                            tempdir,
                            "monsters",
                            slugify(a["name"])
                            + "_"
                            + os.path.splitext(os.path.basename(a["img"]))[0]
                            + args.jpeg,
                        )
                    )
                    os.remove(a["img"])
                    ET.SubElement(monster, "image").text = (
                        slugify(a["name"])
                        + "_"
                        + os.path.splitext(os.path.basename(a["img"]))[0]
                        + args.jpeg
                    )
                else:
                    ET.SubElement(monster, "image").text = (
                        slugify(a["name"]) + "_" + os.path.basename(a["img"])
                    )
                    shutil.copy(
                        a["img"],
                        os.path.join(
                            tempdir,
                            "monsters",
                            slugify(a["name"]) + "_" + os.path.basename(a["img"]),
                        ),
                    )
            if a["token"]["img"]:
                a["token"]["img"] = urllib.parse.unquote(a["token"]["img"])
            if a["token"]["img"] and os.path.exists(a["token"]["img"]):
                if (
                    os.path.splitext(a["token"]["img"])[1] == ".webp"
                    and args.jpeg != ".webp"
                ):
                    PIL.Image.open(a["token"]["img"]).save(
                        os.path.join(
                            tempdir,
                            "monsters",
                            "token_"
                            + slugify(a["name"])
                            + "_"
                            + os.path.splitext(os.path.basename(a["token"]["img"]))[0]
                            + ".png",
                        )
                    )
                    os.remove(a["token"]["img"])
                    ET.SubElement(monster, "image").text = (
                        "token_"
                        + slugify(a["name"])
                        + "_"
                        + os.path.splitext(os.path.basename(a["token"]["img"]))[0]
                        + ".png"
                    )
                else:
                    ET.SubElement(monster, "token").text = (
                        "token_"
                        + slugify(a["name"])
                        + "_"
                        + os.path.basename(a["token"]["img"])
                    )
                    shutil.copy(
                        a["token"]["img"],
                        os.path.join(
                            tempdir,
                            "monsters",
                            "token_"
                            + slugify(a["name"])
                            + "_"
                            + os.path.basename(a["img"]),
                        ),
                    )
            equip = []
            for trait in a["items"]:
                if trait["type"] == "feat":
                    if trait["data"]["activation"]["type"] in [
                        "action",
                        "reaction",
                        "legendary",
                    ]:
                        typ = trait["data"]["activation"]["type"]
                    else:
                        typ = "trait"
                elif trait["type"] == "weapon":
                    typ = "action"
                else:
                    if trait["type"] == "equipment":
                        equip.append("<item>{}</item>".format(trait["name"]))
                    continue
                el = ET.SubElement(monster, typ)
                ET.SubElement(el, "name").text = trait["name"]
                txt = ET.SubElement(el, "text")
                txt.text = fixHTMLContent(trait["data"]["description"]["value"])
                txt.text = re.sub(
                    r"^((?:<[^>]*?>)*){}\.?((?:<\/[^>]*?>)*)\.?".format(
                        re.escape(trait["name"])
                    ),
                    r"\1\2",
                    txt.text,
                )
            if len(equip) > 0:
                trait = ET.SubElement(monster, "trait")
                ET.SubElement(trait, "name").text = "Equipment"
                ET.SubElement(trait, "text").text = ", ".join(equip)
        tree = ET.ElementTree(indent(compendium, 1))
        if args.gui:
            worker.updateProgress(86)
            worker.outputLog("Generating compendium.xml")
        tree.write(
            os.path.join(tempdir, "compendium.xml"),
            xml_declaration=True,
            short_empty_elements=False,
            encoding="utf-8",
        )
    os.chdir(cwd)
    if args.gui:
        worker.updateProgress(90)
        worker.outputLog("Zipping module")
    if args.packdir:
        zipfilename = "{}.pack".format(mod["name"])
    else:
        zipfilename = "{}.module".format(mod["name"])
    # zipfile = shutil.make_archive("module","zip",tempdir)
    if args.output:
        zipfilename = args.output
    zippos = 0
    with zipfile.ZipFile(
        zipfilename, "w", allowZip64=False, compression=zipfile.ZIP_DEFLATED
    ) as zipObj:
        # Iterate over all the files in directory
        for folderName, subfolders, filenames in os.walk(tempdir):
            if args.packdir and os.path.commonprefix([folderName, packdir]) != packdir:
                continue
            if args.gui:
                worker.updateProgress(
                    90 + 10 * (zippos / len(list(os.walk(os.path.abspath(tempdir)))))
                )
                zippos += 1
            for filename in filenames:
                if filename.startswith("."):
                    continue
                # create complete filepath of file in directory
                filePath = os.path.join(folderName, filename)
                # Add file to zip
                sys.stderr.write("\033[K")
                print("\rAdding: {}".format(filename), file=sys.stderr, end="")
                zipObj.write(
                    filePath,
                    filename if args.packdir else os.path.relpath(filePath, tempdir),
                )
    sys.stderr.write("\033[K")
    print("\rDeleteing temporary files", file=sys.stderr, end="")
    # shutil.rmtree(tempdir)
    tempdir = None
    sys.stderr.write("\033[K")
    print("\rFinished creating module: {}".format(zipfilename), file=sys.stderr)
    if args.gui:
        worker.updateProgress(100)
        worker.outputLog("Finished.")


if args.gui:
    import icon
    from PyQt5.QtGui import QIcon, QPixmap
    from PyQt5.QtCore import (
        QObject,
        QThread,
        pyqtSignal,
        pyqtSlot,
        QRect,
        QCoreApplication,
        QMetaObject,
        Qt,
        QSettings,
    )
    from PyQt5.QtWidgets import *

    class Worker(QThread):
        def __init__(self, parent=None):
            QThread.__init__(self, parent)
            # self.exiting = False
            args = None

        progress = pyqtSignal(int)
        message = pyqtSignal(str)
        # def __del__(self):
        #    self.exiting = True
        #    self.wait()
        def convert(self, args):
            self.args = args
            self.start()

        def updateProgress(self, pct):
            self.progress.emit(math.floor(pct))

        def outputLog(self, msg):
            self.message.emit(msg)

        def run(self):
            try:
                convert(args, self)
            except Exception:
                import traceback

                self.message.emit(traceback.format_exc())
                global tempdir
                if tempdir:
                    try:
                        shutil.rmtree(tempdir)
                        tempdir = None
                    except:
                        pass

    class ManifestWorker(QThread):
        def __init__(self, parent=None):
            QThread.__init__(self, parent)
            # self.exiting = False
            manifesturl = None

        progress = pyqtSignal(int)
        message = pyqtSignal(str)
        # def __del__(self):
        #    self.exiting = True
        #    self.wait()
        def download(self, manifesturl):
            self.manifesturl = manifesturl
            self.start()

        def updateProgress(self, pct):
            self.progress.emit(math.floor(pct))

        def sendMessage(self, msg):
            self.message.emit(msg)

        def run(self):
            try:
                global tempdir
                tempdir = tempfile.mkdtemp(prefix="convertfoundry_")
                urllib.request.urlretrieve(
                    self.manifesturl, os.path.join(tempdir, "manifest.json")
                )
                with open(os.path.join(tempdir, "manifest.json")) as f:
                    manifest = json.load(f)
                self.sendMessage("Downloading: {}".format(manifest["title"]))

                def progress(block_num, block_size, total_size):
                    pct = 100.00 * ((block_num * block_size) / total_size)
                    self.updateProgress(pct)

                urllib.request.urlretrieve(
                    manifest["download"], os.path.join(tempdir, "module.zip"), progress
                )
                self.sendMessage("DONE")
            except Exception as e:
                self.sendMessage("An error occurred downloading the manifest:" + str(e))

    class Prefs(QDialog):
        def __init__(self):
            super(Prefs, self).__init__()
            settings = QSettings()
            self.settings = settings
            self.ffmpeg_qpath = settings.value("ffmpeg_path", None, type=str)
            self.ffprobe_qpath = settings.value("ffprobe_path", None, type=str)
            self.setupUi(self)
            self.show()

        def setupUi(self, Dialog):
            Dialog.setObjectName("Dialog")
            Dialog.resize(400, 105)
            Dialog.setFixedSize(400, 105)
            self.ffmpeg_label = QLabel(Dialog)
            self.ffmpeg_label.setGeometry(QRect(10, 10, 100, 25))
            self.ffmpeg_label.setText("FFmpeg binary:")
            self.ffmpeg_text = QLineEdit(Dialog)
            self.ffmpeg_text.setGeometry(QRect(110, 10, 180, 25))
            self.ffmpeg_text.setText(self.ffmpeg_qpath or ffmpeg_path)
            self.ffmpeg_text.textChanged.connect(self.pathChange)
            self.ffprobe_label = QLabel(Dialog)
            self.ffprobe_label.setGeometry(QRect(10, 40, 100, 25))
            self.ffprobe_label.setText("FFprobe binary:")
            self.ffprobe_text = QLineEdit(Dialog)
            self.ffprobe_text.setGeometry(QRect(110, 40, 180, 25))
            self.ffprobe_text.setText(self.ffprobe_qpath or ffprobe_path)
            self.ffprobe_text.textChanged.connect(self.pathChange)
            self.browseButton1 = QPushButton(Dialog)
            self.browseButton1.setGeometry(QRect(300, 10, 90, 25))
            self.browseButton1.setObjectName("browseButton1")
            self.browseButton1.setText("Browse…")
            self.browseButton1.clicked.connect(self.ffmpegBrowse)
            self.browseButton2 = QPushButton(Dialog)
            self.browseButton2.setGeometry(QRect(300, 40, 90, 25))
            self.browseButton2.setObjectName("browseButton2")
            self.browseButton2.setText("Browse…")
            self.browseButton2.clicked.connect(self.ffprobeBrowse)
            self.buttonBox = QDialogButtonBox(Dialog)
            self.buttonBox.setGeometry(QRect(10, 70, 390, 25))
            self.buttonBox.setOrientation(Qt.Horizontal)
            self.buttonBox.setStandardButtons(
                QDialogButtonBox.Cancel | QDialogButtonBox.Ok
            )
            self.buttonBox.accepted.connect(Dialog.accept)
            self.buttonBox.rejected.connect(Dialog.reject)

        def pathChange(self):
            self.ffmpeg_qpath = self.ffmpeg_text.text()
            self.ffprobe_qpath = self.ffprobe_text.text()

        def ffmpegBrowse(self):
            fileName = QFileDialog.getOpenFileName(
                self, "Select FFmpeg binary", "", "FFmpeg (ffmpeg;ffmpeg.exe)"
            )
            if fileName[0] and os.path.exists(fileName[0]):
                self.ffmpeg_qpath = fileName[0]
                self.ffmpeg_text.setText(self.ffmpeg_qpath)

        def ffprobeBrowse(self):
            fileName = QFileDialog.getOpenFileName(
                self, "Select FFprobe binary", "", "FFprobe (ffprobe;ffprobe.exe)"
            )
            if fileName[0] and os.path.exists(fileName[0]):
                self.ffprobe_qpath = fileName[0]
                self.ffprobe_text.setText(self.ffprobe_qpath)

    class GUI(QDialog):
        def setupUi(self, Dialog):
            Dialog.setObjectName("Dialog")
            Dialog.resize(400, 350)
            Dialog.setFixedSize(400, 350)
            self.opacity = QGraphicsOpacityEffect()
            self.opacity.setOpacity(0.1)
            self.icon = QLabel(Dialog)
            self.icon.setGeometry(QRect(50, 25, 300, 300))
            self.icon.setPixmap(QPixmap(":/Icon.png").scaled(300, 300))
            self.icon.setGraphicsEffect(self.opacity)
            # self.icon.show()
            self.title = QLabel(Dialog)
            self.title.setGeometry(QRect(30, 20, 340, 30))
            self.title.setAlignment(Qt.AlignCenter)
            self.title.setText("<h1>Foundry to Encounter</h1>")
            self.progress = QProgressBar(Dialog)
            self.progress.setEnabled(True)
            self.progress.setGeometry(QRect(30, 210, 340, 23))
            self.progress.setVisible(False)
            self.progress.setProperty("value", 0)
            self.progress.setObjectName("progress")
            self.browseButton = QPushButton(Dialog)
            self.browseButton.setGeometry(QRect(140, 50, 120, 32))
            self.browseButton.setObjectName("browseButton")
            self.compendium = QCheckBox(Dialog)
            self.compendium.setGeometry(QRect(30, 240, 171, 31))
            self.compendium.setObjectName("compendium")
            # self.jpeg = QCheckBox(Dialog)
            self.jpeg = QComboBox(Dialog)
            self.jpeg.addItems(
                [
                    "Do not convert WebP Files",
                    "Convert all WebP Files to PNG",
                    "Convert WebP Maps to JPEG & assets to PNG",
                ]
            )
            self.jpeg.setGeometry(QRect(30, 265, 340, 31))
            self.jpeg.setObjectName("jpeg")
            self.label = QLabel(Dialog)
            self.label.setGeometry(QRect(30, 80, 340, 21))
            self.label.setVisible(False)
            self.label.setText("")
            self.label.setObjectName("label")
            self.output = QTextEdit(Dialog)
            self.output.setGeometry(QRect(30, 100, 340, 100))
            self.output.setVisible(False)
            self.output.setObjectName("output")
            self.convert = QPushButton(Dialog)
            self.convert.setGeometry(QRect(140, 300, 120, 32))
            self.convert.setObjectName("convert")
            self.convert.setEnabled(False)

            menubar = QMenuBar(self)

            exitAct = QAction("&Exit", self)
            exitAct.setShortcut("Ctrl+Q")
            exitAct.setStatusTip("Exit application")
            exitAct.triggered.connect(app.quit)

            openAct = QAction("&Open…", self)
            openAct.setShortcut("Ctrl+O")
            openAct.setStatusTip("Open Foundry ZIP File")
            openAct.triggered.connect(self.openFile)

            openManifestAct = QAction("Open Manifest &Url…", self)
            openManifestAct.setShortcut("Ctrl+U")
            openManifestAct.setStatusTip("Download File from Manifest at URL")
            openManifestAct.triggered.connect(self.openManifest)

            createPackAct = QAction("Create Asset &Pack…", self)
            createPackAct.setStatusTip("Create an Asset Pack instead of a Module")
            createPackAct.setEnabled(False)
            createPackAct.triggered.connect(self.selectPack)
            self.createPackAct = createPackAct

            ffmpegAct = QAction("Set paths for FFmpeg…", self)
            ffmpegAct.setStatusTip("Set paths for FFmpeg and FFprobe")
            ffmpegAct.triggered.connect(self.setFFmpeg)

            fileMenu = menubar.addMenu("&File")
            fileMenu.addAction(openAct)
            fileMenu.addAction(openManifestAct)
            fileMenu.addAction(createPackAct)
            fileMenu.addAction(ffmpegAct)
            fileMenu.addAction(exitAct)

            aboutAct = QAction("&About", self)
            aboutAct.setStatusTip("About FoundryToEncounter")
            aboutAct.triggered.connect(self.showAbout)

            helpMenu = menubar.addMenu("&Help")
            helpMenu.addAction(aboutAct)

            self.retranslateUi(Dialog)
            QMetaObject.connectSlotsByName(Dialog)

        def retranslateUi(self, Dialog):
            _translate = QCoreApplication.translate
            Dialog.setWindowTitle(_translate("Dialog", "Foundry to Encounter"))
            self.browseButton.setText(_translate("Dialog", "Browse..."))
            self.compendium.setText(_translate("Dialog", "Include Compendium"))
            # self.jpeg.setText(_translate("Dialog", "Convert WebP to JPG instead of PNG"))
            self.convert.setText(_translate("Dialog", "Convert"))

        def __init__(self):
            super(GUI, self).__init__()
            # uic.loadUi('foundrytoencounter.ui', self)
            self.foundryFile = None
            self.packdir = None
            self.outputFile = ""
            self.worker = Worker()
            self.manifestWorker = ManifestWorker()
            self.setupUi(self)
            self.browseButton.clicked.connect(self.openFile)
            self.convert.clicked.connect(self.saveFile)
            self.worker.message.connect(self.outputLog)
            self.worker.progress.connect(self.updateProgress)
            self.manifestWorker.progress.connect(self.updateProgress)
            self.manifestWorker.message.connect(self.manifestMessage)
            self.show()
            self.settings = QSettings()
            # self.openFile()

        def clearFiles(self):
            self.foundryFile = None
            self.outputFile = ""
            self.label.setText("")
            self.label.setVisible(False)
            self.convert.setEnabled(False)
            self.createPackAct.setEnabled(False)

        def setFiles(self, filename, name):
            self.foundryFile = filename
            self.outputFile = "{}.module".format(name)
            self.createPackAct.setEnabled(True)
            self.output.clear()

        def openFile(self):
            fileName = QFileDialog.getOpenFileName(
                self,
                "Open Foundry ZIP File",
                self.settings.value("last_path", None, type=str),
                "Foundry Archive (*.zip)",
            )
            if not fileName[0] or not os.path.exists(fileName[0]):
                self.clearFiles()
                return
            self.settings.setValue("last_path", os.path.split(fileName[0])[0])
            self.settings.sync()
            with zipfile.ZipFile(fileName[0]) as z:
                isworld = False
                mod = None
                for filename in z.namelist():
                    if os.path.basename(filename) == "world.json":
                        with z.open(filename) as f:
                            mod = json.load(f)
                        isworld = True
                    elif not mod and os.path.basename(filename) == "module.json":
                        with z.open(filename) as f:
                            mod = json.load(f)
            if mod:
                if isworld:
                    self.label.setText("Foundry World: {}".format(mod["title"]))
                else:
                    self.label.setText("Foundry Module: {}".format(mod["title"]))
                self.label.setVisible(True)
                self.setFiles(fileName[0], mod["name"])
                self.convert.setEnabled(True)
            else:
                alert = QMessageBox(self)
                alert.setWindowTitle("Invalid")
                alert.setText(
                    "No foundry data was found in this zip file.\nWould you like to convert it to an asset pack?"
                )
                alert.setIcon(QMessageBox.Question)
                alert.setStandardButtons(QMessageBox.Cancel | QMessageBox.Yes)
                alert.setDefaultButton(QMessageBox.Cancel)
                btnid = alert.exec_()
                if btnid == QMessageBox.Cancel:
                    self.clearFiles()
                else:
                    self.label.setText(
                        "Asset Pack: {}".format(
                            os.path.splitext(os.path.basename(fileName[0]))[0].title()
                        )
                    )
                    self.setFiles(
                        fileName[0],
                        os.path.splitext(os.path.basename(fileName[0]))[0].title(),
                    )
                    self.output.clear()
                    self.label.setVisible(True)
                    self.convert.setEnabled(True)
                    self.packdir = "."
                    self.output.setVisible(True)
                    self.output.append(
                        "Will create asset pack with contents of " + fileName[0]
                    )
                    if self.outputFile.endswith(".module"):
                        self.outputFile = self.outputFile[:-7] + ".pack"

        def openManifest(self):
            manifesturl, okPressed = QInputDialog.getText(
                self, "Download from Manifest", "Manifest URL:", QLineEdit.Normal, ""
            )
            if not okPressed:
                self.clearFiles()
                return
            self.manifestWorker.download(manifesturl)

        def selectPack(self):
            paths = []
            with zipfile.ZipFile(self.foundryFile) as z:
                dirpath = ""
                for filename in z.namelist():
                    if os.path.basename(filename) == "world.json":
                        dirpath = os.path.dirname(filename)
                    elif os.path.basename(filename) == "module.json":
                        dirpath = os.path.dirname(filename)
                for filename in z.namelist():
                    parent, f = os.path.split(filename)
                    if parent.startswith(dirpath):
                        parent = parent[len(dirpath):]
                        if parent.startswith("/"):
                            parent = parent[1:]
                    if parent and parent not in paths:
                        paths.append(parent)
            packdir, okPressed = QInputDialog.getItem(
                self, "Create Asset Pack", "Create Asset Pack from path:", paths
            )
            if not okPressed:
                self.packdir = None
                if self.outputFile.endswith(".pack"):
                    self.outputFile = self.outputFile[:-5] + ".module"
                self.output.clear()
                self.output.setVisible(False)
                self.compendium.setEnabled(True)
            self.packdir = packdir
            if self.outputFile.endswith(".module"):
                self.outputFile = self.outputFile[:-7] + ".pack"
            self.compendium.setEnabled(False)
            self.output.setVisible(True)
            self.output.append(
                "Will create asset pack with contents of " + self.packdir
            )

        def manifestMessage(self, message):
            if message.startswith("Downloading:"):
                self.label.setText(message)
                self.label.setVisible(True)
                self.progress.setVisible(True)
            elif message == "DONE":
                self.progress.setVisible(False)
                with zipfile.ZipFile(os.path.join(tempdir, "module.zip")) as z:
                    isworld = False
                    mod = None
                    for filename in z.namelist():
                        if os.path.basename(filename) == "world.json":
                            with z.open(filename) as f:
                                mod = json.load(f)
                            isworld = True
                        elif not mod and os.path.basename(filename) == "module.json":
                            with z.open(filename) as f:
                                mod = json.load(f)
                if mod:
                    if isworld:
                        self.label.setText("Foundry World: {}".format(mod["title"]))
                    else:
                        self.label.setText("Foundry Module: {}".format(mod["title"]))
                    self.label.setVisible(True)
                    self.setFiles(os.path.join(tempdir, "module.zip"), mod["name"])
                    self.convert.setEnabled(True)
                else:
                    QMessageBox.warning(
                        self, "Invalid", "No foundry data was found in this zip file"
                    )
                    self.clearFiles()
            else:
                QMessageBox.warning(self, "Error", message)
                self.clearFiles()

        def showAbout(self):
            QMessageBox.about(
                self,
                "About FoundryToEncounter " + VERSION,
                "This utility converts a Foundry world or module to an EncounterPlus module.",
            )

        def outputLog(self, text):
            self.output.append(text)

        def updateProgress(self, pct):
            self.progress.setValue(pct)

        def setFFmpeg(self):
            prefs = Prefs()
            if prefs.exec():
                settings = QSettings()
                settings.setValue("ffmpeg_path", prefs.ffmpeg_qpath)
                settings.setValue("ffprobe_path", prefs.ffprobe_qpath)
                settings.sync()

        def saveFile(self):
            if self.packdir:
                fileName = QFileDialog.getSaveFileName(
                    self,
                    "Save Asset Pack",
                    os.path.join(
                        self.settings.value("last_path", None, type=str),
                        self.outputFile,
                    ),
                    "EncounterPlus Asset Pack (*.pack)",
                )
            else:
                fileName = QFileDialog.getSaveFileName(
                    self,
                    "Save Converted Module",
                    os.path.join(
                        self.settings.value("last_path", None, type=str),
                        self.outputFile,
                    ),
                    "EncounterPlus Module (*.module)",
                )
            self.outputFile = fileName[0]
            if not fileName[0]:
                return
            args.output = self.outputFile
            self.output.setVisible(True)
            self.output.clear()
            self.progress.setValue(0)
            self.progress.setVisible(True)
            args.srcfile = self.foundryFile
            args.compendium = self.compendium.isChecked()
            jpegopt = self.jpeg.currentText()
            if "JPEG" in jpegopt:
                args.jpeg = ".jpeg"
            elif "PNG" in jpegopt:
                args.jpeg = ".png"
            else:
                args.jpeg = ".webp"
            if self.packdir:
                args.packdir = self.packdir
            print(args)
            self.worker.convert(args)

    app = QApplication([])
    QCoreApplication.setApplicationName("FoundryToEncounter")
    QCoreApplication.setOrganizationName("Robert George")
    QCoreApplication.setOrganizationDomain("play5e.online")
    QCoreApplication.setApplicationVersion(VERSION)
    if sys.platform != "linux":
        app.setWindowIcon(QIcon(":/Icon.png"))
    gui = GUI()
    app.exec_()
else:
    convert()
