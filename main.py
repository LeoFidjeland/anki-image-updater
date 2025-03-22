import anki.collection
from anki.collection import Collection
from pprint import pprint
import json

col = Collection("/Users/leofidjeland/Library/Application Support/Anki2/Leo/collection.anki2")
noteIds = col.find_notes("deck:\"ལམ་རིམ་\"")

def getNotetypeNameFromId(modelId):
    model = col.models.get(modelId)
    return model['name']

def getNotetypeNameFromNote(note):
    model = col.models.get(note.mid)
    return model['name']

#note = col.get_note(notes[0])
#notetypeName = getNotetypeNameFromNote(note)

##pprint(vars(note))

def getDecksForNote(note):

    if isinstance(note, int):
        note = col.get_note(note)

    dids = col.db.list("select distinct did from cards where nid = {0}".format(note.id))
    #pprint(dids)
    decks = []
    for did in dids:
        name = col.decks.name(did)
        print(name)
        decks.append({'name':name, 'id':did})
    #pprint(decks)
    return decks

def getNoteInfo(note, print):

    if isinstance(note, int):
        note = col.get_note(note)

    fieldsAndValues = {}
    for key, value in note._fmap.items():
        idx = value[0]
        name = value[1]['name']
        value = note.fields[idx]
        ##print('({0}) {1} : {2}'.format(idx, name, value))
        fieldsAndValues[name] = value
    output = {
        'nid': note.id,
        'fields': fieldsAndValues,
        'model_name':   getNotetypeNameFromNote(note),
        'mid': note.mid,
        'tags': note.tags,
        'decks': getDecksForNote(note)
    }
    if print:
        pprint(output)
    return output

output = []

count = 0

for noteId in noteIds:
    output.append(getNoteInfo(noteId, True))
    count += 1

print(len(output))

with open('grammarcards.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=4)


col.close()