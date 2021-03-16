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

try:
    ffmpeg_path = shutil.which("ffmpeg") or shutil.which("ffmpeg",path=os.defpath)
    ffprobe_path = shutil.which("ffprobe") or shutil.which("ffprobe",path=os.defpath)
    if sys.platform == "darwin" and not ffmpeg_path and not ffprobe_path:
        # Try homebrew paths
        brewpath = "/usr/local/bin" + os.pathsep + "/opt/homebrew/bin"
        ffmpeg_path = shutil.which("ffmpeg",path=brewpath)
        ffprobe_path = shutil.which("ffprobe",path=brewpath)
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
    process = subprocess.Popen([ffprobe_path,'-v','error','-show_entries','format=duration','-select_streams','v:0','-show_entries','stream=codec_name,height,width','-of','default=noprint_wrappers=1',video],startupinfo=startupinfo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE)
    probe = {}
    lines = process.stdout.readlines()
    for entry in lines:
        m = re.match(r'(.*)=(.*)',entry.decode())
        if m:
            if m.group(1) == "duration":
                probe[m.group(1)]=float(m.group(2))
            elif m.group(1) in ["height","width"]:
                probe[m.group(1)]=int(m.group(2))
            else:
                probe[m.group(1)]=m.group(2)
    return probe

# Argument Parser
parser = argparse.ArgumentParser(
    description="Converts Foundry Modules/Worlds to EncounterPlus Modules")
parser.add_argument(
    '-o',
    dest="output",
    action='store',
    default=None,
    help="output into given output (default: [name].module)")
parser.add_argument(
    '-p',
    dest="packdir",
    action='store',
    default=None,
    help="create an asset pack using path provided instead of module")
parser.add_argument(
    '-c',
    dest="compendium",
    action='store_const',
    const=True,
    default=False,
    help="create compendium content with actors and items")
parser.add_argument(
    '-j',
    dest="jpeg",
    action='store_const',
    const=".jpg",
    default=".png",
    help="convert WebP to JPG instead of PNG")
parserg = parser.add_mutually_exclusive_group()
parserg.add_argument(
    dest="srcfile",
    action='store',
    default=False,
    nargs='?',
    help="foundry file to convert")
parserg.add_argument(
    '-gui',
    dest="gui",
    action='store_const',
    default=False,
    const=True,
    help="use graphical interface")
args = parser.parse_args()
if not args.srcfile and not args.gui:
    if sys.platform in ['darwin','win32']:
        args.gui = True
    else:
        parser.print_help()
        exit()
numbers = ['zero','one','two','three','four']
stats = {"str":"Strength","dex":"Dexterity","con":"Constitution","int":"Intelligence","wis":"Wisdom","cha":"Charisma"}
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
    "sur": "Survival"
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
        return '<a href="/roll/{0}/{1}">{0}</a>'.format(m.group(1),m.group(2))
    else:
        return '<a href="/roll/{0}">{0}</a>'.format(m.group(1))

def convert(args=args,worker=None):
    def createMap(map,mapgroup):
        if "padding" in map:
            map["offsetX"] = math.ceil((map["padding"]*map["width"])/map["grid"])*map["grid"]
            map["offsetY"] = math.ceil((map["padding"]*map["height"])/map["grid"])*map["grid"]
        else:
            map["offsetX"] = (map["width"] + math.ceil(0.5 * map["width"] / (map["grid"] * 2)) * (map["grid"] * 2) - map["width"]) * 0.5
            map["offsetY"] = (map["height"] + math.ceil(0.5 * map["height"] / (map["grid"] * 2)) * (map["grid"] * 2) - map["height"]) * 0.5

        mapbaseslug = slugify(map['name'])
        mapslug = mapbaseslug + str(len([i for i in slugs if mapbaseslug in i]))
        slugs.append(mapslug)
        if not map["img"] and map["tiles"][0]["width"] >= map["width"] and map["tiles"][0]["height"] >= map["height"]:
            bg = map["tiles"].pop(0)
            bg["img"] = urllib.parse.unquote(bg["img"])
            imgext = os.path.splitext(os.path.basename(urllib.parse.urlparse(bg["img"]).path))[1]
            if not imgext:
                imgext = args.jpeg
            if imgext == ".webp" and args.jpeg != ".webp":
                PIL.Image.open(bg["img"]).save(os.path.join(tempdir,os.path.splitext(bg["img"])[0]+args.jpeg))
                os.remove(bg["img"])
                map["img"] = os.path.splitext(bg["img"])[0]+args.jpeg
            else:
                map["img"] = bg["img"]
            map["shiftX"] = bg["x"]-map["offsetX"]
            map["shiftY"] = bg["y"]-map["offsetY"]
            map["width"] = bg["width"]
            map["height"] = bg["height"]
        map["rescale"] = 1.0
        if map["width"] > 8192 or map["height"] > 8192:
            map["rescale"] = 8192.0/map["width"] if map["width"] >= map["height"] else 8192.0/map["height"]
            map["grid"] = round(map["grid"]*map["rescale"])
            map["width"] *= round(map["rescale"])
            map["height"] *= round(map["rescale"])
            map['shiftX'] *= map["rescale"]
            map['shiftY'] *= map["rescale"]

        mapentry = ET.SubElement(module,'map',{'id': str(uuid.uuid5(moduuid,map['_id'])),'parent': mapgroup,'sort': str(int(map["sort"]))})
        ET.SubElement(mapentry,'name').text = map['name']
        ET.SubElement(mapentry,'slug').text = mapslug
        ET.SubElement(mapentry,'gridScale').text = str(round(map["gridDistance"]))#*((5.0/map["gridDistance"]))))
        ET.SubElement(mapentry,'gridUnits').text = str(map["gridUnits"])
        ET.SubElement(mapentry,'gridVisible').text = "YES" if map['gridAlpha'] > 0 else "NO"
        ET.SubElement(mapentry,'gridColor').text = map['gridColor']
        ET.SubElement(mapentry,'gridOffsetX').text = str(round(map['shiftX']))
        ET.SubElement(mapentry,'gridOffsetY').text = str(round(map['shiftY']))

        if map["img"] and os.path.exists(urllib.parse.unquote(map["img"])):
            map["img"] = urllib.parse.unquote(map["img"])
            imgext = os.path.splitext(os.path.basename(map["img"]))[1]
            if imgext == ".webm":
                try:
                    if args.gui:
                        worker.outputLog("Converting video map")
                    duration = ffprobe(map["img"])["duration"]
                    ffp = subprocess.Popen([ffmpeg_path,'-v','error','-i',map["img"],'-vf','pad=\'width=ceil(iw/2)*2:height=ceil(ih/2)*2\'','-vcodec','hevc','-acodec','aac','-vtag','hvc1','-progress','ffmpeg.log',os.path.splitext(map["img"])[0]+".mp4"],startupinfo=startupinfo, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
                    with open('ffmpeg.log','a+') as f:
                        logged = False
                        while ffp.poll() is None:
                            l = f.readline()
                            m = re.match(r'(.*?)=(.*)',l)
                            if m:
                                key = m.group(1)
                                val = m.group(2)
                                if key == "out_time_us":
                                    if not logged:
                                        print(" webm->mp4:    ",file=sys.stderr,end='')
                                        logged = True
                                    elif pct >= 100:
                                        print("\b",file=sys.stderr,end='')
                                    pos = round(float(val)/10000,2)
                                    pct = round(pos/duration)
                                    print("\b\b\b{:02d}%".format(pct),file=sys.stderr,end='')
                                    if args.gui:
                                        worker.updateProgress(pct)
                                    sys.stderr.flush()
                    os.remove('ffmpeg.log')
                    ffp = subprocess.Popen([ffmpeg_path,'-v','error','-i',map["img"],'-vf','pad=\'width=ceil(iw/2)*2:height=ceil(ih/2)*2\'','-vframes','1',os.path.splitext(map["img"])[0]+".jpg"],startupinfo=startupinfo, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
                    print("\b"*16,file=sys.stderr,end='')
                    print(" extracting still",file=sys.stderr,end='')
                    sys.stderr.flush()
                    ffp.wait()
                    os.remove(map["img"])
                    map["img"] = os.path.splitext(map["img"])[0]+".jpg"
                    ET.SubElement(mapentry,'video').text = os.path.splitext(map["img"])[0]+".mp4"
                except Exception:
                    import traceback
                    if args.gui:
                        worker.outputLog(traceback.format_exc())
                    else:
                        print(traceback.format_exc())
            if imgext == ".webp" and args.jpeg != ".webp":
                ET.SubElement(mapentry,'image').text = os.path.splitext(map["img"])[0]+args.jpeg
            else:
                ET.SubElement(mapentry,'image').text = map["img"]
            with PIL.Image.open(map["img"]) as img:
                if img.width > 8192 or img.height > 8192:
                    scale = 8192/img.width if img.width>=img.height else 8192/img.height
                    if args.gui:
                        worker.outputLog(" - Resizing map from {}x{} to {}x{}".format(img.width,img.height,round(img.width*scale),round(img.height*scale)))
                    img = img.resize((round(img.width*scale),round(img.height*scale)))
                    if imgext == ".webp" and args.jpeg != ".webp":
                        if args.gui:
                            worker.outputLog(" - Converting map from .webp to " + args.jpeg)
                        img.save(os.path.join(tempdir,os.path.splitext(map["img"])[0]+args.jpeg))
                        os.remove(map["img"])
                    else:
                        img.save(os.path.join(tempdir,map["img"]))
                elif imgext == ".webp" and args.jpeg != ".webp":
                        if args.gui:
                            worker.outputLog(" - Converting map from .webp to " + args.jpeg)
                        img.save(os.path.join(tempdir,os.path.splitext(map["img"])[0]+args.jpeg))
                        os.remove(map["img"])
                if map["height"] != img.height or map["width"] != img.width:
                    map["scale"] = map["width"]/img.width if map["width"]/img.width >= map["height"]/img.height else map["height"]/img.height
                    if map["scale"] > 1:
                        map["scale"] = 1.0
                        map["rescale"] = img.width/map["width"] if img.width/map["width"] >= img.height/map["height"] else img.height/map["height"]
                else:
                    map["scale"] = 1.0
        else:
            print(" |> Map Error NO BG FOR: {}".format(map["name"]),file=sys.stderr,end='')
            map["scale"] = 1.0
            with PIL.Image.new('1', (map["width"], map["height"]), color = 'black') as img:
                if img.width > 8192 or img.height > 8192:
                    scale = 8192/img.width if img.width>=img.height else 8192/img.height
                    if args.gui:
                        worker.outputLog(" - Resizing map from {}x{} to {}x{}".format(img.width,img.height,round(img.width*scale),round(img.height*scale)))
                    img = img.resize((round(img.width*scale),round(img.height*scale)))
                img.save(os.path.join(tempdir,mapslug+"_bg.png"))
                if map["height"] != img.height or map["width"] != img.width:
                    map["scale"] = map["width"]/img.width if map["width"]/img.width >= map["height"]/img.height else map["height"]/img.height
                    if map["scale"] > 1:
                        map["scale"] = 1.0
                        map["rescale"] = img.width/map["width"] if img.width/map["width"] >= img.height/map["height"] else img.height/map["height"]
                else:
                    map["scale"] = 1.0

                ET.SubElement(mapentry,'image').text = mapslug+"_bg.png"
            if 'thumb' in map and map["thumb"] and os.path.exists(map["thumb"]):
                imgext = os.path.splitext(os.path.basename(map["img"]))[1]
                if imgext == ".webp" and args.jpeg != ".webp":
                    ET.SubElement(mapentry,'snapshot').text = os.path.splitext(map["thumb"])[0]+args.jpeg
                    PIL.Image.open(map["thumb"]).save(os.path.join(tempdir,os.path.splitext(map["thumb"])[0]+args.jpeg))
                    os.remove(map["thumb"])
                else:
                    ET.SubElement(mapentry,'snapshot').text = map["thumb"]

        ET.SubElement(mapentry,'gridSize').text = str(round(map["grid"]*map["rescale"]))#*(5.0/map["gridDistance"])))
        ET.SubElement(mapentry,'scale').text = str(map["scale"])
        if "walls" in map and len(map["walls"])>0:
            ET.SubElement(mapentry,'lineOfSight').text = "YES"
            for i in range(len(map["walls"])):
                p = map["walls"][i]
                print("\rwall {}".format(i),file=sys.stderr,end='')
                pathlist = [
                        (p["c"][0]-map["offsetX"])*map["rescale"],
                        (p["c"][1]-map["offsetY"])*map["rescale"],
                        (p["c"][2]-map["offsetX"])*map["rescale"],
                        (p["c"][3]-map["offsetY"])*map["rescale"]
                        ]
                isConnected = False
                for pWall in mapentry.iter('wall'):
                    lastpath = pWall.find('data')
                    pWallID=pWall.get('id')
                    if lastpath != None and lastpath.text.endswith(",{:.1f},{:.1f}".format(pathlist[0],pathlist[1])):
                        wType = pWall.find('type')
                        if p['door'] > 0:
                            if p['door'] == 1 and wType.text != 'door':
                                continue
                            if p['door'] == 2 and wType.text != 'secretDoor':
                                continue
                            if p['ds'] > 0:
                                door = pWall.find('door')
                                if door == None:
                                    continue
                                elif p['ds'] == 1 and door.text != 'open':
                                    continue
                                elif p['ds'] == 2 and door.text != 'locked':
                                    continue
                        elif wType.text in ['door','secretDoor']:
                            continue
                        elif p['move'] == 0 and p['sense'] == 1 and wType.text != 'ethereal':
                            continue
                        elif p['move'] == 1 and p['sense'] == 0 and wType.text != 'invisible':
                            continue
                        elif p['move'] == 1 and p['sense'] == 2 and wType.text != 'terrain':
                            continue
                        if 'dir' in p:
                            wSide = pWall.find('side')
                            if wSide == None and p['dir'] > 0:
                                continue
                            if p['dir'] == 1 and wSide.text != 'left':
                                continue
                            if p['dir'] == 2 and wSide.text != 'right':
                                continue
                        isConnected = True
                        #pWall.set('id',pWallID+' '+p['_id'])
                        lastpath.text += ','+','.join("{:.1f}".format(x) for x in pathlist)
                        break
                if not isConnected:
                    wall = ET.SubElement(mapentry,'wall',{'id': str(uuid.uuid5(moduuid,p['_id'])) })
                    lastpath = ET.SubElement(wall,'data')
                    lastpath.text = ','.join("{:.1f}".format(x) for x in pathlist)
                if not isConnected:
                    if 'door' in p and p['door'] == 1:
                        ET.SubElement(wall,'type').text = 'door'
                        ET.SubElement(wall,'color').text = '#00ffff'
                        if p['ds'] > 0:
                            ET.SubElement(wall,'door').text = 'locked' if p['ds'] == 2 else 'open'
                    elif p['door'] == 2:
                        ET.SubElement(wall,'type').text = 'secretDoor'
                        ET.SubElement(wall,'color').text = '#00ffff'
                        if p['ds'] > 0:
                            ET.SubElement(wall,'door').text = 'locked' if p['ds'] == 2 else 'open'
                    elif p['move'] == 0 and p['sense'] == 1:
                        ET.SubElement(wall,'type').text = 'ethereal'
                        ET.SubElement(wall,'color').text = '#7f007f'
                    elif p['move'] == 1 and p['sense'] == 0:
                        ET.SubElement(wall,'type').text = 'invisible'
                        ET.SubElement(wall,'color').text = '#ff00ff'
                    elif p['move'] == 1 and p['sense'] == 2:
                        ET.SubElement(wall,'type').text = 'terrain'
                        ET.SubElement(wall,'color').text = '#ffff00'
                    else:
                        ET.SubElement(wall,'type').text = 'normal'
                        ET.SubElement(wall,'color').text = '#ff7f00'
                    if 'dir' in p and p['dir'] > 0:
                        ET.SubElement(wall,'side').text = 'left' if p['dir'] == 1 else 'right'

                    if 'door' in p and p['door'] > 0:
                        p["stroke"] = '#00ffff'
                    else:
                        p["stroke"] = '#ff7f00'
                    p["stroke_width"] = 5
                    p["layer"] = "walls"

                    ET.SubElement(wall,'generated').text = 'YES'

        if 'tiles' in map:
            for i in range(len(map["tiles"])):
                image = map["tiles"][i]
                image["img"] = urllib.parse.unquote(image["img"])
                print("\rtiles [{}/{}]".format(i,len(map["tiles"])),file=sys.stderr,end='')
                tile = ET.SubElement(mapentry,'tile')
                ET.SubElement(tile,'x').text = str(round((image["x"]-map["offsetX"]+(image["width"]*image["scale"]/2))*map["rescale"]))
                ET.SubElement(tile,'y').text = str(round((image["y"]-map["offsetY"]+(image["height"]*image["scale"]/2))*map["rescale"]))
                ET.SubElement(tile,'zIndex').text = str(image["z"])
                ET.SubElement(tile,'width').text = str(round(image["width"]*image["scale"]*map["rescale"]))
                ET.SubElement(tile,'height').text = str(round(image["height"]*image["scale"]*map["rescale"]))
                ET.SubElement(tile,'opacity').text = "1.0"
                ET.SubElement(tile,'rotation').text = str(image["rotation"])
                ET.SubElement(tile,'locked').text = "YES" if image["locked"] else "NO"
                ET.SubElement(tile,'layer').text = "object"
                ET.SubElement(tile,'hidden').text = "YES" if image["hidden"] else "NO"

                asset = ET.SubElement(tile,'asset')
                ET.SubElement(asset,'name').text = os.path.splitext(os.path.basename(image["img"]))[0]
                imgext = os.path.splitext(os.path.basename(image["img"]))[1]
                if imgext == ".webm":
                    try:
                        if os.path.exists(image["img"]):
                            if args.gui:
                                worker.outputLog(" - Converting webm tile to spritesheet")
                            probe = ffprobe(image["img"])
                            if probe['codec_name'] != 'vp9':
                                ffp = subprocess.Popen([ffmpeg_path,'-v','error','-i',image["img"],os.path.splitext(image["img"])[0]+"-frame%05d.png"],startupinfo=startupinfo, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
                            else:
                                ffp = subprocess.Popen([ffmpeg_path,'-v','error','-vcodec','libvpx-vp9','-i',image["img"],os.path.splitext(image["img"])[0]+"-frame%05d.png"],startupinfo=startupinfo, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
                            ffp.wait()
                            duration = probe['duration']
                            framewidth = probe['width']
                            frameheight = probe['height']
                            frames = []
                            for afile in os.listdir(os.path.dirname(image["img"])):
                                if re.match(re.escape(os.path.splitext(os.path.basename(image["img"]))[0])+"-frame[0-9]{5}\.png",afile):
                                    frames.append(os.path.join(os.path.dirname(image["img"]),afile))
                            def getGrid(n):
                                i = 1
                                factors = []
                                while(i < n+1):
                                    if n % i == 0:
                                        factors.append(i)
                                    i += 1
                                gw = factors[len(factors)//2]
                                gh = factors[(len(factors)//2)-1]
                                if gw*framewidth > 4096 or gh*frameheight > 4096:
                                    return (gh,gw)
                                else:
                                    return (gw,gh)
                            (gw,gh) = getGrid(len(frames))
                            with PIL.Image.new('RGBA', (round(framewidth*gw), round(frameheight*gh)), color = (0,0,0,0)) as img:
                                px = 0
                                py = 0
                                for i in range(len(frames)):
                                    img.paste(PIL.Image.open(frames[i]),(framewidth*px,frameheight*py))
                                    os.remove(frames[i])
                                    px += 1
                                    if px == gw:
                                        px = 0
                                        py += 1
                                if img.width > 4096 or img.height > 4096:
                                    scale = 4095/img.width if img.width>=img.height else 4095/img.height
                                    img = img.resize((round(img.width*scale),round(img.height*scale)))
                                    framewidth = round(framewidth*scale)
                                    frameheight = round(frameheight*scale)
                                img.save(os.path.splitext(image["img"])[0]+"-sprite.png")
                            os.remove(image["img"])
                        if os.path.exists(os.path.splitext(image["img"])[0]+"-sprite.png"):
                            ET.SubElement(asset,'type').text = "spriteSheet"
                            ET.SubElement(asset,'frameWidth').text = str(framewidth)
                            ET.SubElement(asset,'frameHeight').text = str(frameheight)
                            ET.SubElement(asset,'resource').text = os.path.splitext(image["img"])[0]+"-sprite.png"
                            ET.SubElement(asset,'duration').text = str(duration)
                        continue
                    except Exception:
                        import traceback
                        print(traceback.format_exc())
                        if args.gui:
                            worker.outputLog(" - webm tiles are not supported, consider converting to a spritesheet: "+image["img"])
                        print(" - webm tiles are not supported, consider converting to a spritesheet:",image["img"],file=sys.stderr,end='')
                    continue
                else:
                    ET.SubElement(asset,'type').text = "image"
                if image["img"].startswith("http"):
                    urllib.request.urlretrieve(image["img"],os.path.basename(image["img"]))
                    image["img"] = os.path.basename(image["img"])
                if not os.path.exists(image["img"]):
                    if os.path.exists(os.path.splitext(image["img"])[0]+".png"):
                        image["img"] = os.path.splitext(image["img"])[0]+".png"
                        imgext = ".png"
                    else:
                        if args.gui:
                            worker.outputLog(" - MISSING RESOURCE: "+image["img"])
                        print(" - MISSING RESOURCE:",image["img"],file=sys.stderr,end='')
                        continue
                img = PIL.Image.open(image["img"])
                if imgext == ".webp" and args.jpeg != ".webp":
                    ET.SubElement(asset,'resource').text = os.path.splitext(image["img"])[0]+".png"
                    if img.width > 4096 or img.height > 4096:
                        scale = 4095/img.width if img.width>=img.height else 4095/img.height
                        img = img.resize((round(img.width*scale),round(img.height*scale)))
                    if args.gui:
                        worker.outputLog(" - Converting tile from webp to png")
                    img.save(os.path.join(tempdir,os.path.splitext(image["img"])[0]+".png"))
                    os.remove(image["img"])
                else:
                    ET.SubElement(asset,'resource').text = image["img"]
                    if img.width > 4096 or img.height > 4096:
                        scale = 4095/img.width if img.width>=img.height else 4095/img.height
                        img = img.resize((round(img.width*scale),round(img.height*scale)))
                        img.save(os.path.join(tempdir,image["img"]))
        if 'lights' in map:
            for i in range(len(map["lights"])):
                print("\rlights [{}/{}]".format(i,len(map["lights"])),file=sys.stderr,end='')
                light = map["lights"][i]
                tile = ET.SubElement(mapentry,'tile')
                ET.SubElement(tile,'x').text = str(round((light["x"]-map["offsetX"])))
                ET.SubElement(tile,'y').text = str(round((light["y"]-map["offsetY"])))
                ET.SubElement(tile,'zIndex').text = str(0)
                ET.SubElement(tile,'width').text = str(round(50*map["rescale"]))
                ET.SubElement(tile,'height').text = str(round(50*map["rescale"]))
                ET.SubElement(tile,'opacity').text = "1.0"
                ET.SubElement(tile,'rotation').text = str(0)
                ET.SubElement(tile,'locked').text = "YES"
                ET.SubElement(tile,'layer').text = "dm"
                ET.SubElement(tile,'hidden').text = "YES"

                asset = ET.SubElement(tile,'asset', {'id': str(uuid.uuid5(moduuid,mapslug+"/lights/"+str(i)))})
                ET.SubElement(asset,'name').text = "Light {}".format(i+1)

                lightel = ET.SubElement(tile,'light', {'id': str(uuid.uuid5(moduuid,mapslug+"/lights/"+str(i)+"light"))})
                ET.SubElement(lightel,'radiusMax').text = str(round(light["dim"]))
                ET.SubElement(lightel,'radiusMin').text = str(round(light["bright"]))
                ET.SubElement(lightel,'color').text = light["tintColor"] if "tintColor" in light and light["tintColor"] else "#ffffff"
                ET.SubElement(lightel,'opacity').text = str(light["tintAlpha"])
                ET.SubElement(lightel,'alwaysVisible').text = "YES" if light["t"] == "u" else "NO"

        if 'tokens' in map and len(map['tokens']) > 0:
            encentry = ET.SubElement(module,'encounter',{'id': str(uuid.uuid5(moduuid,mapslug+"/encounter")),'parent': str(uuid.uuid5(moduuid,map['_id'])), 'sort': '1'})
            ET.SubElement(encentry,'name').text = map['name'] + " Encounter"
            ET.SubElement(encentry,'slug').text = slugify(map['name'] + " Encounter")
            for token in map['tokens']:
                combatant = ET.SubElement(encentry,'combatant')
                ET.SubElement(combatant,'name').text = token['name']
                ET.SubElement(combatant,'role').text = "hostile" if token['disposition'] < 0 else "friendly" if token['disposition'] > 0 else "neutral"
                ET.SubElement(combatant,'x').text = str(round((token['x']-map["offsetX"])*map["rescale"]))
                ET.SubElement(combatant,'y').text = str(round((token['y']-map["offsetY"])*map["rescale"]))
                actorLinked = False
                for a in actors:
                    if a['_id'] == token['actorId']:
                        ET.SubElement(combatant,'monster', { 'ref': "/monster/{}".format(slugify(a['name'])) })
                        actorLinked = True
                        break
                if not actorLinked:
                    ET.SubElement(combatant,'monster', { 'ref': "/monster/{}".format(slugify(token['name'])) })

        if 'drawings' in map and len(map['drawings']) > 0:
            for d in map['drawings']:
                if d['type'] == 't':
                    with PIL.Image.new('RGBA', (round(d["width"]), round(d["height"])), color = (0,0,0,0)) as img:
                        try:
                            font = PIL.ImageFont.truetype(os.path.join(moduletmp,mod["name"],"fonts",d['fontFamily'] + ".ttf"), size=d['fontSize'])
                        except Exception:
                            try:
                                font = PIL.ImageFont.truetype(d['fontFamily'] + ".ttf", size=d['fontSize'])
                            except Exception:
                                try:
                                    urllib.request.urlretrieve("https://raw.githubusercontent.com/google/fonts/master/ofl/{}/{}.ttf".format(d['fontFamily'].lower(),d['fontFamily']),d['fontFamily'] + ".ttf")
                                    font = PIL.ImageFont.truetype(d['fontFamily'] + ".ttf", size=d['fontSize'])
                                except Exception:
                                    font = PIL.ImageFont.load_default()
                        text = d['text']
                        draw = PIL.ImageDraw.Draw(img)
                        if draw.multiline_textsize(text,font=font)[0] > round(d["width"]):
                            words = text.split(' ')
                            text = ''
                            for i in range(len(words)):
                                if draw.multiline_textsize(text + ' ' + words[i],font=font)[0] <= round(d["width"]):
                                    text += ' ' + words[i]
                                else:
                                    text += '\n' + words[i]
                        draw.multiline_text((0,0),text,(255,255,255),spacing=0,font=font)
                        img.save(os.path.join(tempdir,"text_" + d['_id'] + ".png"))
                    tile = ET.SubElement(mapentry,'tile')
                    ET.SubElement(tile,'x').text = str(round((d["x"]-map["offsetX"]+(d["width"]/2))*map["rescale"]))
                    ET.SubElement(tile,'y').text = str(round((d["y"]-map["offsetY"]+(d["height"]/2))*map["rescale"]))
                    ET.SubElement(tile,'zIndex').text = str(d["z"])
                    ET.SubElement(tile,'width').text = str(round(d["width"]*map["rescale"]))
                    ET.SubElement(tile,'height').text = str(round(d["height"]*map["rescale"]))
                    ET.SubElement(tile,'opacity').text = "1.0"
                    ET.SubElement(tile,'rotation').text = str(d["rotation"])
                    ET.SubElement(tile,'locked').text = "YES" if d["locked"] else "NO"
                    ET.SubElement(tile,'layer').text = "object"
                    ET.SubElement(tile,'hidden').text = "YES" if d["hidden"] else "NO"
                    asset = ET.SubElement(tile,'asset')
                    ET.SubElement(asset,'name').text = d['text']
                    ET.SubElement(asset,'type').text = "image"
                    ET.SubElement(asset,'resource').text = "text_" + d['_id'] + ".png"

                elif d['type'] == 'p':
                    drawing = ET.SubElement(mapentry,'drawing',{'id': str(uuid.uuid5(moduuid,d['_id']))})
                    ET.SubElement(drawing,'layer').text = 'dm' if d['hidden'] else 'map'
                    ET.SubElement(drawing,'strokeWidth').text = str(d['strokeWidth'])
                    ET.SubElement(drawing,'strokeColor').text = d['strokeColor']
                    ET.SubElement(drawing,'opacity').text = str(d['strokeAlpha'])
                    ET.SubElement(drawing,'fillColor').text = d['fillColor']

                    points = []
                    for p in d['points']:
                        points.append(str(p[0]*map["rescale"]))
                        points.append(str(p[1]*map["rescale"]))
                    ET.SubElement(drawing,'data').text = ",".join(points)

        if 'sounds' in map and len(map['sounds']) > 0:
            for s in map['sounds']:
                marker = ET.SubElement(mapentry,'marker')
                ET.SubElement(marker,'name').text = ""#"Sound: " + os.path.splitext(os.path.basename(s["path"]))[0]
                ET.SubElement(marker,'label').text = "🔊"
                ET.SubElement(marker,'type').text = "circle"
                ET.SubElement(marker,'x').text = str(round((s['x']-map["offsetX"])*map["rescale"]))
                ET.SubElement(marker,'y').text = str(round((s['y']-map["offsetY"])*map["rescale"]))
                ET.SubElement(marker,'hidden').text = 'YES'
                ET.SubElement(marker,'content', { 'ref': "/page/{}".format(str(uuid.uuid5(moduuid,s['_id']))) })
                page = ET.SubElement(module,'page', { 'id': str(uuid.uuid5(moduuid,s['_id'])), 'parent': str(uuid.uuid5(moduuid,map['_id'])) } )
                ET.SubElement(page,'name').text = map["name"] + " Sound: " + os.path.splitext(os.path.basename(s["path"]))[0]
                ET.SubElement(page,'slug').text = slugify(map["name"] + " Sound: " + os.path.splitext(os.path.basename(s["path"]))[0])
                content = ET.SubElement(page,'content')
                content.text = "<h1>Sound: {}</h1>".format(s['name'] if 'name' in s else os.path.splitext(os.path.basename(s['path']))[0])
                content.text += '<figure id={}>'.format(s['_id'])
                content.text += '<figcaption>{}</figcaption>'.format(s['name'] if 'name' in s else os.path.splitext(os.path.basename(s['path']))[0])
                if os.path.exists(s['path']):
                    if magic.from_file(os.path.join(tempdir,urllib.parse.unquote(s['path'])),mime=True) not in ["audio/mp3","audio/mpeg","audio/wav","audio/mp4","video/mp4"]:
                        try:
                            ffp = subprocess.Popen([ffmpeg_path,'-v','error','-i',s["path"],'-acodec','aac',os.path.splitext(s["path"])[0]+".mp4"],startupinfo=startupinfo, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
                            ffp.wait()
                            os.remove(s["path"])
                            s["path"] = os.path.splitext(s["path"])[0]+".mp4"
                        except Exception:
                            print ("Could not convert to MP4")
                    content.text += '<audio controls {}><source src="{}" type="{}"></audio>'.format(" loop" if s['repeat'] else "",s['path'],magic.from_file(os.path.join(tempdir,urllib.parse.unquote(s['path'])),mime=True))
                else:
                    content.text += '<audio controls {}><source src="{}"></audio>'.format(" loop" if s['repeat'] else "",s['path'])
                content.text += '</figure>'

        return mapslug
    global tempdir
    if not tempdir:
        tempdir = tempfile.mkdtemp(prefix="convertfoundry_")
    nsuuid = uuid.UUID("ee9acc6e-b94a-472a-b44d-84dc9ca11b87")
    if args.srcfile.startswith("http"):
        urllib.request.urlretrieve(args.srcfile,os.path.join(tempdir,"manifest.json"))
        with open(os.path.join(tempdir,"manifest.json")) as f:
            manifest = json.load(f)
        if 'download' in manifest:
            def progress(block_num, block_size, total_size):
                pct = 100.00*((block_num * block_size)/total_size)
                print("\rDownloading module {:.2f}%".format(pct),file=sys.stderr,end='')
            urllib.request.urlretrieve(manifest['download'],os.path.join(tempdir,"module.zip"),progress)
            print("\r".format(pct),file=sys.stderr,end='')
            args.srcfile = os.path.join(tempdir,"module.zip")

    with zipfile.ZipFile(args.srcfile) as z:
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
                with z.open(filename) as f:
                    mod = json.load(f)
                isworld = True
            elif not mod and os.path.basename(filename) == "module.json":
                with z.open(filename) as f:
                    mod = json.load(f)
            elif os.path.basename(os.path.dirname(filename)) == 'data' and os.path.basename(filename) == 'folders.db':
                with z.open(filename) as f:
                    l = f.readline().decode('utf8')
                    while l:
                        folder = json.loads(l)
                        folders.append(folder)
                        l = f.readline().decode('utf8')
                    f.close()
            elif os.path.basename(os.path.dirname(filename)) == 'data' and os.path.basename(filename) == 'journal.db':
                with z.open(filename) as f:
                    l = f.readline().decode('utf8')
                    while l:
                        jrn = json.loads(l)
                        journal.append(jrn)
                        l = f.readline().decode('utf8')
                    f.close()
            elif os.path.basename(os.path.dirname(filename)) == 'data' and os.path.basename(filename) == 'scenes.db':
                with z.open(filename) as f:
                    l = f.readline().decode('utf8')
                    while l:
                        scene = json.loads(l)
                        maps.append(scene)
                        l = f.readline().decode('utf8')
                    f.close()
            elif os.path.basename(os.path.dirname(filename)) == 'data' and os.path.basename(filename) == 'actors.db':
                with z.open(filename) as f:
                    l = f.readline().decode('utf8')
                    while l:
                        actor = json.loads(l)
                        actors.append(actor)
                        l = f.readline().decode('utf8')
                    f.close()
            elif os.path.basename(os.path.dirname(filename)) == 'data' and os.path.basename(filename) == 'items.db':
                with z.open(filename) as f:
                    l = f.readline().decode('utf8')
                    while l:
                        item = json.loads(l)
                        items.append(item)
                        l = f.readline().decode('utf8')
                    f.close()
            elif os.path.basename(os.path.dirname(filename)) == 'data' and os.path.basename(filename) == 'tables.db':
                with z.open(filename) as f:
                    l = f.readline().decode('utf8')
                    while l:
                        table = json.loads(l)
                        tables.append(table)
                        l = f.readline().decode('utf8')
                    f.close()
            elif os.path.basename(os.path.dirname(filename)) == 'data' and os.path.basename(filename) == 'playlists.db':
                with z.open(filename) as f:
                    l = f.readline().decode('utf8')
                    while l:
                        playlist = json.loads(l)
                        playlists.append(playlist)
                        l = f.readline().decode('utf8')
                    f.close()
        if not isworld and mod:
            for pack in mod['packs']:
                pack['path'] = pack['path'][1:] if os.path.isabs(pack['path']) else pack['path']
                if any(x.startswith("{}/".format(mod['name'])) for x in z.namelist()):
                    pack['path'] = mod['name']+'/'+pack['path']
                with z.open(pack['path']) as f:
                    l = f.readline().decode('utf8')
                    while l:
                        if pack['entity'] == 'JournalEntry':
                            jrn = json.loads(l)
                            journal.append(jrn)
                        elif pack['entity'] == 'Scene':
                            scene = json.loads(l)
                            maps.append(scene)
                        elif pack['entity'] == 'Actor':
                            actor = json.loads(l)
                            actors.append(actor)
                        l = f.readline().decode('utf8')
                    f.close()
        if not mod and args.packdir:
            mod = { "title": os.path.splitext(os.path.basename(args.srcfile))[0].title(),
                    "name": slugify(os.path.splitext(os.path.basename(args.srcfile))[0]),
                    "version": 1,
                    "description": ""
                    }
        elif not mod:
            print("No foundry data was found in this zip file.")
            return
        print(mod["title"])
        global moduuid
        if isworld:
            moduletmp = os.path.join(tempdir,"worlds")
        else:
            moduletmp = os.path.join(tempdir,"modules")
        os.mkdir(moduletmp)
        if not any(x.startswith("{}/".format(mod['name'])) for x in z.namelist()):
            os.mkdir(os.path.join(moduletmp,mod['name']))
            z.extractall(path=os.path.join(moduletmp,mod['name']))
        else:
            z.extractall(path=moduletmp)
    if os.path.exists(os.path.join(tempdir,"module.zip")):
        os.remove(os.path.join(tempdir,"module.zip"))
        os.remove(os.path.join(tempdir,"manifest.json"))
    moduuid = uuid.uuid5(nsuuid,mod["name"])
    slugs = []
    if args.packdir:
        if not args.packdir.startswith("{}/".format(mod['name'])):
            args.packdir = os.path.join(mod['name'],args.packdir)
        args.packdir = os.path.join(moduletmp,args.packdir)
        module = ET.Element(
            'pack', { 'id': str(moduuid),'version': "{}".format(mod['version']) } )
    else:
        module = ET.Element(
            'module', { 'id': str(moduuid),'version': "{}".format(mod['version']) } )
    name = ET.SubElement(module, 'name')
    name.text = mod['title']
    author = ET.SubElement(module, 'author')
    if 'author' not in mod:
        mod['author'] = ""
    author.text = mod['author']
    if type(mod['author']) == list:
        author.text = ", ".join(mod['author'])
    category = ET.SubElement(module, 'category')
    if args.packdir:
        category.text = "personal"
    else:
        category.text = "adventure"
    code = ET.SubElement(module, 'code')
    code.text = mod['name']
    slug = ET.SubElement(module, 'slug')
    slug.text = slugify(mod['title'])
    description = ET.SubElement(module, 'description')
    description.text = re.sub(r'<.*?>','',html.unescape(mod['description']))
    modimage = ET.SubElement(module, 'image')
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
        packdir = os.path.join(tempdir,"packdir")
        os.mkdir(packdir)
        packroot = [folder for folder in os.listdir(args.packdir) if os.path.isdir(os.path.join(args.packdir,folder))]
        packroot.append('.')
        pos = 0.00
        if sys.platform == "win32":
            args.packdir = args.packdir.replace("/","\\")
        for root,dirs,files in os.walk(args.packdir):
            if args.gui:
                worker.updateProgress((pos/len(packroot))*70)
            groupname = os.path.relpath(root, start=args.packdir)
            if groupname != '.':
                if args.gui:
                    worker.outputLog("Creating group "+groupname.title())
                sort += 1
                groupid = str(uuid.uuid5(moduuid,slugify(os.path.relpath(root, start=args.packdir))))
                group = ET.SubElement(module, 'group', {'id': groupid, 'sort': str(int(sort))})
                ET.SubElement(group, 'name').text = groupname.title()
                ET.SubElement(group, 'slug').text = slugify(groupname)
            else:
                groupid = None
            for f in files:
                pos += 1.00/len(files)
                image = os.path.join(root,f)
                if not re.match(r'(image/.*?|video/webm)',magic.from_file(image,mime=True)):
                    print("\r - Skipping",f,file=sys.stderr,end='')
                    sys.stderr.write("\033[K")
                    sys.stderr.flush()
                    continue
                print("\r Adding",f,file=sys.stderr,end='')
                sys.stderr.write("\033[K")
                sys.stderr.flush()
                if args.gui:
                    worker.outputLog(" adding "+f)
                    worker.updateProgress((pos/len(packroot))*70)
                if groupid:
                    asset = ET.SubElement(module,'asset', { 'id': str(uuid.uuid5(moduuid,os.path.relpath(image, start=tempdir))), 'parent': groupid})
                else:
                    asset = ET.SubElement(module,'asset', { 'id': str(uuid.uuid5(moduuid,os.path.relpath(image, start=tempdir))) })
                ET.SubElement(asset,'name').text = os.path.splitext(os.path.basename(image))[0]
                imgext = os.path.splitext(os.path.basename(image))[1]
                if imgext == ".webm":
                    try:
                        if os.path.exists(image):
                            if args.gui:
                                worker.outputLog(" - Converting webm tile to spritesheet")
                            probe = ffprobe(image)
                            if probe['codec_name'] != 'vp9':
                                ffp = subprocess.Popen([ffmpeg_path,'-v','error','-i',image,os.path.splitext(image)[0]+"-frame%05d.png"],startupinfo=startupinfo, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
                            else:
                                ffp = subprocess.Popen([ffmpeg_path,'-v','error','-vcodec','libvpx-vp9','-i',image,os.path.splitext(image)[0]+"-frame%05d.png"],startupinfo=startupinfo, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
                            ffp.wait()
                            duration = probe['duration']
                            framewidth = probe['width']
                            frameheight = probe['height']
                            frames = []
                            for afile in os.listdir(os.path.dirname(image)):
                                if re.match(re.escape(os.path.splitext(os.path.basename(image))[0])+"-frame[0-9]{5}\.png",afile):
                                    frames.append(os.path.join(os.path.dirname(image),afile))
                            def getGrid(n):
                                i = 1
                                factors = []
                                while(i < n+1):
                                    if n % i == 0:
                                        factors.append(i)
                                    i += 1
                                gw = factors[len(factors)//2]
                                gh = factors[(len(factors)//2)-1]
                                if gw*framewidth > 4096 or gh*frameheight > 4096:
                                    return (gh,gw)
                                else:
                                    return (gw,gh)
                            (gw,gh) = getGrid(len(frames))
                            with PIL.Image.new('RGBA', (round(framewidth*gw), round(frameheight*gh)), color = (0,0,0,0)) as img:
                                px = 0
                                py = 0
                                for i in range(len(frames)):
                                    img.paste(PIL.Image.open(frames[i]),(framewidth*px,frameheight*py))
                                    os.remove(frames[i])
                                    px += 1
                                    if px == gw:
                                        px = 0
                                        py += 1
                                if img.width > 4096 or img.height > 4096:
                                    scale = 4095/img.width if img.width>=img.height else 4095/img.height
                                    img = img.resize((round(img.width*scale),round(img.height*scale)))
                                    framewidth = round(framewidth*scale)
                                    frameheight = round(frameheight*scale)
                                img.save(os.path.splitext(image)[0]+"-sprite.png")
                            os.remove(image)
                        if os.path.exists(os.path.splitext(image)[0]+"-sprite.png"):
                            ET.SubElement(asset,'type').text = "spriteSheet"
                            ET.SubElement(asset,'frameWidth').text = str(framewidth)
                            ET.SubElement(asset,'frameHeight').text = str(frameheight)
                            ET.SubElement(asset,'duration').text = str(duration)
                            image = os.path.splitext(os.path.basename(image, start=tempdir))[0]+"-sprite.png"
                            if os.path.exists(os.path.join(packdir,os.path.basenamne(image))):
                                exist_count = 1
                                image_name,image_ext = os.path.splitext(image)
                                while os.path.exists(os.path.join(packdir,os.path.basename("{}{}{}".format(image_name,exist_count,image_ext)))):
                                    exist_count += 1
                                newimage = "{}{}{}".format(image_name,exist_count,image_ext)
                            else:
                                newimage = image
                            shutil.copy(image,os.path.join(packdir,os.path.basename(newimage)))
                            ET.SubElement(asset,'resource').text = os.path.basename(newimage)
                        continue
                    except Exception:
                        import traceback
                        print(traceback.format_exc())
                        if args.gui:
                            worker.outputLog(" - webm tiles are not supported, consider converting to a spritesheet: "+image)
                        print(" - webm tiles are not supported, consider converting to a spritesheet:",image,file=sys.stderr,end='')
                    continue
                else:
                    ET.SubElement(asset,'type').text = "image"
                with PIL.Image.open(image) as img:
                    if imgext == ".webp" and args.jpeg != ".webp":
                        if img.width > 4096 or img.height > 4096:
                            scale = 4095/img.width if img.width>=img.height else 4095/img.height
                            img = img.resize((round(img.width*scale),round(img.height*scale)))
                        if args.gui:
                            worker.outputLog(" - Converting tile from webp to png")
                        img.save(os.path.join(tempdir,os.path.splitext(image)[0]+".png"))
                        os.remove(image)
                        image = os.path.join(tempdir,os.path.splitext(image)[0]+".png")
                    else:
                        if img.width > 4096 or img.height > 4096:
                            scale = 4095/img.width if img.width>=img.height else 4095/img.height
                            img = img.resize((round(img.width*scale),round(img.height*scale)))
                            img.save(os.path.join(tempdir,image))
                if os.path.exists(os.path.join(packdir,os.path.basename(image))):
                    exist_count = 1
                    image_name,image_ext = os.path.splitext(image)
                    while os.path.exists(os.path.join(packdir,os.path.basename("{}{}{}".format(image_name,exist_count,image_ext)))):
                        exist_count += 1
                    newimage = "{}{}{}".format(image_name,exist_count,image_ext)
                else:
                    newimage = image
                shutil.copy(image,os.path.join(packdir,os.path.basename(newimage)))
                ET.SubElement(asset,'resource').text = os.path.basename(newimage)
                if not modimage.text and "preview" in f.lower():
                    modimage.text = os.path.basename(newimage)
    for f in folders:
        f['sort'] = sort if 'sort' not in f or f['sort'] == None else f['sort']
        if f['sort'] > maxorder:
            maxorder = f['sort']
        sort += 1
    sort = 0
    for j in journal:
        j['sort'] = sort if 'sort' not in j or j['sort'] == None else j['sort']
        if 'flags' in j and 'R20Converter' in j['flags'] and 'handout-order' in j['flags']['R20Converter']:
            j['sort'] += j['flags']['R20Converter']['handout-order']
        if j['sort'] > maxorder:
            maxorder = j['sort']
        sort += 1
    sort = 0
    for m in maps:
        m['sort'] = sort if 'sort' not in m or m['sort'] == None else m['sort']
        if m['sort'] and m['sort'] > maxorder:
            maxorder = m['sort']
        sort += 1
    if args.gui and len(folders)>0:
        worker.outputLog("Converting folders")
    for f in folders:
        order += 1
        if args.gui:
            worker.updateProgress((order/len(folders))*5)
        print("\rCreating Folders [{}/{}] {:.0f}%".format(order,len(folders),order/len(folders)*100),file=sys.stderr,end='')
        if f['type'] not in ["JournalEntry","RollTable"]:
            continue
        folder = ET.SubElement(module,'group', { 'id': str(uuid.uuid5(moduuid,f['_id'])), 'sort': str(int(f['sort'])) } )
        ET.SubElement(folder,'name').text = f['name']
        if f['parent'] != None:
            folder.set('parent',f['parent'])
    order = 0
    if len(journal)>0 and args.gui:
        worker.outputLog("Converting journal")
    for j in journal:
        order += 1
        if args.gui:
            worker.updateProgress(5+(order/len(journal))*10)
        if '$$deleted' in j and j['$$deleted']:
            continue
        print("\rConverting journal [{}/{}] {:.0f}%".format(order,len(journal),order/len(journal)*100),file=sys.stderr,end='')
        page = ET.SubElement(module,'page', { 'id': str(uuid.uuid5(moduuid,j['_id'])), 'sort': str(j['sort'] or order) } )
        if 'folder' in j and j['folder'] != None:
            page.set('parent',j['folder'])
        ET.SubElement(page,'name').text = j['name']
        ET.SubElement(page,'slug').text = slugify(j['name'])
        content = ET.SubElement(page,'content')
        content.text = j['content'] or ""
        def fixLink(m):
            if m.group(2) == "JournalEntry":
                return '<a href="/page/{}" {} {} {}>'.format(str(uuid.uuid5(moduuid,m.group(4))),m.group(1),m.group(3),m.group(5))
            if m.group(2) == "Actor":
                for a in actors:
                    if a['_id'] == m.group(4):
                        return '<a href="/monster/{}" {} {} {}>'.format(slugify(a['name']),m.group(1),m.group(3),m.group(5))
            return m.group(0)
        content.text = re.sub(r'<a(.*?)data-entity="?(.*?)"? (.*?)data-id="?(.*?)"?( .*?)?>',fixLink,content.text)
        def fixFTag(m):
            if m.group(1) == "JournalEntry":
                return '<a href="/page/{}">{}</a>'.format(str(uuid.uuid5(moduuid,m.group(2))),m.group(3) or "Journal Entry")
            if m.group(1) == "RollTable":
                return '<a href="/page/{}">{}</a>'.format(str(uuid.uuid5(moduuid,m.group(2))),m.group(3) or "Roll Table")
            if m.group(1) == "Scene":
                return '<a href="/map/{}">{}</a>'.format(str(uuid.uuid5(moduuid,m.group(2))),m.group(3) or "Map")
            if m.group(1) == "Actor":
                for a in actors:
                    if a['_id'] == m.group(2):
                        return '<a href="/monster/{}">{}</a>'.format(slugify(a['name']),m.group(3) or a['name'],m.group(3))
            if m.group(1) == "Compendium" and m.group(3):
                (system,entrytype,idnum) = m.group(2).split('.',3)
                return '<a href="/{}/{}">{}</a>'.format(entrytype,slugify(m.group(3)),m.group(3))
            if m.group(1) == "Item":
                for i in items:
                    if i['_id'] == m.group(2):
                        return '<a href="/item/{}">{}</a>'.format(slugify(i['name']),m.group(3) or i['name'])
            if m.group(1) == "Macro":
                if m.group(3):
                    return '<details><summary>{}</summary>This was a Foundry Macro, which cannot be converted.</details>'.format(m.group(3))
                else:
                    return '<details><summary>Unsupported</summary>This was a Foundry Macro, which cannot be converted.</details>'
            return m.group(0)
        content.text = re.sub(r'@(.*?)\[(.*?)\](?:\{(.*?)\})?',fixFTag,content.text)
        content.text = re.sub(r'\[\[(?:/(?:gm)?r(?:oll)? )?(.*?)(?: ?# ?(.*?))?\]\]',fixRoll,content.text)
        if 'img' in j and j['img']:
            content.text += '<img src="{}">'.format(j["img"])
    order = 0
    if len(playlists) > 0:
        if args.gui:
            worker.outputLog("Converting playlists")
        playlistsbaseslug = 'playlists'
        playlistsslug = playlistsbaseslug + str(len([i for i in slugs if playlistsbaseslug in i]))
        playlistsgroup = str(uuid.uuid5(moduuid,playlistsslug))
        group = ET.SubElement(module, 'group', {'id': playlistsgroup, 'sort': str(int(maxorder+1))})
        ET.SubElement(group, 'name').text = "Playlists"
        ET.SubElement(group, 'slug').text = playlistsslug
    for p in playlists:
        order += 1
        if args.gui:
            worker.updateProgress(15+(order/len(playlists))*10)
        if '$$deleted' in p and p['$$deleted']:
            continue
        print("\rConverting playlists [{}/{}] {:.0f}%".format(order,len(playlists),order/len(playlists)*100),file=sys.stderr,end='')
        page = ET.SubElement(module,'page', { 'id': str(uuid.uuid5(moduuid,p['_id'])), 'parent': playlistsgroup, 'sort': str(p['sort'] if 'sort' in p and p['sort'] else order) } )
        ET.SubElement(page,'name').text = p['name']
        ET.SubElement(page,'slug').text = slugify(p['name'])
        content = ET.SubElement(page,'content')
        content.text = "<h1>{}</h1>".format(p['name'])
        content.text += "<table><thead><tr><td>"
        content.text += "Track"
        content.text += '</td>'
        content.text += "</tr></thead><tbody>"
        for s in p['sounds']:
            content.text += '<tr>'
            content.text += '<td><figure>'
            content.text += '<figcaption>{}</figcaption>'.format(s['name'])
            if os.path.exists(s['path']):
                if magic.from_file(os.path.join(tempdir,urllib.parse.unquote(s['path'])),mime=True) not in ["audio/mp3","audio/mpeg","audio/wav","audio/mp4","video/mp4"]:
                    try:
                        ffp = subprocess.Popen([ffmpeg_path,'-v','error','-i',s["path"],'-acodec','aac',os.path.splitext(s["path"])[0]+".mp4"],startupinfo=startupinfo, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
                        ffp.wait()
                        s["path"] = os.path.splitext(s["path"])[0]+".mp4"
                    except Exception:
                        print ("Could not convert to MP4")
                content.text += '<audio controls {}><source src="{}" type="{}"></audio>'.format(" loop" if s['repeat'] else "",s['path'],magic.from_file(os.path.join(tempdir,urllib.parse.unquote(s['path'])),mime=True))
            else:
                content.text += '<audio controls {}><source src="{}"></audio>'.format(" loop" if s['repeat'] else "",s['path'])
            content.text += '</figure></td>'
            content.text += '</tr>'
        content.text += "</tbody></table>"
    order = 0
    if len(tables) > 0:
        if args.gui:
            worker.outputLog("Converting roll tables")
        tablesbaseslug = 'tables'
        tablesslug = tablesbaseslug + str(len([i for i in slugs if tablesbaseslug in i]))
        tablesgroup = str(uuid.uuid5(moduuid,tablesslug))
        group = ET.SubElement(module, 'group', {'id': tablesgroup, 'sort': str(int(maxorder+1))})
        ET.SubElement(group, 'name').text = "Roll Tables"
        ET.SubElement(group, 'slug').text = tablesslug
    for t in tables:
        order += 1
        if args.gui:
            worker.updateProgress(25+(order/len(tables))*10)
        if '$$deleted' in t and t['$$deleted']:
            continue
        print("\rConverting tables [{}/{}] {:.0f}%".format(order,len(tables),order/len(tables)*100),file=sys.stderr,end='')
        page = ET.SubElement(module,'page', { 'id': str(uuid.uuid5(moduuid,t['_id'])), 'parent': tablesgroup, 'sort': str(t['sort'] if 'sort' in t and t['sort'] else order) } )
        ET.SubElement(page,'name').text = t['name']
        ET.SubElement(page,'slug').text = slugify(t['name'])
        content = ET.SubElement(page,'content')
        content.text = "<h1>{}</h1>".format(t['name'])
        content.text += "<table><thead><tr><td>"
        content.text += '<a href="/roll/{0}/{1}">{0}</a>'.format(t['formula'],t['name'])
        content.text += '</td><td colspan="2" align="center">{}</td>'.format(t['name'])
        content.text += "</tr></thead><tbody>"
        for r in t['results']:
            content.text += '<tr>'
            content.text += '<td>{}</td>'.format("{}-{}".format(*r['range']) if r['range'][0]!=r['range'][1] else r['range'][0])
            content.text += '<td>'
            linkMade = False
            if 'collection' in r:
                if r['collection'] == 'dnd5e.monsters':
                    content.text += '<a href="/monster/{}">{}</a>'.format(slugify(r['text']),r['text'])
                    linkMade = True
                elif r['collection'] == 'Actor':
                    for a in actors:
                        if a['_id'] == r['resultId']:
                            content.text += '<a href="/monster/{}">{}</a>'.format(slugify(a['name']),r['text'])
                            linkMade = True
                elif r['collection'] == 'Item':
                    for i in items:
                        if i['_id'] == r['resultId']:
                            content.text += '<a href="/item/{}">{}</a>'.format(slugify(i['name']),r['text'])
                            linkMade = True
            if not linkMade:
                content.text += '{}'.format(r['text'] if r['text'] else '&nbsp;')
            content.text += '</td>'
            if 'img' in r and os.path.exists(r['img']):
                content.text += '<td style="width:50px;height:50px;"><img src="{}"></td>'.format(r['img'])
            else:
                content.text += '<td style="width:50px;height:50px;">&nbsp;</td>'
            content.text += '</tr>'
        content.text += "</tbody></table>"
        content.text = re.sub(r'\[\[(?:/(?:gm)?r(?:oll)? )?(.*?)(?: ?# ?(.*?))?\]\]',fixRoll,content.text)

    mapcount = 0
    if len(maps) > 0:
        if args.gui:
            worker.outputLog("Converting maps")
        mapsbaseslug = 'maps'
        mapsslug = mapsbaseslug + str(len([i for i in slugs if mapsbaseslug in i]))
        mapgroup = str(uuid.uuid5(moduuid,mapsslug))
        group = ET.SubElement(module, 'group', {'id': mapgroup, 'sort': str(int(maxorder+2))})
        ET.SubElement(group, 'name').text = "Maps"
        ET.SubElement(group, 'slug').text = mapsslug
        for map in maps:
            if '$$deleted' in map and map['$$deleted']:
                continue
            if not modimage.text and map["name"].lower() in ["intro","start","start here","title page","title","landing","landing page"]:
                if args.gui:
                    worker.outputLog("Generating cover image")
                print("\rGenerating cover image",file=sys.stderr,end='')
                if not os.path.exists(urllib.parse.unquote(map["img"] or map["tiles"][0]["img"])):
                    if os.path.exists(os.path.splitext(urllib.parse.unquote(map["img"] or map["tiles"][0]["img"]))[0]+args.jpeg):
                        map["img"] = os.path.splitext(map["img"])[0]+args.jpeg
                with PIL.Image.open(urllib.parse.unquote(map["img"] or map["tiles"][0]["img"])) as img:
                    if img.width >= img.width:
                        img.crop((0,0,img.width,img.width))
                    else:
                        img.crop((0,0,img.height,img.height))
                    if img.width > 1024:
                        img.resize((1024,1024))
                    if args.jpeg == ".jpg" and img.mode in ("RGBA", "P"): img = img.convert("RGB")
                    img.save(os.path.join(tempdir,"module_cover" + args.jpeg))
                modimage.text = "module_cover" + args.jpeg
            if not map["img"] and len(map["tiles"]) == 0:
                continue
            mapcount += 1
            sys.stderr.write("\033[K")
            if args.gui:
                worker.updateProgress(35+(mapcount/len(maps))*35)
            print("\rConverting maps [{}/{}] {:.0f}%".format(mapcount,len(maps),mapcount/len(maps)*100),file=sys.stderr,end='')
            createMap(map,mapgroup)
    if not modimage.text and len(maps) > 0:
        map = random.choice(maps)
        while '$$deleted' in map and mapcount > 0:
            map = random.choice(maps)
        if args.gui:
            worker.outputLog("Generating cover image")
        print("\rGenerating cover image",file=sys.stderr,end='')
        if not os.path.exists(urllib.parse.unquote(map["img"] or map["tiles"][0]["img"])):
            if os.path.exists(os.path.splitext(urllib.parse.unquote(map["img"] or map["tiles"][0]["img"]))[0]+args.jpeg):
                map["img"] = os.path.splitext(map["img"])[0]+args.jpeg
        with PIL.Image.open(map["img"] or map["tiles"][0]["img"]) as img:
            if img.width >= img.width:
                img.crop((0,0,img.width,img.width))
            else:
                img.crop((0,0,img.height,img.height))
            if img.width > 1024:
                img.resize((1024,1024))
            if args.jpeg == ".jpg" and img.mode in ("RGBA", "P"): img = img.convert("RGB")
            img.save(os.path.join(tempdir,"module_cover" + args.jpeg))
        modimage.text = "module_cover" + args.jpeg
    # write to file
    sys.stderr.write("\033[K")
    if args.gui:
        worker.updateProgress(70)
        if args.packdir:
            worker.outputLog("Generating pack.xml")
        else:
            worker.outputLog("Generating module.xml")
    print("\rWriting XML",file=sys.stderr,end='')
    tree = ET.ElementTree(indent(module, 1))
    tree.write(os.path.join(packdir if args.packdir else tempdir,"pack.xml" if args.packdir else "module.xml"), xml_declaration=True, short_empty_elements=False, encoding='utf-8')
    if 'styles' in mod:
        if not os.path.exists(os.path.join(tempdir,"assets")):
            os.mkdir(os.path.join(tempdir,"assets"))
        if not os.path.exists(os.path.join(tempdir,"assets","css")):
            os.mkdir(os.path.join(tempdir,"assets","css"))
        for style in mod['styles']:
            if os.path.exists(os.path.join(moduletmp,mod["name"],style)):
                with open(os.path.join(tempdir,"assets","css","custom.css"),"a") as f:
                    with open(os.path.join(moduletmp,mod["name"],style)) as css:
                        for l in css:
                            f.write(l)
        if os.path.exists(os.path.join(moduletmp,mod["name"],"fonts")):
            os.rename(os.path.join(moduletmp,mod["name"],"fonts"),os.path.join(tempdir,"assets","fonts"))

    if args.compendium and (len(items)+len(actors)) > 0:
        if args.gui:
            worker.updateProgress(75)
            worker.outputLog("Generating compendium data")
        def fixHTMLContent(text):
            text = re.sub(r'<a(.*?)data-entity="?(.*?)"? (.*?)data-id="?(.*?)"?( .*?)?>',fixLink,text)
            text = re.sub(r'<h([0-9]).*?>(.*?)</h\1>',r'<b>\2</b>\n',text)
            text = re.sub(r'<em.*?>(.*?)</em>',r'<i>\1</i>',text)
            text = re.sub(r'<strong.*?>(.*?)</strong>',r'<b>\1</b>',text)
            text = re.sub(r'<blockquote.*?>(.*?)</blockquote>',r'-------------\n\1-------------\n',text)
            text = re.sub(r'<img(.*?)src="?(.*?)"?( .*?)?>',r'<a\1href="\2"\3>Image</a>',text)
            text = re.sub(r'<tr.*?><td.*?>(.*?)</td>',r'\1',text)
            text = re.sub(r'<td.*?>(.*?)</td>',r' | \1',text)
            text = re.sub(r'</tr>','\n',text)
            text = re.sub(r'</?p.*?>','',text)
            text = re.sub(r'<br.*?>','\n',text)
            text = re.sub(r'<hr.*?>','------------------------\n',text)
            text = re.sub(r'\[\[(?:/(?:gm)?r(?:oll)? )?(.*?)(?: ?# ?(.*?))?\]\]',fixRoll,text)
            return html.unescape(text)
        compendium = ET.Element('compendium')
        os.mkdir(os.path.join(tempdir,"items"))
        os.mkdir(os.path.join(tempdir,"monsters"))
        itemnumber = 0
        for i in items:
            itemnumber += 1
            if args.gui:
                worker.updateProgress(75+(itemnumber/(len(items)+len(actors)))*10)
            print("\rGenerating compendium [{}/{}]".format(itemnumber,len(items)+len(actors)),file=sys.stderr,end='')
            if i['type'] in ['feat','spell']:
                continue
            item = ET.SubElement(compendium,'item',{'id': str(uuid.uuid5(moduuid,i['_id']))})
            d = i['data']
            ET.SubElement(item,'name').text = i['name']
            ET.SubElement(item,'slug').text = slugify(i['name'])
            if 'weight' in d and d['weight']:
                ET.SubElement(item,'weight').text = str(d['weight'])
            if 'rarity' in d and d['rarity']:
                ET.SubElement(item,'rarity').text = d['rarity'].title()
            if 'price' in d and d['price']:
                value = ET.SubElement(item,'value')
                if d['price'] >= 100:
                    value.text = "{:g} gp".format(d['price']/100)
                elif d['price'] >= 10:
                    value.text = "{:g} sp".format(d['price']/10)
                else:
                    value.text = "{:g} cp".format(d['price'])
            if i['type'] in ['consumable']:
                if d['consumableType'] == 'potion':
                    ET.SubElement(item,'type').text = 'P'
                elif d['consumableType'] == 'wand':
                    ET.SubElement(item,'type').text = 'WD'
                elif d['consumableType'] == 'scroll':
                    ET.SubElement(item,'type').text = 'SC'
                elif d['consumableType'] == 'food':
                    ET.SubElement(item,'type').text = 'G'
                else:
                    print("Dont know consumable:",d['consumableType'])
                    ET.SubElement(item,'type').text = 'G'
            elif i['type'] in ['equipment']:
                if d['armor']['type'] in ['clothing']:
                    ET.SubElement(item,'type').text = 'LA'
                elif d['armor']['type'] in ['medium']:
                    ET.SubElement(item,'type').text = 'MA'
                elif d['armor']['type'] in ['shield']:
                    ET.SubElement(item,'type').text = 'S'
                elif d['armor']['type'] in ['trinket']:
                    ET.SubElement(item,'type').text = 'G'
                else:
                    print("Dont know armor type:",d['armor']['type'])
                    ET.SubElement(item,'type').text = 'AA'
                if d['armor']['value']:
                    ET.SubElement(item,'ac').text = str(d['armor']['value'])
            elif i['type'] == "weapon":
                if d['weaponType'] in ["simpleR","martialR"]:
                    ET.SubElement(item,'type').text = 'R'
                    ET.SubElement(item,'range').text = "{}/{} {}".format(d['range']['value'],d['range']['long'],d['range']['units'])
                elif d['weaponType'] in ["simpleM","martialM"]:
                    ET.SubElement(item,'type').text = 'M'
                elif 'staff' in d and d['staff']:
                    ET.SubElement(item,'type').text = 'ST'
                else:
                    if d['weaponType'] not in ['natural']:
                        print("Dont know weapon:",d['weaponType'])
                    ET.SubElement(item,'type').text = 'WW'
                props = []
                for prop in d['properties'].keys():
                    if prop == 'amm':
                        props.append('A')
                    if prop == 'fin':
                        props.append('F')
                    if prop == 'hvy':
                        props.append('H')
                    if prop == 'lgt':
                        props.append('L')
                    if prop == 'lod':
                        props.append('LD')
                    if prop == 'rch':
                        props.append('R')
                    if prop == 'spc':
                        props.append('S')
                    if prop == 'thr':
                        props.append('T')
                    if prop == 'two':
                        props.append('2H')
                    if prop == 'ver':
                        props.append('V')
                ET.SubElement(item,'property').text = ','.join(props)
                if d['damage']['parts']:
                    ET.SubElement(item,'dmg1').text = d['damage']['parts'][0][0]
                    if d['damage']['parts'][0][1]:
                        ET.SubElement(item,'dmgType').text = d['damage']['parts'][0][1][0].upper()
                if d['damage']['versatile']:
                    ET.SubElement(item,'dmg2').text = d['damage']['versatile']
            elif i['type'] == "loot":
                ET.SubElement(item,'type').text = 'G'
            else:
                print("Dont know item type",i['type'])
            ET.SubElement(item,'text').text=fixHTMLContent(d['description']['value'])
            if i['img']: i['img'] = urllib.parse.unquote(i['img'])
            if i['img'] and os.path.exists(i['img']):
                ET.SubElement(item,'image').text = slugify(i['name'])+"_"+os.path.basename(i['img'])
                shutil.copy(i['img'],os.path.join(tempdir,"items",slugify(i['name'])+"_"+os.path.basename(i['img'])))
        for a in actors:
            itemnumber += 1
            if args.gui:
                worker.updateProgress(75+(itemnumber/(len(items)+len(actors)))*10)
            print("\rGenerating compendium [{}/{}]".format(itemnumber,len(items)+len(actors)),file=sys.stderr,end='')
            monster = ET.SubElement(compendium,'monster',{'id': str(uuid.uuid5(moduuid,a['_id']))})
            d = a['data']
            ET.SubElement(monster,'name').text = a['name']
            ET.SubElement(monster,'slug').text = slugify(a['name'])
            ET.SubElement(monster,'size').text = d['traits']['size'][0].upper()
            if 'type' in d['details']:
                ET.SubElement(monster,'type').text = d['details']['type']
            if 'alignment' in d['details']:
                ET.SubElement(monster,'alignment').text = d['details']['alignment']
            ET.SubElement(monster,'ac').text = str(d['attributes']['ac']['value'])
            if 'formula' in d['attributes']['hp'] and d['attributes']['hp']['formula']:
                ET.SubElement(monster,'hp').text = "{} ({})".format(d['attributes']['hp']['value'],d['attributes']['hp']['formula'])
            else:
                ET.SubElement(monster,'hp').text = "{}".format(d['attributes']['hp']['value'])
            if 'speed' in d['attributes']:
                if d['attributes']['speed']['special']:
                    ET.SubElement(monster,'speed').text = d['attributes']['speed']['value']+", "+d['attributes']['speed']['special']
                else:
                    ET.SubElement(monster,'speed').text = d['attributes']['speed']['value']
            ET.SubElement(monster,'str').text = str(d['abilities']['str']['value'])
            ET.SubElement(monster,'dex').text = str(d['abilities']['dex']['value'])
            ET.SubElement(monster,'con').text = str(d['abilities']['con']['value'])
            ET.SubElement(monster,'int').text = str(d['abilities']['int']['value'])
            ET.SubElement(monster,'wis').text = str(d['abilities']['wis']['value'])
            ET.SubElement(monster,'cha').text = str(d['abilities']['cha']['value'])
            ET.SubElement(monster,'save').text = ", ".join(['{} {:+d}'.format(k.title(),v['save']) for (k,v) in d['abilities'].items() if 'save' in v and (v['save'] != v['mod'] and v['proficient'])])
            ET.SubElement(monster,'skill').text = ", ".join(['{} {:+d}'.format(skills[k],v['total'] if 'total' in v else v['mod'] + v['prof'] if 'prof' in v else v['mod']) for (k,v) in d['skills'].items() if ('total' in v and v['mod'] != v['total']) or ('mod' in d['abilities'][v['ability']] and v['mod'] != d['abilities'][v['ability']]['mod'])])
            ET.SubElement(monster,'immune').text = "; ".join(d['traits']['di']['value'])+(" {}".format(d['traits']['di']['special']) if 'special' in d['traits']['di'] and d['traits']['di']['special'] else "")
            ET.SubElement(monster,'vulnerable').text = "; ".join(d['traits']['dv']['value'])+(" {}".format(d['traits']['dv']['special']) if 'special' in d['traits']['dv'] and d['traits']['dv']['special'] else "")
            ET.SubElement(monster,'resist').text = "; ".join(d['traits']['dr']['value'])+(" {}".format(d['traits']['dr']['special']) if 'special' in d['traits']['dr'] and d['traits']['dr']['special'] else "")
            ET.SubElement(monster,'conditionImmune').text = ", ".join(d['traits']['ci']['value'])+(" {}".format(d['traits']['ci']['special']) if 'special' in d['traits']['ci'] and d['traits']['ci']['special'] else "")
            if 'senses' in d['traits']:
                ET.SubElement(monster,'senses').text = d['traits']['senses']
            ET.SubElement(monster,'passive').text = str(d['skills']['prc']['passive']) if 'passive' in d['skills']['prc'] else ""
            ET.SubElement(monster,'languages').text = ", ".join(d['traits']['languages']['value'])+(" {}".format(d['traits']['languages']['special']) if 'special' in d['traits']['languages'] and d['traits']['languages']['special'] else "")
            ET.SubElement(monster,'description').text = fixHTMLContent((d['details']['biography']['value'] + "\n" + d['details']['biography']['public']).rstrip())
            if 'cr' in d['details']:
                ET.SubElement(monster,'cr').text = "{}/{}".format(*d['details']['cr'].as_integer_ratio()) if type(d['details']['cr']) != str and 0<d['details']['cr']<1  else str(d['details']['cr'])
            if 'source' in d['details']:
                ET.SubElement(monster,'source').text = d['details']['source']
            if 'environment' in d['details']:
                ET.SubElement(monster,'environments').text = d['details']['environment']
            if a['img']: a['img'] = urllib.parse.unquote(a['img'])
            if a['img'] and os.path.exists(a['img']):
                if os.path.splitext(a["img"])[1] == ".webp" and args.jpeg != ".webp":
                    PIL.Image.open(a["img"]).save(os.path.join(tempdir,"monsters",slugify(a['name'])+"_"+os.path.splitext(os.path.basename(a["img"]))[0]+args.jpeg))
                    os.remove(a["img"])
                    ET.SubElement(monster,'image').text = slugify(a['name'])+"_"+os.path.splitext(os.path.basename(a["img"]))[0]+args.jpeg
                else:
                    ET.SubElement(monster,'image').text = slugify(a['name'])+"_"+os.path.basename(a['img'])
                    shutil.copy(a['img'],os.path.join(tempdir,"monsters",slugify(a['name'])+"_"+os.path.basename(a['img'])))
            if a['token']['img']: a['token']['img'] = urllib.parse.unquote(a['token']['img'])
            if a['token']['img'] and os.path.exists(a['token']['img']):
                if os.path.splitext(a['token']["img"])[1] == ".webp" and args.jpeg != ".webp":
                    PIL.Image.open(a['token']["img"]).save(os.path.join(tempdir,"monsters","token_"+slugify(a['name'])+"_"+os.path.splitext(os.path.basename(a['token']["img"]))[0]+".png"))
                    os.remove(a['token']["img"])
                    ET.SubElement(monster,'image').text = "token_"+slugify(a['name'])+"_"+os.path.splitext(os.path.basename(a['token']["img"]))[0]+".png"
                else:
                    ET.SubElement(monster,'token').text = "token_"+slugify(a['name'])+"_"+os.path.basename(a['token']['img'])
                    shutil.copy(a['token']['img'],os.path.join(tempdir,"monsters","token_"+slugify(a['name'])+"_"+os.path.basename(a['img'])))
            equip = []
            for trait in a['items']:
                if trait['type'] == 'feat':
                    if trait['data']['activation']['type'] in ['action','reaction','legendary']:
                        typ = trait['data']['activation']['type']
                    else:
                        typ = 'trait'
                elif trait['type'] == 'weapon':
                    typ = 'action'
                else:
                    if trait['type'] == 'equipment':
                        equip.append("<item>{}</item>".format(trait['name']))
                    continue
                el = ET.SubElement(monster,typ)
                ET.SubElement(el,'name').text = trait['name']
                txt = ET.SubElement(el,'text')
                txt.text = fixHTMLContent(trait['data']['description']['value'])
                txt.text = re.sub(r'^((?:<[^>]*?>)*){}\.?((?:<\/[^>]*?>)*)\.?'.format(re.escape(trait['name'])),r'\1\2',txt.text)
            if len(equip) > 0:
                trait = ET.SubElement(monster,'trait')
                ET.SubElement(trait,'name').text = "Equipment"
                ET.SubElement(trait,'text').text = ", ".join(equip)
        tree = ET.ElementTree(indent(compendium, 1))
        if args.gui:
            worker.updateProgress(86)
            worker.outputLog("Generating compendium.xml")
        tree.write(os.path.join(tempdir,"compendium.xml"), xml_declaration=True, short_empty_elements=False, encoding='utf-8')
    os.chdir(cwd)
    if args.gui:
        worker.updateProgress(90)
        worker.outputLog("Zipping module")
    if args.packdir:
        zipfilename = "{}.pack".format(mod['name'])
    else:
        zipfilename = "{}.module".format(mod['name'])
    # zipfile = shutil.make_archive("module","zip",tempdir)
    if args.output:
        zipfilename = args.output
    zippos = 0
    with zipfile.ZipFile(zipfilename, 'w',compression=zipfile.ZIP_DEFLATED) as zipObj:
       # Iterate over all the files in directory
       for folderName, subfolders, filenames in os.walk(tempdir):
           if args.packdir and os.path.commonprefix([folderName,packdir]) != packdir:
               continue
           if args.gui:
               worker.updateProgress(90+10*(zippos/len(list(os.walk(os.path.abspath(tempdir))))))
               zippos += 1
           for filename in filenames:
               #create complete filepath of file in directory
               filePath = os.path.join(folderName, filename)
               # Add file to zip
               sys.stderr.write("\033[K")
               print("\rAdding: {}".format(filename),file=sys.stderr,end='')
               zipObj.write(filePath, filename if args.packdir else os.path.relpath(filePath,tempdir)) 
    sys.stderr.write("\033[K")
    print("\rDeleteing temporary files",file=sys.stderr,end='')
    shutil.rmtree(tempdir)
    tempdir = None
    sys.stderr.write("\033[K")
    print("\rFinished creating module: {}".format(zipfilename),file=sys.stderr)
    if args.gui:
        worker.updateProgress(100)
        worker.outputLog("Finished.")

if args.gui:
    import icon
    from PyQt5.QtGui import QIcon,QPixmap
    from PyQt5.QtCore import QObject,QThread,pyqtSignal,pyqtSlot,QRect,QCoreApplication,QMetaObject,Qt
    from PyQt5.QtWidgets import *#QApplication,QFileDialog,QDialog,QProgressBar,QPushButton,QTextEdit,QLabel,QCheckBox,QMessageBox,QMenuBar,QAction

    class Worker(QThread):
        def __init__(self,parent = None):
            QThread.__init__(self,parent)
            #self.exiting = False
            args = None
        progress = pyqtSignal(int)
        message = pyqtSignal(str)
        #def __del__(self):
        #    self.exiting = True
        #    self.wait()
        def convert(self,args):
            self.args = args
            self.start()
        def updateProgress(self,pct):
            self.progress.emit(math.floor(pct))
        def outputLog(self,msg):
            self.message.emit(msg)
        def run(self):
            try:
                convert(args,self)
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
        def __init__(self,parent = None):
            QThread.__init__(self,parent)
            #self.exiting = False
            manifesturl = None
        progress = pyqtSignal(int)
        message = pyqtSignal(str)
        #def __del__(self):
        #    self.exiting = True
        #    self.wait()
        def download(self,manifesturl):
            self.manifesturl = manifesturl
            self.start()
        def updateProgress(self,pct):
            self.progress.emit(math.floor(pct))
        def sendMessage(self,msg):
            self.message.emit(msg)
        def run(self):
            try:
                global tempdir
                tempdir = tempfile.mkdtemp(prefix="convertfoundry_")
                urllib.request.urlretrieve(self.manifesturl,os.path.join(tempdir,"manifest.json"))
                with open(os.path.join(tempdir,"manifest.json")) as f:
                    manifest = json.load(f)
                self.sendMessage("Downloading: {}".format(manifest["title"]))
                def progress(block_num, block_size, total_size):
                    pct = 100.00*((block_num * block_size)/total_size)
                    self.updateProgress(pct)
                urllib.request.urlretrieve(manifest['download'],os.path.join(tempdir,"module.zip"),progress)
                self.sendMessage("DONE")
            except Exception as e:
                self.sendMessage("An error occurred downloading the manifest:" + str(e))

    class GUI(QDialog):
        def setupUi(self, Dialog):
            Dialog.setObjectName("Dialog")
            Dialog.resize(400, 350)
            Dialog.setFixedSize(400, 350)
            self.opacity = QGraphicsOpacityEffect()
            self.opacity.setOpacity(0.1) 
            self.icon = QLabel(Dialog)
            self.icon.setGeometry(QRect(50, 25, 300, 300))
            self.icon.setPixmap(QPixmap(":/Icon.png").scaled(300,300))
            self.icon.setGraphicsEffect(self.opacity)
            #self.icon.show()
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
            #self.jpeg = QCheckBox(Dialog)
            self.jpeg = QComboBox(Dialog)
            self.jpeg.addItems(["Do not convert WebP Files","Convert all WebP Files to PNG","Convert WebP Maps to JPEG & assets to PNG"])
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

            exitAct = QAction('&Exit', self)
            exitAct.setShortcut('Ctrl+Q')
            exitAct.setStatusTip('Exit application')
            exitAct.triggered.connect(app.quit)

            openAct = QAction('&Open…', self)
            openAct.setShortcut('Ctrl+O')
            openAct.setStatusTip('Open Foundry ZIP File')
            openAct.triggered.connect(self.openFile)

            openManifestAct = QAction('Open Manifest &Url…', self)
            openManifestAct.setShortcut('Ctrl+U')
            openManifestAct.setStatusTip('Download File from Manifest at URL')
            openManifestAct.triggered.connect(self.openManifest)

            createPackAct = QAction('Create Asset &Pack…', self)
            createPackAct.setStatusTip('Create an Asset Pack instead of a Module')
            createPackAct.setEnabled(False)
            createPackAct.triggered.connect(self.selectPack)
            self.createPackAct = createPackAct

            fileMenu = menubar.addMenu('&File')
            fileMenu.addAction(openAct)
            fileMenu.addAction(openManifestAct)
            fileMenu.addAction(createPackAct)
            fileMenu.addAction(exitAct)

            aboutAct = QAction('&About', self)
            aboutAct.setStatusTip('About FoundryToEncounter')
            aboutAct.triggered.connect(self.showAbout)

            helpMenu = menubar.addMenu('&Help')
            helpMenu.addAction(aboutAct)

            self.retranslateUi(Dialog)
            QMetaObject.connectSlotsByName(Dialog)
        def retranslateUi(self, Dialog):
            _translate = QCoreApplication.translate
            Dialog.setWindowTitle(_translate("Dialog", "Foundry to Encounter"))
            self.browseButton.setText(_translate("Dialog", "Browse..."))
            self.compendium.setText(_translate("Dialog", "Include Compendium"))
            #self.jpeg.setText(_translate("Dialog", "Convert WebP to JPG instead of PNG"))
            self.convert.setText(_translate("Dialog", "Convert"))
        def __init__(self):
            super(GUI, self).__init__()
            #uic.loadUi('foundrytoencounter.ui', self)
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
            self.openFile()

        def clearFiles(self):
            self.foundryFile = None
            self.outputFile = ""
            self.label.setText("")
            self.label.setVisible(False)
            self.convert.setEnabled(False)
            self.createPackAct.setEnabled(False)

        def setFiles(self,filename,name):
            self.foundryFile = filename
            self.outputFile = "{}.module".format(name)
            self.createPackAct.setEnabled(True)
            self.output.clear()

        def openFile(self):
            fileName = QFileDialog.getOpenFileName(self,"Open Foundry ZIP File","","Foundry Archive (*.zip)")
            if not fileName[0] or not os.path.exists(fileName[0]):
                self.clearFiles()
                return
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
                self.setFiles(fileName[0],mod["name"])
                self.convert.setEnabled(True)
            else:
                alert = QMessageBox(self)
                alert.setWindowTitle("Invalid")
                alert.setText("No foundry data was found in this zip file.\nWould you like to convert it to an asset pack?")
                alert.setIcon(QMessageBox.Question)
                alert.setStandardButtons(QMessageBox.Cancel|QMessageBox.Yes)
                alert.setDefaultButton(QMessageBox.Cancel)
                btnid = alert.exec_()
                if btnid == QMessageBox.Cancel:
                    self.clearFiles()
                else:
                    self.label.setText("Asset Pack: {}".format(os.path.splitext(os.path.basename(fileName[0]))[0].title()))
                    self.setFiles(fileName[0],os.path.splitext(os.path.basename(fileName[0]))[0].title())
                    self.output.clear()
                    self.label.setVisible(True)
                    self.convert.setEnabled(True)
                    self.packdir = '.'
                    self.output.setVisible(True)
                    self.output.append("Will create asset pack with contents of "+fileName[0])
                    if self.outputFile.endswith(".module"):
                        self.outputFile = self.outputFile[:-7]+".pack"


        def openManifest(self):
            manifesturl,okPressed = QInputDialog.getText(self,"Download from Manifest","Manifest URL:",QLineEdit.Normal,"")
            if not okPressed:
                self.clearFiles()
                return
            self.manifestWorker.download(manifesturl)

        def selectPack(self):
            paths = []
            with zipfile.ZipFile(self.foundryFile) as z:
                for filename in z.namelist():
                    parent,f = os.path.split(filename)
                    if parent and parent not in paths:
                        paths.append(parent)
            packdir,okPressed = QInputDialog.getItem(self,"Create Asset Pack","Create Asset Pack from path:",paths)
            if not okPressed:
                self.packdir = None
                if self.outputFile.endswith(".pack"):
                    self.outputFile = self.outputFile[:-5]+".module"
                self.output.clear()
                self.output.setVisible(False)
                self.compendium.setEnabled(True)
            self.packdir = packdir
            if self.outputFile.endswith(".module"):
                self.outputFile = self.outputFile[:-7]+".pack"
            self.compendium.setEnabled(False)
            self.output.setVisible(True)
            self.output.append("Will create asset pack with contents of "+self.packdir)

        def manifestMessage(self,message):
            if message.startswith("Downloading:"):
                self.label.setText(message)
                self.label.setVisible(True)
                self.progress.setVisible(True)
            elif message == "DONE":
                self.progress.setVisible(False)
                with zipfile.ZipFile(os.path.join(tempdir,"module.zip")) as z:
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
                    self.setFiles(os.path.join(tempdir,"module.zip"),mod["name"])
                    self.convert.setEnabled(True)
                else:
                    QMessageBox.warning(self,"Invalid","No foundry data was found in this zip file")
                    self.clearFiles()
            else:
                QMessageBox.warning(self,"Error",message)
                self.clearFiles()


        def showAbout(self):
            QMessageBox.about(self,"About FoundryToEncounter","This utility converts a Foundry world or module to an EncounterPlus module.")
        def outputLog(self,text):
            self.output.append(text)
        def updateProgress(self,pct):
            self.progress.setValue(pct)

        def saveFile(self):
            if self.packdir:
                fileName = QFileDialog.getSaveFileName(self,"Save Asset Pack",self.outputFile,"EncounterPlus Asset Pack (*.pack)")
            else:
                fileName = QFileDialog.getSaveFileName(self,"Save Converted Module",self.outputFile,"EncounterPlus Module (*.module)")
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
    if sys.platform != "linux":
        app.setWindowIcon(QIcon(':/Icon.png'))
    gui = GUI()
    app.exec_()
else:
    convert()
