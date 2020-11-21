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
import random

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
    dest="srcfile",
    action='store',
    default=False,
    nargs=1,
    help="foundry file to convert")

args = parser.parse_args()

tempdir = tempfile.mkdtemp(prefix="convertfoundry_")
moduletmp = os.path.join(tempdir,"modules")
os.mkdir(moduletmp)
worldtmp = os.path.join(tempdir,"worlds")
os.mkdir(worldtmp)
nsuuid = uuid.UUID("ee9acc6e-b94a-472a-b44d-84dc9ca11b87")

numbers = ['zero','one','two','three','four']
stats = {"str":"Strength","dex":"Dexterity","con":"Constitution","int":"Intelligence","wis":"Wisdom","cha":"Charisma"}

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
def createMap(map,mapgroup):
    map["offsetX"] = (map["width"] + math.ceil(0.5 * map["width"] / (map["grid"] * 2)) * (map["grid"] * 2) - map["width"]) * 0.5
    map["offsetY"] = (map["height"] + math.ceil(0.5 * map["height"] / (map["grid"] * 2)) * (map["grid"] * 2) - map["height"]) * 0.5

    mapbaseslug = slugify(map['name'])
    mapslug = mapbaseslug + str(len([i for i in slugs if mapbaseslug in i]))
    slugs.append(mapslug)
    if not map["img"] and map["tiles"][0]["width"] >= map["width"] and map["tiles"][0]["height"] >= map["height"]:
        bg = map["tiles"].pop(0)
        imgext = os.path.splitext(os.path.basename(urllib.parse.urlparse(bg["img"]).path))[1]
        if not imgext:
            imgext = ".png"
        if imgext == ".webp":
            PIL.Image.open(bg["img"]).save(os.path.join(tempdir,os.path.splitext(bg["img"])[0]+".png"))
            map["img"] = os.path.splitext(bg["img"])[0]+".png"
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
        map["width"] *= map["rescale"]
        map["height"] *= map["rescale"]
        map['shiftX'] *= map["rescale"]
        map['shiftY'] *= map["rescale"]

    mapentry = ET.SubElement(module,'map',{'id': map['_id'],'parent': mapgroup,'sort': str(int(map["sort"]))})
    ET.SubElement(mapentry,'name').text = map['name']
    ET.SubElement(mapentry,'slug').text = mapslug
    ET.SubElement(mapentry,'gridSize').text = str(round(map["grid"]))#*(5.0/map["gridDistance"])))
    ET.SubElement(mapentry,'gridScale').text = str(round(map["gridDistance"]))#*((5.0/map["gridDistance"]))))
    ET.SubElement(mapentry,'gridUnits').text = str(map["gridUnits"])
    ET.SubElement(mapentry,'gridVisible').text = "YES" if map['gridAlpha'] > 0 else "NO"
    ET.SubElement(mapentry,'gridColor').text = map['gridColor']
    ET.SubElement(mapentry,'gridOffsetX').text = str(round(map['shiftX']))
    ET.SubElement(mapentry,'gridOffsetY').text = str(round(map['shiftY']))

    if map["img"]:
        imgext = os.path.splitext(os.path.basename(map["img"]))[1]
        if imgext == ".webp":
            ET.SubElement(mapentry,'image').text = os.path.splitext(map["img"])[0]+".png"
        else:
            ET.SubElement(mapentry,'image').text = map["img"]
        with PIL.Image.open(map["img"]) as img:
            if img.width > 8192 or img.height > 8192:
                scale = 8192/img.width if img.width>=img.height else 8192/img.height
                img = img.resize((round(img.width*scale),round(img.height*scale)))
                if imgext == ".webp":
                    img.save(os.path.join(tempdir,os.path.splitext(map["img"])[0]+".png"))
                else:
                    img.save(os.path.join(tempdir,map["img"]))
            elif imgext == ".webp":
                    img.save(os.path.join(tempdir,os.path.splitext(map["img"])[0]+".png"))
            if map["height"] != img.height or map["width"] != img.width:
                map["scale"] = map["width"]/img.width if map["width"]/img.width >= map["height"]/img.height else map["height"]/img.height
            else:
                map["scale"] = 1.0
    else:
        print(" |> Map Error NO BG FOR: {}".format(map["name"]),file=sys.stderr,end='')
        map["scale"] = 1.0
        if 'thumb' in map and map["thumb"]:
            imgext = os.path.splitext(os.path.basename(map["img"]))[1]
            if imgext == ".webp":
                ET.SubElement(mapentry,'snapshot').text = os.path.splitext(map["thumb"])[0]+".png"
                PIL.Image.open(map["thumb"]).save(os.path.join(tempdir,os.path.splitext(map["thumb"])[0]+".png"))
            else:
                ET.SubElement(mapentry,'snapshot').text = map["thumb"]

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
                    pWall.set('id',pWallID+' '+p['_id'])
                    lastpath.text += ','+','.join("{:.1f}".format(x) for x in pathlist)
                    break
            if not isConnected:
                wall = ET.SubElement(mapentry,'wall',{'id': p['id'] if 'id' in p else p['_id'] })
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
            ET.SubElement(asset,'type').text = "image"
            imgext = os.path.splitext(os.path.basename(image["img"]))[1]
            if image["img"].startswith("http"):
                urllib.request.urlretrieve(image["img"],os.path.basename(image["img"]))
                image["img"] = os.path.basename(image["img"])
            img = PIL.Image.open(image["img"])
            if imgext == ".webp":
                ET.SubElement(asset,'resource').text = os.path.splitext(image["img"])[0]+".png"
                if img.width > 4096 or img.height > 4096:
                    scale = 4095/img.width if img.width>=img.height else 4095/img.height
                    img = img.resize((round(img.width*scale),round(img.height*scale)))
                img.save(os.path.join(tempdir,os.path.splitext(image["img"])[0]+".png"))
            else:
                ET.SubElement(asset,'resource').text = image["img"]
                if img.width > 4096 or img.height > 4096:
                    scale = 4095/img.width if img.width>=img.height else 4095/img.height
                    img = img.resize((round(img.width*scale),round(img.height*scale)))
                    img.save(os.path.join(tempdir,image["img"]))
    return mapslug

with zipfile.ZipFile(args.srcfile[0]) as z:
    journal = []
    maps = []
    folders = []
    actors = []
    items = []
    tables = []
    mod = None
    isworld = False
    for filename in z.namelist():
        if filename.endswith("world.json"):
            with z.open(filename) as f:
                mod = json.load(f)
            isworld = True
        elif not mod and filename.endswith("module.json"):
            with z.open(filename) as f:
                mod = json.load(f)
        elif filename.endswith("folders.db"):
            with z.open(filename) as f:
                l = f.readline().decode('utf8')
                while l:
                    folder = json.loads(l)
                    folders.append(folder)
                    l = f.readline().decode('utf8')
                f.close()
        elif filename.endswith("journal.db"):
            with z.open(filename) as f:
                l = f.readline().decode('utf8')
                while l:
                    jrn = json.loads(l)
                    journal.append(jrn)
                    l = f.readline().decode('utf8')
                f.close()
        elif filename.endswith("scenes.db"):
            with z.open(filename) as f:
                l = f.readline().decode('utf8')
                while l:
                    scene = json.loads(l)
                    maps.append(scene)
                    l = f.readline().decode('utf8')
                f.close()
        elif filename.endswith("actors.db"):
            with z.open(filename) as f:
                l = f.readline().decode('utf8')
                while l:
                    actor = json.loads(l)
                    actors.append(actor)
                    l = f.readline().decode('utf8')
                f.close()
        elif filename.endswith("items.db"):
            with z.open(filename) as f:
                l = f.readline().decode('utf8')
                while l:
                    item = json.loads(l)
                    items.append(item)
                    l = f.readline().decode('utf8')
                f.close()
        elif filename.endswith("tables.db"):
            with z.open(filename) as f:
                l = f.readline().decode('utf8')
                while l:
                    table = json.loads(l)
                    tables.append(table)
                    l = f.readline().decode('utf8')
                f.close()
    for pack in mod['packs']:
        pack['path'] = pack['path'][1:] if os.path.isabs(pack['path']) else pack['path']
        if pack['entity'] == 'JournalEntry':
            with z.open(os.path.join(mod['name'],pack['path'])) as f:
                l = f.readline().decode('utf8')
                while l:
                    jrn = json.loads(l)
                    journal.append(jrn)
                    l = f.readline().decode('utf8')
                f.close()
        if pack['entity'] == 'Scene':
            with z.open(os.path.join(mod['name'],pack['path'])) as f:
                l = f.readline().decode('utf8')
                while l:
                    scene = json.loads(l)
                    maps.append(scene)
                    l = f.readline().decode('utf8')
                f.close()
        if pack['entity'] == 'Actor':
            with z.open(os.path.join(mod['name'],pack['path'])) as f:
                l = f.readline().decode('utf8')
                while l:
                    actor = json.loads(l)
                    actors.append(actor)
                    l = f.readline().decode('utf8')
                f.close()
    print(mod["title"])
    global moduuid
    if isworld:
        z.extractall(path=worldtmp)
    else:
        z.extractall(path=moduletmp)
moduuid = uuid.uuid5(nsuuid,mod["name"])
slugs = []
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
category.text = "adventure"
code = ET.SubElement(module, 'code')
code.text = mod['name']
slug = ET.SubElement(module, 'slug')
slug.text = slugify(mod['title'])
description = ET.SubElement(module, 'description')
description.text = re.sub(r'<.*?>','',mod['description'])
modimage = ET.SubElement(module, 'image')
order = 0
cwd = os.getcwd()
os.chdir(tempdir)
maxorder = 0
for f in folders:
    f['sort'] = 0 if 'sort' not in f or f['sort'] == None else f['sort']
    if f['sort'] > maxorder:
        maxorder = f['sort']
for j in journal:
    j['sort'] = 0 if 'sort' not in j or j['sort'] == None else j['sort']
    if 'flags' in j and 'R20Converter' in j['flags'] and 'handout-order' in j['flags']['R20Converter']:
        j['sort'] += j['flags']['R20Converter']['handout-order']
    if j['sort'] > maxorder:
        maxorder = j['sort']
for m in maps:
    m['sort'] = 0 if 'sort' not in m or m['sort'] == None else m['sort']
    if m['sort'] and m['sort'] > maxorder:
        maxorder = m['sort']
for f in folders:
    print("\rCreating Folders [{}/{}] {:.0f}%".format(order,len(folders),order/len(folders)*100),file=sys.stderr,end='')
    if f['type'] not in ["JournalEntry","RollTable"]:
        continue
    folder = ET.SubElement(module,'group', { 'id': str(f['_id']), 'sort': str(int(f['sort'])) } )
    ET.SubElement(folder,'name').text = f['name']
    if f['parent'] != None:
        folder.set('parent',f['parent'])
    order += 1
order = 0
for j in journal:
    order += 1
    print("\rConverting journal [{}/{}] {:.0f}%".format(order,len(journal),order/len(journal)*100),file=sys.stderr,end='')
    page = ET.SubElement(module,'page', { 'id': str(j['_id']), 'sort': str(j['sort'] or order) } )
    if j['folder'] != None:
        page.set('parent',j['folder'])
    ET.SubElement(page,'name').text = j['name']
    ET.SubElement(page,'slug').text = slugify(j['name'])
    content = ET.SubElement(page,'content')
    content.text = j['content'] or ""
    def fixLink(m):
        if m.group(2) == "JournalEntry":
            return '<a href="/page/{}" {} {} {}'.format(m.group(4),m.group(1),m.group(3),m.group(5))
        if m.group(2) == "Actor":
            for a in actors:
                if a['_id'] == m.group(4):
                    return '<a href="/monster/{}" {} {} {}'.format(slugify(a['name']),m.group(1),m.group(3),m.group(5))
        return m.group(0)
    content.text = re.sub(r'<a(.*?)data-entity="?(.*?)"? (.*?)data-id="?(.*?)"?( .*?)?>',fixLink,content.text)
    def fixFTag(m):
        if m.group(1) == "JournalEntry":
            return '<a href="/page/{}">{}</a>'.format(m.group(2),m.group(3) or "Journal Entry")
        if m.group(1) == "RollTable":
            return '<a href="/page/{}">{}</a>'.format(m.group(2),m.group(3) or "Roll Table")
        if m.group(1) == "Scene":
            return '<a href="/map/{}">{}</a>'.format(m.group(2),m.group(3) or "Map")
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
        return m.group(0)
    content.text = re.sub(r'@(.*?)\[(.*?)\](?:\{(.*?)\})?',fixFTag,content.text)
    def fixRoll(m):
        if m.group(2):
            return '<a href="/roll/{0}/{1}">{1}</a>'.format(m.group(1),m.group(2))
        else:
            return '<a href="/roll/{0}">{0}</a>'.format(m.group(1))
    content.text = re.sub(r'\[\[(?:/(?:gm)?r(?:oll)? )?(.*?)(?: ?# ?(.*?))?\]\]',fixRoll,content.text)
    if 'img' in j and j['img']:
        content.text += '<img src="{}">'.format(j["img"])
order = 0
if len(tables) > 0:
    tablesbaseslug = 'tables'
    tablesslug = tablesbaseslug + str(len([i for i in slugs if tablesbaseslug in i]))
    tablesgroup = str(uuid.uuid5(moduuid,tablesslug))
    group = ET.SubElement(module, 'group', {'id': tablesgroup, 'sort': str(int(maxorder+1))})
    ET.SubElement(group, 'name').text = "Roll Tables"
    ET.SubElement(group, 'slug').text = tablesslug
for t in tables:
    order += 1
    print("\rConverting tables [{}/{}] {:.0f}%".format(order,len(tables),order/len(tables)*100),file=sys.stderr,end='')
    page = ET.SubElement(module,'page', { 'id': str(t['_id']), 'parent': tablesgroup, 'sort': str(t['sort'] or order) } )
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
        if os.path.exists(r['img']):
            content.text += '<td style="width:50px;height:50px;"><img src="{}"></td>'.format(r['img'])
        else:
            content.text += '<td style="width:50px;height:50px;">&nbsp;</td>'
        content.text += '</tr>'
    content.text += "</tbody></table>"
    def fixRoll(m):
        if m.group(2):
            return '<a href="/roll/{0}/{1}">{1}</a>'.format(m.group(1),m.group(2))
        else:
            return '<a href="/roll/{0}">{0}</a>'.format(m.group(1))
    content.text = re.sub(r'\[\[(?:/(?:gm)?r(?:oll)? )?(.*?)(?: ?# ?(.*?))?\]\]',fixRoll,content.text)

mapcount = 0
if len(maps) > 0:
    mapsbaseslug = 'maps'
    mapsslug = mapsbaseslug + str(len([i for i in slugs if mapsbaseslug in i]))
    mapgroup = str(uuid.uuid5(moduuid,mapsslug))
    group = ET.SubElement(module, 'group', {'id': mapgroup, 'sort': str(int(maxorder+2))})
    ET.SubElement(group, 'name').text = "Maps"
    ET.SubElement(group, 'slug').text = mapsslug
    for map in maps:
        if not modimage.text and map["name"].lower() in ["start","start here","title page","title","landing","landing page"]:
            modimage.text = map["img"] or map["tiles"][0]["img"]
        if not map["img"] and len(map["tiles"]) == 0:
            continue
        mapcount += 1
        sys.stderr.write("\033[K")
        print("\rConverting maps [{}/{}] {:.0f}%".format(mapcount,len(maps),mapcount/len(maps)*100),file=sys.stderr,end='')
        createMap(map,mapgroup)
if not modimage.text:
    map = random.choice(maps)
    with PIL.Image.open(map["img"] or map["tiles"][0]["img"]) as img:
        if img.width >= img.width:
            img.crop((0,0,img.width,img.width))
        else:
            img.crop((0,0,img.height,img.height))
        if img.width > 1024:
            img.resize((1024,1024))
        img.save(os.path.join(tempdir,"module_cover.png"))
    modimage.text = "module_cover.png"
os.chdir(cwd)
# write to file
sys.stderr.write("\033[K")
print("\rWriting XML",file=sys.stderr,end='')
tree = ET.ElementTree(indent(module, 1))
tree.write(os.path.join(tempdir,"module.xml"), xml_declaration=True, short_empty_elements=False, encoding='utf-8')
zipfilename = "{}.module".format(mod['name'])
# zipfile = shutil.make_archive("module","zip",tempdir)
if args.output:
    zipfilename = args.output
with zipfile.ZipFile(zipfilename, 'w',compression=zipfile.ZIP_DEFLATED) as zipObj:
   # Iterate over all the files in directory
   for folderName, subfolders, filenames in os.walk(tempdir):
       for filename in filenames:
           #create complete filepath of file in directory
           filePath = os.path.join(folderName, filename)
           # Add file to zip
           sys.stderr.write("\033[K")
           print("\rAdding: {}".format(filename),file=sys.stderr,end='')
           zipObj.write(filePath, os.path.relpath(filePath,tempdir)) 
sys.stderr.write("\033[K")
print("\rDeleteing temporary files",file=sys.stderr,end='')
shutil.rmtree(tempdir)
sys.stderr.write("\033[K")
print("\rFinished creating module: {}".format(zipfilename),file=sys.stderr)
